from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.desk.query_report import run
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope.tests.project_fixture import make_project, project_user_roles


class TestScopeReportPermissions(FrappeTestCase):
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
			for report in ("Project Scope Overview", "Project Constraint Register"):
				with self.subTest(report=report):
					result = run(report, filters={"project": project.name}, ignore_prepared_report=True)
					self.assertIn("result", result)
					with self.assertRaises(frappe.PermissionError):
						run(report, filters={"project": other.name}, ignore_prepared_report=True)
		finally:
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
