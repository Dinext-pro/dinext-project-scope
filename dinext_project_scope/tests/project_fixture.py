"""Create a project compatible with both core and finance-enabled test sites."""

import frappe


def make_project(title, name, project_type=None):
	if not project_type:
		project_type = frappe.get_doc(doctype="Project Type", project_type=title).insert().name
	project = frappe.get_doc(doctype="Project", project_name=title, project_type=project_type)
	if project.meta.has_field("custom_payment_scheme"):
		project.custom_payment_scheme = frappe.db.get_value(
			"Project Payment Scheme", {}, "name", order_by="name asc"
		)
	return project.insert(set_name=name)
