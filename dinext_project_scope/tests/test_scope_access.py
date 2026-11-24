from io import BytesIO
from secrets import token_hex
from unittest import TestCase
from unittest.mock import patch

import frappe
import frappe.share
from frappe.desk.query_report import run
from frappe.tests.utils import FrappeTestCase
from openpyxl import load_workbook

from dinext_project_scope.analytics import dynamics, export
from dinext_project_scope.tests.project_fixture import make_project, project_user_roles
from dinext_project_scope.tests.scope_ui_test_helpers import create_report_fixture


class TestScopeReportPermissions(FrappeTestCase):
	def test_change_impact_download_keeps_two_permitted_projects_and_excludes_the_third(self):
		frappe.set_user("Administrator")
		fixture = create_report_fixture(token_hex(8))
		prefix = fixture["title"]
		try:
			frappe.set_user(fixture["actor"])
			export.download("Project Change Impact Matrix", {})
			workbook = load_workbook(BytesIO(frappe.response["filecontent"]), read_only=True)
			try:
				values = {value for row in workbook.worksheets[0].values for value in row}
				self.assertIn(f"{prefix} change", values)
				self.assertIn(f"{prefix} rollout change", values)
				self.assertIn(f"{prefix} secondary", values)
				self.assertNotIn(f"{prefix} hidden change", values)
				self.assertNotIn(f"{prefix} hidden", values)
			finally:
				workbook.close()
		finally:
			for key in ("type", "filename", "filecontent"):
				frappe.response.pop(key, None)
			frappe.set_user("Administrator")

	def test_project_reports_use_scope_permissions_and_deny_other_projects(self):
		frappe.set_user("Administrator")
		prefix = f"Scope reports {frappe.generate_hash(length=10)}"
		project = make_project(prefix, prefix)
		other = make_project(f"{prefix} hidden", f"{prefix} hidden", project.project_type)
		user = frappe.get_doc(
			doctype="User",
			email=f"scope-report-{frappe.generate_hash(length=10)}@example.test",
			first_name="Scope report reader",
			send_welcome_email=0,
			roles=project_user_roles(),
		).insert()
		frappe.share.add("Project", project.name, user=user.name, read=1, write=0, notify=0)
		frappe.get_doc(
			doctype="User Permission",
			user=user.name,
			allow="Project",
			for_value=project.name,
			apply_to_all_doctypes=1,
		).insert()
		try:
			frappe.set_user(user.name)
			self.assertEqual(dynamics.project_result_dynamics(project.name)["category"]["count"], 0)
			with self.assertRaises(frappe.PermissionError):
				dynamics.project_result_dynamics(other.name)
			for report in ("Project Scope Overview", "Project Constraint Register"):
				with self.subTest(report=report):
					result = run(report, filters={"project": project.name}, ignore_prepared_report=True)
					self.assertIn("result", result)
					with self.assertRaises(frappe.PermissionError):
						run(report, filters={"project": other.name}, ignore_prepared_report=True)
		finally:
			frappe.set_user("Administrator")

	def test_responsibility_export_denies_access_revoked_after_report_run(self):
		frappe.set_user("Administrator")
		prefix = f"Scope export {frappe.generate_hash(length=10)}"
		project = make_project(prefix, prefix)
		other = make_project(f"{prefix} retained", f"{prefix} retained", project.project_type)
		user = frappe.get_doc(
			doctype="User",
			email=f"scope-export-{frappe.generate_hash(length=10)}@example.test",
			first_name="Scope export reader",
			send_welcome_email=0,
			roles=project_user_roles(),
		).insert()
		permissions = {}
		for allowed in (project, other):
			frappe.share.add("Project", allowed.name, user=user.name, read=1, notify=0)
			permissions[allowed.name] = frappe.get_doc(
				doctype="User Permission",
				user=user.name,
				allow="Project",
				for_value=allowed.name,
				apply_to_all_doctypes=1,
			).insert().name
		report = "Project Responsibility Matrix"
		filters = {"project": project.name}
		try:
			frappe.set_user(user.name)
			self.assertIn("result", run(report, filters=filters, ignore_prepared_report=True))
			export.download(report, filters)
			self.assertTrue(frappe.response["filecontent"].startswith(b"PK"))

			frappe.set_user("Administrator")
			frappe.share.remove("Project", project.name, user.name)
			frappe.delete_doc("User Permission", permissions[project.name])

			frappe.set_user(user.name)
			with self.assertRaises(frappe.PermissionError):
				export.download(report, filters)
			self.assertIn("result", run(report, filters={"project": other.name}, ignore_prepared_report=True))
		finally:
			for key in ("type", "filename", "filecontent"):
				frappe.response.pop(key, None)
			frappe.set_user("Administrator")


class TestScopeAccess(TestCase):
	def setUp(self):
		translation = patch("dinext_project_scope.access._", side_effect=lambda value: value)
		translation.start()
		self.addCleanup(translation.stop)

	def test_child_target_requires_the_selected_project(self):
		from dinext_project_scope.access import validate_project_target

		row = frappe._dict(
			name="row", parent="other-project", parenttype="Project", parentfield="project_constraints"
		)
		with (
			patch("dinext_project_scope.access.check_project"),
			patch("dinext_project_scope.access._owned_row", return_value=row),
		):
			with self.assertRaises(frappe.ValidationError):
				validate_project_target("chosen-project", "Project Constraint", "row")

	def test_unknown_target_raises_before_document_loading(self):
		from dinext_project_scope.access import validate_project_target

		with self.assertRaises(frappe.ValidationError):
			validate_project_target("chosen-project", "User", "user@example.test", check_permission=False)

	def test_permission_hook_denies_explicitly_when_project_is_unreadable(self):
		from dinext_project_scope.access import project_document_permission

		doc = frappe._dict(doctype="Project Change Request", project="unreadable", status="Draft")
		with patch("dinext_project_scope.access.has_project_access", return_value=False):
			self.assertIs(project_document_permission(doc, "read", "user@example.test"), False)
