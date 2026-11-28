from unittest import TestCase
from unittest.mock import patch

import frappe


class TestScopeValidation(TestCase):
	def test_assumption_decision_requires_evidence(self):
		from dinext_project_scope.project_scope import validate_constraint

		row = frappe._dict(
			name="assumption", record_type="Assumption", status="New", verification_status="Confirmed"
		)
		with patch("dinext_project_scope.project_scope._", side_effect=lambda text: text):
			with self.assertRaises(frappe.ValidationError):
				validate_constraint(row, "PRJ-1")

	def test_change_requires_configured_details_and_keeps_estimate_range(self):
		from dinext_project_scope.changes import validate_relation

		row = frappe._dict(
			name="impact", type="Schedule", direction="target", level="Strong", estimation="2\u20134 days"
		)
		kind = frappe._dict(enabled=1, uom="Day", reqd_explanation=0, reqd_estimation=1, reqd_link=0)
		with (
			patch("dinext_project_scope.changes.check_document", return_value=kind),
			patch("dinext_project_scope.changes._", side_effect=lambda text: text),
		):
			validate_relation(row, "PRJ-1")
		self.assertEqual(row.estimation, "2\u20134 days")
		self.assertEqual(row.uom, "Day")

	def test_workflow_submission_seals_impact_text_and_estimation(self):
		from dinext_project_scope.changes import change_snapshot

		doc = frappe._dict(
			title="Upgrade",
			project="PRJ-1",
			change_relations=[frappe._dict(type="Schedule", estimation="2\u20134")],
		)
		before = change_snapshot(doc)
		doc.change_relations[0].estimation = "4\u20136"
		self.assertNotEqual(before, change_snapshot(doc))

	def test_template_operation_key_is_scoped_to_user_and_project(self):
		from dinext_project_scope.template_application import operation_key

		key = operation_key("PRJ-1", "Project Constraints Template", "Template", "key-1", "user@example.test")
		self.assertEqual(
			key,
			operation_key("PRJ-1", "Project Constraints Template", "Template", "key-1", "user@example.test"),
		)
		self.assertNotEqual(
			key,
			operation_key("PRJ-2", "Project Constraints Template", "Template", "key-1", "user@example.test"),
		)
