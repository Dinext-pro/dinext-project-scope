from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe
from frappe.handler import execute_cmd
from openpyxl import load_workbook

from dinext_project_scope import access, project_scope, requirements
from dinext_project_scope.analytics import data, export


class TestScopeTableWorkbooks(TestCase):
	def workbook(self, table, **arguments):
		with patch.object(export, "provide_binary_file") as deliver:
			export.download_project_scope_table("project", table, **arguments)
		filename, extension, content = deliver.call_args.args
		self.assertEqual((filename, extension), ("project-" + table.replace("_", "-"), "xlsx"))
		return load_workbook(BytesIO(content)).active

	def project(self, **tables):
		project = Mock()
		project.get.side_effect = tables.get
		return project

	def test_scope_items_export_intersects_facet_and_saved_grid_rows(self):
		project = self.project(
			project_scopes=[
				frappe._dict(
					name="visible", scope_title="=Visible", scope_type="Boundary", object_ref="Object"
				),
				frappe._dict(name="hidden-by-search", scope_title="Hidden by search", scope_type="Boundary"),
				frappe._dict(name="hidden-by-facet", scope_title="Hidden by facet", scope_type="Different"),
			]
		)
		with patch.object(access, "check_project", return_value=project) as read:
			sheet = self.workbook(
				"scope_items",
				filters='{"scope_type":"Boundary"}',
				row_names='["visible","hidden-by-facet","different-project","unsaved"]',
			)
		read.assert_called_once_with("project")
		project.check_permission.assert_called_once_with("export")
		project.apply_fieldlevel_read_permissions.assert_called_once_with()
		self.assertEqual(sheet.max_row, 2)
		self.assertEqual((sheet["A2"].value, sheet["A2"].data_type), ("=Visible", "s"))
		self.assertEqual(sheet["C2"].value, "Object")

	def test_download_supports_post_with_json_filters_and_row_names(self):
		project = self.project(
			project_scopes=[
				frappe._dict(name="saved", scope_title="Saved", scope_type="Boundary"),
			]
		)
		response = frappe._dict()
		with (
			patch.object(access, "check_project", return_value=project),
			patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True),
			patch.object(frappe.local, "response", response, create=True),
			patch.object(
				frappe.local,
				"form_dict",
				frappe._dict(
					project="project",
					table="scope_items",
					filters='{"scope_type":"Boundary"}',
					row_names='["saved"]',
				),
				create=True,
			),
		):
			execute_cmd("dinext_project_scope.analytics.export.download_project_scope_table")
		self.assertEqual((response.type, response.filename), ("binary", "project-scope-items.xlsx"))
		self.assertEqual(load_workbook(BytesIO(response.filecontent)).active["A2"].value, "Saved")

	def test_empty_native_selection_exports_headers(self):
		project = self.project(project_scopes=[frappe._dict(name="saved", scope_title="Saved")])
		with patch.object(access, "check_project", return_value=project):
			sheet = self.workbook("scope_items", row_names="[]")
		self.assertEqual(sheet.max_row, 1)

	def test_constraints_export_uses_typed_identity_and_permission_checked_full_name(self):
		project = self.project(
			project_constraints=[
				frappe._dict(
					name="user", subject="User constraint", responsible="same", responsible_type="User"
				),
				frappe._dict(
					name="contact",
					subject="Contact constraint",
					responsible="same",
					responsible_type="Contact",
				),
				frappe._dict(name="none", subject="Unassigned constraint"),
			]
		)
		with (
			patch.object(access, "check_project", return_value=project),
			patch.object(
				data,
				"select_rows",
				return_value={"same": {"full_name": "Readable Contact", "image": "/photo"}},
			) as profiles,
		):
			sheet = self.workbook("constraints", filters={"responsible": "Contact:same"})
			unassigned = self.workbook("constraints", filters={"responsible": data.ONLY_EMPTY})
		profiles.assert_called_once_with(
			"Contact", {"name": ["in", ["same"]]}, ["name", "full_name", "image"]
		)
		self.assertEqual(sheet.max_row, 2)
		self.assertEqual(sheet["A2"].value, "Contact constraint")
		self.assertEqual(sheet["E2"].value, "Readable Contact")
		self.assertEqual(unassigned["A2"].value, "Unassigned constraint")
		self.assertIsNone(unassigned["E2"].value)

	def test_requirements_export_preserves_ancestor_and_selected_specification_paths(self):
		rows = [
			{"name": "ROOT", "title": "Context requirement", "status": "New", "paths": [["SPEC"]]},
			{
				"name": "CHILD",
				"title": "Matched requirement",
				"parent": "ROOT",
				"status": "Done",
				"priority": "High",
				"kind": "Function",
				"requirement_importance": "Must",
				"author": "author",
				"author_profile": {"label": "Author Name"},
				"responsible": "responsible",
				"responsible_profile": {"label": "Responsible Name"},
				"paths": [["SPEC", "NESTED"]],
			},
			{"name": "OTHER", "title": "Unrelated requirement", "status": "Done", "paths": [["SPEC"]]},
		]
		with (
			patch.object(requirements, "project_rows", return_value=rows) as read,
			patch.object(frappe, "has_permission") as permission,
		):
			sheet = self.workbook(
				"requirements",
				filters={
					"status": "Done",
					"priority": "High",
					"kind": "Function",
					"requirement_importance": "Must",
				},
				specification="SPEC",
			)
		permission.assert_called_once_with(data.REQUIREMENT, "export", throw=True)
		read.assert_called_once_with("project", "SPEC")
		self.assertEqual(sheet.max_row, 3)
		self.assertEqual(
			(sheet["A2"].value, sheet["A3"].value), ("Context requirement", "Matched requirement")
		)
		self.assertEqual(sheet["E3"].value, "Author Name")
		self.assertEqual(sheet["G3"].value, "Responsible Name")
		self.assertEqual(sheet["H3"].value, "SPEC, NESTED")
		self.assertEqual(sheet["J3"].value, "ROOT")
		self.assertEqual(sheet["K3"].value, "SPEC → NESTED")
		self.assertEqual(sheet["A3"].alignment.indent, 1)
		self.assertEqual(sheet.row_dimensions[3].outlineLevel, 1)

	def test_requirements_export_preserves_direct_and_nested_paths(self):
		rows = [{"name": "REQ", "title": "A requirement", "paths": [[], ["SPEC"], ["SPEC", "NESTED"]]}]
		with (
			patch.object(requirements, "project_rows", return_value=rows),
			patch.object(frappe, "has_permission"),
		):
			sheet = self.workbook("requirements")
		self.assertEqual(sheet["H2"].value, "SPEC, NESTED")
		self.assertEqual(sheet["K2"].value.splitlines()[1:], ["SPEC", "SPEC → NESTED"])
		self.assertEqual(sheet["K2"].value.splitlines()[0], frappe._("Included directly"))

	def test_changes_export_matches_local_day_and_participants(self):
		matched = {
			"name": "CHANGE",
			"title": "Matched change",
			"creation": datetime(2026, 11, 27, 23, 45),
			"status": "New",
			"initiator": "same",
			"implementation_responsible": "same",
			"initiator_profile": {"label": "Readable Contact"},
			"implementation_responsible_profile": {"label": "Readable User"},
		}
		rows = [
			dict(matched, title="Wrong date", creation=datetime(2026, 11, 28)),
			dict(matched, title="Wrong initiator", initiator="other"),
			dict(matched, title="Wrong responsible", implementation_responsible="other"),
			dict(matched, title="Wrong status", status="Done"),
			matched,
		]
		with (
			patch.object(project_scope, "project_change_rows", return_value=rows) as read,
			patch.object(frappe, "has_permission") as permission,
		):
			sheet = self.workbook(
				"change_requests",
				filters={
					"status": "New",
					"creation": "2026-11-27",
					"initiator": "Contact:same",
					"implementation_responsible": "User:same",
				},
			)
		permission.assert_called_once_with(data.CHANGE_REQUEST, "export", throw=True)
		read.assert_called_once_with("project")
		self.assertEqual(sheet.max_row, 2)
		self.assertEqual((sheet["A2"].value, sheet["C2"].value), ("Matched change", "Readable User"))
		self.assertEqual(sheet["D2"].value, "Readable Contact")
		self.assertEqual(sheet["E2"].value, matched["creation"])

	def test_denied_project_and_doctype_export_do_not_send_workbooks(self):
		project = self.project(project_scopes=[])
		project.check_permission.side_effect = frappe.PermissionError
		with (
			patch.object(access, "check_project", return_value=project),
			patch.object(export, "provide_binary_file") as deliver,
			self.assertRaises(frappe.PermissionError),
		):
			export.download_project_scope_table("project", "scope_items")
		project.get.assert_not_called()
		deliver.assert_not_called()
		with (
			patch.object(frappe, "has_permission", side_effect=frappe.PermissionError),
			patch.object(requirements, "project_rows") as read,
			self.assertRaises(frappe.PermissionError),
		):
			export.download_project_scope_table("project", "requirements")
		read.assert_not_called()

	def test_invalid_table_and_unlisted_filter_arguments_are_rejected(self):
		for table, arguments in [
			("Project", {}),
			([], {}),
			("scope_items", {"filters": {"project": "other-project"}}),
			("scope_items", {"filters": '{"scope_type": ["Boundary"]}'}),
			("scope_items", {"row_names": '{"name": "another-project"}'}),
			("scope_items", {"row_names": "["}),
			("requirements", {"row_names": "[]"}),
		]:
			with self.subTest(table=table, arguments=arguments), self.assertRaises(frappe.ValidationError):
				export.download_project_scope_table("project", table, **arguments)

	def test_constraint_profiles_are_limited_to_saved_readable_project_assignments(self):
		from dinext_project_scope.analytics import scope_tables

		project = self.project(
			project_constraints=[
				frappe._dict(responsible_type="User", responsible="same"),
				frappe._dict(responsible_type="Contact", responsible="same"),
				frappe._dict(responsible_type="Employee", responsible="unsupported"),
			]
		)
		with (
			patch.object(access, "check_project", return_value=project) as read,
			patch.object(
				data,
				"select_rows",
				side_effect=[{"same": {"full_name": "Readable User", "user_image": "/photo"}}, {}],
			) as profiles,
		):
			result = scope_tables.project_constraint_profiles("project")
		read.assert_called_once_with("project")
		project.apply_fieldlevel_read_permissions.assert_called_once_with()
		self.assertEqual(
			profiles.call_args_list,
			[
				call("User", {"name": ["in", ["same"]]}, ["name", "full_name", "user_image"]),
				call("Contact", {"name": ["in", ["same"]]}, ["name", "full_name", "image"]),
			],
		)
		self.assertEqual(
			result,
			{
				"User:same": {"doctype": "User", "name": "same", "label": "Readable User", "image": "/photo"},
				"Contact:same": {"doctype": "Contact", "name": "same", "label": "same", "image": None},
			},
		)
		with (
			patch.object(access, "check_project", side_effect=frappe.PermissionError),
			patch.object(data, "select_rows") as profiles,
			self.assertRaises(frappe.PermissionError),
		):
			scope_tables.project_constraint_profiles("other-project")
		profiles.assert_not_called()
