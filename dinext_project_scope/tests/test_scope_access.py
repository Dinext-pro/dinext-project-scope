from unittest import TestCase
from unittest.mock import patch

import frappe


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
