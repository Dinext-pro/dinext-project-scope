"""Prepare and inspect a disposable CI site's catalog round trip."""

import os

import frappe


def _require_ci_site():
	if os.environ.get("CI") != "true" or frappe.local.site != "localhost" or not frappe.conf.allow_tests:
		raise RuntimeError("Catalog acceptance requires the disposable CI localhost site.")


def snapshot(doctypes):
	_require_ci_site()
	return {
		doctype: [
			frappe.get_doc(doctype, name).as_dict()
			for name in frappe.get_all(doctype, pluck="name", order_by="name asc")
		]
		for doctype in doctypes
	}


def configure(doctypes, probe, blank_icon_type):
	_require_ci_site()
	for doctype in doctypes:
		doc = frappe.new_doc(doctype)
		if doctype == "Project Deliverable Responsibility":
			doc.responsibility = probe
		doc.insert(set_name=probe)

	role = frappe.get_doc(doctype="Project Role", role_name=probe, enabled=1).insert(set_name=probe)
	category = frappe.get_doc("Project Deliverable Category", "Управление проектом")
	category.append("responsibilities", {"project_role": role.name, "responsibility": "И"})
	category.save()

	kind = frappe.get_doc("Project Deliverable Type", "Документ")
	kind.color = "#244668"
	kind.icon = "/files/scope-ci-configured-icon.svg"
	kind.elements[0].weight = 2.5
	kind.append(
		"elements",
		{
			"element_key": "ci-retained-work",
			"element_name": probe,
			"element_type": "Task",
			"weight": 4,
			"is_optional": 1,
		},
	)
	kind.save()

	blank_icon = frappe.get_doc("Project Deliverable Type", blank_icon_type)
	blank_icon.icon = None
	blank_icon.save()

	changes = (
		("Project Deliverable Responsibility", "И", {"color": "#315273", "required": 0, "single": 1}),
		(
			"Project Change Relation Type",
			"Сроки",
			{
				"enabled": 0,
				"uom": "Hour",
				"reqd_estimation": 0,
				"reqd_explanation": 0,
				"reqd_link": 1,
				"link_doctype": "Task",
			},
		),
		("Project Scope Type", "Географический", {"enabled": 0, "object_doctype": "Project"}),
		("Requirement Kind", "Организационные", {"enabled": 0, "description": probe}),
	)
	for doctype, name, values in changes:
		doc = frappe.get_doc(doctype, name)
		doc.update(values)
		doc.save()
	return snapshot(doctypes)
