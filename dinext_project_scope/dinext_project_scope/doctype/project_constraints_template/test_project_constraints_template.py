# Copyright (c) 2026, Dinext and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope.project_scope import apply_constraints_template, preview_constraints_template
from dinext_project_scope.tests.project_fixture import make_project


class TestProjectConstraintsTemplate(FrappeTestCase):
	def test_apply_keeps_distinct_assumptions_and_is_idempotent(self):
		tag = f"SCOPE-TEST-{frappe.generate_hash(length=10)}"
		project = make_project(tag, tag)
		category = frappe.get_doc(doctype="Project Deliverable Category", enabled=1).insert(
			set_name=frappe.generate_hash(length=10)
		)
		template = frappe.get_doc(
			doctype="Project Constraints Template",
			template_name=f"Template {frappe.generate_hash(length=10)}",
			project_constraints=[
				{
					"subject": "Availability",
					"category": category.name,
					"record_type": "Assumption",
					"status": "Template",
				}
			],
		).insert()
		preview = preview_constraints_template(project.name, template.name)
		key = frappe.generate_hash(length=24)
		first = apply_constraints_template(project.name, template.name, key, preview["digest"])
		self.assertEqual(
			first, apply_constraints_template(project.name, template.name, key, preview["digest"])
		)
		second = apply_constraints_template(
			project.name, template.name, frappe.generate_hash(length=24), preview["digest"]
		)
		self.assertNotEqual(first, second)
		rows = project.reload().project_constraints
		self.assertEqual([row.verification_status for row in rows], ["Pending", "Pending"])
		rows[0].verification_status = "Confirmed"
		rows[0].verification_note = "Resource availability confirmed."
		project.save()
		self.assertEqual(project.reload().project_constraints[0].verified_by, frappe.session.user)
