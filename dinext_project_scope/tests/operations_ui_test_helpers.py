"""Isolated data for Desk tests that perform operations as project participants."""

from secrets import token_urlsafe

import frappe
from frappe.share import add as share
from frappe.tests.ui_test_helpers import whitelist_for_tests
from frappe.utils import add_days, today

from dinext_project_scope.deliverable_structure import from_type
from dinext_project_scope.tests.project_fixture import make_project, project_user_roles
from dinext_project_scope.tests.requirement_ui_test_helpers import _prefix


def _identity(run_id):
	_prefix(run_id)
	return f"Cypress operations {run_id}", f"CYPRESS-SCOPE-OPS-{run_id}"


@whitelist_for_tests(methods=["POST"])
def create_fixture(run_id: str) -> dict:
	label, project_name = _identity(run_id)
	password = f"Qa9!{token_urlsafe(18)}"
	actors = {}
	for role in ("author", "reviewer", "observer"):
		email = f"scope-ops-{run_id}-{role}@example.test"
		actors[role] = frappe.get_doc(
			doctype="User",
			first_name=f"{label} {role}",
			email=email,
			new_password=password,
			send_welcome_email=0,
			user_type="System User",
			language="en",
			roles=project_user_roles(),
		).insert().name

	project = make_project(label, project_name)
	other = make_project(f"{label} restricted", f"{project_name}-RESTRICTED", project.project_type)
	manager_role = frappe.db.get_single_value("Project Scope Settings", "project_manager_role")
	manager_role = manager_role or "Project Manager"
	if not frappe.db.exists("Project Role", manager_role):
		frappe.get_doc(doctype="Project Role", role_name=manager_role, enabled=1).insert(
			set_name=manager_role
		)
	role = frappe.get_doc(doctype="Project Role", role_name=label, enabled=1).insert(set_name=label)
	contact = frappe.get_doc(doctype="Contact", first_name=f"{label} author").insert()
	for user, project_role in ((actors["author"], role.name), (actors["reviewer"], manager_role)):
		project.append("users", {"user": user, "welcome_email_sent": 1})
		project.append(
			"custom_ts_details",
			{"pt_role": project_role, "pt_participant_type": "User", "pt_participant": user},
		)
	project.append("custom_contact_list", {"contact": contact.name, "project_role": role.name})
	project.is_active = "Yes"
	project.save()
	other.append("users", {"user": actors["observer"], "welcome_email_sent": 1})
	other.is_active = "Yes"
	other.save()

	category = frappe.get_doc(doctype="Project Deliverable Category", enabled=1).insert(set_name=label)
	responsibility = frappe.get_doc(
		doctype="Project Deliverable Responsibility", enabled=1, responsibility=f"R-{run_id}"
	).insert(set_name=label)
	task_type = frappe.get_doc(doctype="Task Type", name=label).insert(set_name=label)
	work_type = frappe.get_doc(
		doctype="Project Deliverable Type",
		enabled=1,
		elements=[
			{
				"element_key": key,
				"element_name": title,
				"element_type": "Task",
				"filter_doctype": "Task Type",
				"filter_type": task_type.name,
				"is_optional": optional,
			}
			for key, title, optional in (("main", "Main work", 0), ("optional", "Optional work", 1))
		],
	).insert(set_name=f"{label} work")
	parent_type = frappe.get_doc(
		doctype="Project Deliverable Type",
		enabled=1,
		elements=[
			{"element_key": "baseline", "element_name": "Baseline work", "element_type": "Task"},
			{
				"element_key": "child",
				"element_name": "Nested work",
				"element_type": "Project Deliverable",
				"filter_doctype": "Project Deliverable Type",
				"filter_type": work_type.name,
			},
		],
	).insert(set_name=f"{label} parent")

	def task(title, *, planned_end, expected_end, status="Open", progress=0, typed=True, target=project):
		return frappe.get_doc(
			doctype="Task",
			subject=f"{label} {title}",
			project=target.name,
			type=task_type.name if typed else None,
			status=status,
			progress=progress,
			custom_planned_start_date="2026-11-01",
			custom_planned_end_date=planned_end,
			exp_end_date=expected_end,
			completed_on=add_days(today(), -2) if status == "Completed" else None,
		).insert().name

	def result(kind, title, linked, assignments=(), target=project):
		return frappe.get_doc(
			doctype="Project Deliverable",
			project=target.name,
			title=f"{label} {title}",
			deliverable_type=kind.name,
			category=category.name,
			table_xuct=[dict(slot, element=linked.get(slot["source_element_key"])) for slot in from_type(kind.name)],
			deliverable_responsibles=list(assignments),
		).insert().name

	baseline = task(
		"baseline", planned_end="2026-11-08", expected_end="2026-11-10", status="Completed", progress=100
	)
	partial = task("partial", planned_end="2026-11-09", expected_end="2026-11-14", progress=20)
	cancelled = task("cancelled", planned_end="2026-11-06", expected_end="2026-11-09", status="Cancelled")
	wrong_type = task("wrong type", planned_end="2026-11-10", expected_end="2026-11-12", typed=False)
	foreign_task = task("restricted work", planned_end="2026-11-10", expected_end="2026-11-12", target=other)
	foreign_result = result(work_type, "restricted result", {"main": foreign_task}, target=other)
	leaf = result(work_type, "nested result", {"main": partial})
	parent = result(parent_type, "existing parent", {"baseline": baseline, "child": leaf})
	acceptance = result(
		work_type,
		"acceptance result",
		{"main": baseline, "optional": cancelled},
		[
			dict(
				responsibility=name,
				project_role=role.name,
				responsible_type="User",
				responsible=actors["author"],
			)
			for name in frappe.get_all(
				"Project Deliverable Responsibility", filters={"enabled": 1, "required": 1}, pluck="name"
			)
		],
	)
	constraint_template = frappe.get_doc(
		doctype="Project Constraints Template",
		template_name=f"{label} constraints",
		project_constraints=[
			dict(subject=f"{label} {title}", category=category.name, record_type=kind, status="Template")
			for kind, title in (("Constraint", "capacity limit"), ("Assumption", "availability"))
		],
	).insert().name
	result_template = frappe.get_doc(
		doctype="Project Deliverables Template",
		template_name=f"{label} results",
		deliverables=[
			dict(item_key=key, title=f"{label} template {key}", deliverable_type=kind.name, category=category.name)
			for key, kind in (("parent", parent_type), ("nested", work_type))
		],
		elements=[dict(owner_item_key="parent", source_element_key="child", nested_item_key="nested")],
	).insert(set_name=f"{label} results").name
	impact = frappe.get_doc(
		doctype="Project Change Relation Type",
		enabled=1,
		link_doctype="Task",
		uom="Day",
		reqd_estimation=1,
		reqd_explanation=1,
		reqd_link=1,
	).insert(set_name=label)
	for actor, user in actors.items():
		accessible = other if actor == "observer" else project
		frappe.get_doc(
			doctype="User Permission",
			user=user,
			allow="Project",
			for_value=accessible.name,
			apply_to_all_doctypes=1,
		).insert()
		share("Project", accessible.name, user=user, read=1, write=1)
		if actor == "observer":
			continue
		share("Contact", contact.name, user=user, read=1)
		share("Task Type", task_type.name, user=user, read=1)
		for project_role in (role.name, manager_role):
			share("Project Role", project_role, user=user, read=1)
		for participant in ("author", "reviewer"):
			share("User", actors[participant], user=user, read=1)
		for name in (baseline, partial, cancelled, wrong_type):
			share("Task", name, user=user, write=1)

	return dict(
		label=label,
		project=project.name,
		password=password,
		actors=actors,
		role=role.name,
		contact=contact.name,
		category=category.name,
		responsibility=responsibility.name,
		work_type=work_type.name,
		parent_type=parent_type.name,
		baseline=baseline,
		partial=partial,
		wrong_type=wrong_type,
		foreign_task=foreign_task,
		foreign_result=foreign_result,
		leaf=leaf,
		parent=parent,
		acceptance=acceptance,
		finished_on=add_days(today(), -2),
		constraint_template=constraint_template,
		result_template=result_template,
		impact=impact.name,
	)


@whitelist_for_tests(methods=["POST"])
def remove_fixture(run_id: str) -> None:
	label, project = _identity(run_id)
	projects = [project, f"{project}-RESTRICTED"]
	users = frappe.get_all("User", filters={"name": ("like", f"scope-ops-{run_id}-%@example.test")}, pluck="name")
	for doctype in ("Project Change Request", "Project Deliverable", "Task"):
		rows = frappe.get_all(doctype, filters={"project": ("in", projects)}, fields=["name", "docstatus"])
		for row in rows:
			frappe.db.delete("Project Scope Approval", {"reference_doctype": doctype, "reference_name": row.name})
			if doctype == "Project Deliverable":
				frappe.db.delete("Project Deliverable Log", {"deliverable": row.name})
			if row.docstatus == 1:
				frappe.db.set_value(doctype, row.name, "docstatus", 0, update_modified=False)
			frappe.delete_doc(doctype, row.name, force=True, delete_permanently=True)
	for user in users:
		for permission in frappe.get_all("User Permission", filters={"user": user}, pluck="name"):
			frappe.delete_doc("User Permission", permission, delete_permanently=True)
	frappe.db.delete("Project Scope Template Application", {"project": ("in", projects)})
	for name in projects:
		frappe.delete_doc("Project", name, force=True, delete_permanently=True)
	for doctype, field, match in (
		("Project Constraints Template", "template_name", f"{label} constraints"),
		("Project Deliverables Template", "template_name", f"{label} results"),
		("Project Deliverable Type", "name", ("in", [f"{label} parent", f"{label} work"])),
		("Project Deliverable Category", "name", label),
		("Project Deliverable Responsibility", "name", label),
		("Project Change Relation Type", "name", label),
		("Task Type", "name", label),
		("Project Role", "name", label),
		("Project Type", "project_type", label),
		("Contact", "first_name", f"{label} author"),
	):
		for name in frappe.get_all(doctype, filters={field: match}, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	for user in users:
		frappe.delete_doc("User", user, force=True, delete_permanently=True)
