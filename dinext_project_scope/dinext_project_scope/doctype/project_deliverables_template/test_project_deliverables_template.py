# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope import deliverable_templates


class TestProjectDeliverablesTemplate(FrappeTestCase):
	def test_apply_recopies_local_links_in_child_first_order_and_replays_same_request(self):
		project_name = f"SCOPE-TEST-{frappe.generate_hash(length=8)}"
		project_type = frappe.get_doc(doctype="Project Type", project_type=project_name).insert().name
		project = frappe.get_doc(
			doctype="Project", project_name=project_name, project_type=project_type
		).insert(set_name=project_name)
		category = frappe.get_doc(
			doctype="Project Deliverable Category", name=frappe.generate_hash(length=8), enabled=1
		).insert()
		child_type = frappe.get_doc(
			doctype="Project Deliverable Type", name=frappe.generate_hash(length=8), enabled=1
		).insert()
		parent_type = frappe.get_doc(
			doctype="Project Deliverable Type",
			name=frappe.generate_hash(length=8),
			enabled=1,
			elements=[
				{
					"element_key": "child",
					"element_type": "Project Deliverable",
					"element_name": "Child work",
				}
			],
		).insert()
		template_name = f"Set {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			doctype="Project Deliverables Template",
			name=template_name,
			template_name=template_name,
			deliverables=[
				{
					"item_key": "a",
					"title": "Parent",
					"deliverable_type": parent_type.name,
					"category": category.name,
				},
				{
					"item_key": "b",
					"title": "Child",
					"deliverable_type": child_type.name,
					"category": category.name,
				},
				{
					"item_key": "c",
					"title": "Child",
					"deliverable_type": child_type.name,
					"category": category.name,
				},
			],
			elements=[{"owner_item_key": "a", "source_element_key": "child", "nested_item_key": "b"}],
		).insert()

		preview = deliverable_templates.preview_template(project.name, template.name)
		first = deliverable_templates.apply_template(project.name, template.name, preview["token"], "first")
		replay = deliverable_templates.apply_template(project.name, template.name, preview["token"], "first")
		another = deliverable_templates.apply_template(
			project.name, template.name, preview["token"], "second"
		)
		self.assertEqual(first["created"], replay["created"])
		self.assertNotEqual(first["created"], another["created"])
		for result in (first, another):
			parent = frappe.get_doc("Project Deliverable", result["created"]["a"])
			child = frappe.get_doc("Project Deliverable", result["created"]["b"])
			self.assertNotEqual(child.name, result["created"]["c"])
			self.assertEqual(parent.table_xuct[0].element, child.name)
			self.assertEqual(parent.status, "Not Started")
			self.assertEqual(child.status, "Not Started")
			self.assertEqual(child.project, project.name)
