from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope.install import before_install
from dinext_project_scope.setup.workflows import default_routes, ensure_default_workflows


class TestScopeWorkflowSetup(FrappeTestCase):
	def test_install_rejects_goal_doctype_without_dinext_project_links(self):
		with patch.object(frappe, "get_meta") as get_meta:
			get_meta.return_value.has_field.side_effect = lambda field: field == "goal_name"
			with self.assertRaisesRegex(frappe.ValidationError, "Dinext Goals"):
				before_install()
		before_install()

	def test_default_scope_routes_have_stable_transition_identities(self):
		routes = [f"Dinext {doctype}" for doctype, _, _ in default_routes()]

		def transitions():
			return frappe.get_all(
				"Workflow Transition",
				filters={"parenttype": "Workflow", "parent": ("in", routes)},
				fields=["name", "parent", "custom_transition_uuid"],
				order_by="parent asc, idx asc",
			)

		original = transitions()
		self.assertEqual({row.parent for row in original}, set(routes))
		identities = [row.custom_transition_uuid for row in original]
		self.assertTrue(all(identities), original)
		self.assertEqual(len(set(identities)), len(identities))
		ensure_default_workflows()
		self.assertEqual(transitions(), original)

	def test_only_stock_legacy_requirement_approver_conditions_are_upgraded(self):
		from frappe.model.workflow import is_transition_condition_satisfied

		name = "Dinext Project Requirement"
		workflow = frappe.get_doc("Workflow", name)
		rows = {row.action: row for row in workflow.transitions if row.state == "In Review"}
		approve, reject = rows["Approve"], rows["Reject"]
		legacy_condition = "doc.responsible == frappe.session.user"
		savepoint = "test_legacy_requirement_workflow"
		frappe.db.savepoint(savepoint)
		try:
			frappe.db.set_value(approve.doctype, approve.name, "condition", legacy_condition)
			frappe.db.set_value(reject.doctype, reject.name, "allowed", "Projects Manager")
			frappe.db.set_value(reject.doctype, reject.name, "condition", legacy_condition)
			frappe.clear_document_cache("Workflow", name)
			contact = frappe.get_doc(
				doctype="Contact",
				first_name=f"Workflow migration {frappe.generate_hash(length=8)}",
				user=frappe.session.user,
			).insert()
			requirement = frappe.get_doc(
				doctype="Project Requirement", responsible_type="Contact", responsible=contact.name
			)
			ensure_default_workflows()

			updated = frappe.get_doc(approve.doctype, approve.name)
			self.assertTrue(is_transition_condition_satisfied(updated, requirement))
			self.assertEqual(updated.custom_transition_uuid, approve.custom_transition_uuid)
			self.assertEqual(frappe.db.get_value(reject.doctype, reject.name, "condition"), legacy_condition)
		finally:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_document_cache("Workflow", name)
