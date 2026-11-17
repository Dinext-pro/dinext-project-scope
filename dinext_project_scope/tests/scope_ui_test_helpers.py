"""Create and clean up isolated data for the scope Desk scenarios."""

import frappe
from frappe.tests.ui_test_helpers import whitelist_for_tests

from dinext_project_scope.tests.requirement_ui_test_helpers import _prefix, create_fixture, remove_fixture


@whitelist_for_tests(methods=["POST"])
def create_report_fixture(run_id):
	prefix = _prefix(run_id)
	seed = create_fixture(run_id)
	project = frappe.get_doc("Project", seed["project"])
	person = frappe.db.get_value("Contact", {"first_name": prefix}, "name")
	role = frappe.get_doc(doctype="Project Role", role_name=prefix, enabled=1).insert(set_name=prefix)
	category = frappe.get_doc(doctype="Project Deliverable Category", enabled=1).insert(set_name=prefix)
	kind = frappe.get_doc(doctype="Project Deliverable Type", enabled=1).insert(set_name=prefix)
	responsibility = frappe.get_doc(
		doctype="Project Deliverable Responsibility", responsibility=f"R-{run_id}", enabled=1, color="#2C7C70"
	).insert(set_name=prefix)
	impact = frappe.get_doc(
		doctype="Project Change Relation Type", enabled=1, link_doctype="Project Deliverable"
	).insert(set_name=prefix)
	project.append(
		"custom_ts_details",
		{"pt_role": role.name, "pt_participant_type": "User", "pt_participant": "Administrator"},
	)
	project.append("custom_contact_list", {"contact": person, "project_role": role.name})
	project.append(
		"project_constraints",
		{
			"subject": f"{prefix} assumption",
			"category": category.name,
			"record_type": "Assumption",
			"status": "New",
		},
	)
	project.save()
	result = frappe.get_doc(
		doctype="Project Deliverable",
		project=project.name,
		title=f"{prefix} result",
		deliverable_type=kind.name,
		category=category.name,
		deliverable_requirements=[{"project_requirement": seed["working"]}],
		deliverable_responsibles=[
			{
				"responsibility": responsibility.name,
				"project_role": role.name,
				"responsible_type": "User",
				"responsible": "Administrator",
			},
			{
				"responsibility": responsibility.name,
				"project_role": role.name,
				"responsible_type": "Contact",
				"responsible": person,
			},
		],
	).insert()
	change = frappe.get_doc(
		doctype="Project Change Request",
		project=project.name,
		title=f"{prefix} change",
		initiator=person,
		status="Draft",
		description="Update the scope of the result",
		change_relations=[
			{
				"type": impact.name,
				"direction": "target",
				"level": "Strong",
				"estimation": "2\u20134 days",
				"link_doctype": "Project Deliverable",
				"link": result.name,
			}
		],
	).insert()
	return dict(seed, title=prefix, result=result.name, change=change.name)


@whitelist_for_tests(methods=["POST"])
def remove_report_fixture(run_id):
	prefix = _prefix(run_id)
	project = frappe.db.get_value("Project", {"project_name": prefix}, "name")
	if not project:
		return
	for doctype, title in (
		("Project Change Request", f"{prefix} change"),
		("Project Deliverable", f"{prefix} result"),
	):
		for name in frappe.get_all(doctype, filters={"project": project, "title": title}, pluck="name"):
			if doctype == "Project Deliverable":
				frappe.db.delete("Project Deliverable Log", {"deliverable": name})
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	remove_fixture(run_id)
	for doctype in (
		"Project Change Relation Type",
		"Project Deliverable Responsibility",
		"Project Deliverable Type",
		"Project Deliverable Category",
		"Project Role",
	):
		if frappe.db.exists(doctype, prefix):
			frappe.delete_doc(doctype, prefix, force=True, delete_permanently=True)
