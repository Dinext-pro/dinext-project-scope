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
