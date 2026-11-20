"""Create and clean up isolated data for the scope Desk scenarios."""

from secrets import token_urlsafe

import frappe
import frappe.share
from frappe.tests.ui_test_helpers import whitelist_for_tests
from frappe.utils import add_days, getdate

from dinext_project_scope.analytics.data import ACCOUNTABLE_CODE, RESPONSIBILITY
from dinext_project_scope.deliverable_structure import from_type
from dinext_project_scope.requirements import (
	PROJECT_REQUIREMENTS,
	PROJECT_SPECIFICATIONS,
	REQUIREMENT,
	SPECIFICATION,
)
from dinext_project_scope.tests.project_fixture import make_project, project_user_roles
from dinext_project_scope.tests.requirement_ui_test_helpers import _prefix


def _fixture_user(run_id, language):
	return f"scope-reports-{run_id}-{language}@example.test"


def ensure_data_import_role():
	role = "Dinext_Data_Import"
	if frappe.db.exists("Custom DocPerm", {"parent": "Data Import", "role": role}) and not frappe.db.exists(
		"Role", role
	):
		frappe.get_doc(doctype="Role", role_name=role).insert()


def _named(doctype, name, **fields):
	return frappe.get_doc(doctype=doctype, enabled=1, **fields).insert(set_name=name)


def _result(project, prefix, label, category, kind, *, work=None, **fields):
	slots = from_type(kind)
	if work:
		slots[0]["element"] = work
	return frappe.get_doc(
		doctype="Project Deliverable",
		project=project,
		title=f"{prefix} {label}",
		deliverable_type=kind,
		category=category,
		table_xuct=slots,
		**fields,
	).insert()


def _impact(kind, level, result, **fields):
	return {
		"type": kind,
		"direction": "target",
		"level": level,
		"link_doctype": "Project Deliverable",
		"link": result,
		**fields,
	}


@whitelist_for_tests(methods=["POST"])
def create_report_fixture(run_id):
	_prefix(run_id)
	prefix = f"Cypress report {run_id}"
	project = make_project(prefix, f"CYPRESS-SCOPE-REPORT-{run_id}")
	rollout = make_project(f"{prefix} rollout", f"CYPRESS-SCOPE-REPORT-ROLLOUT-{run_id}", project.project_type)
	person = frappe.get_doc(doctype="Contact", first_name=prefix).insert().name
	other_category = f"{prefix} secondary"
	password = f"Qa9!{token_urlsafe(18)}"
	actors = {language: _fixture_user(run_id, language) for language in ("en", "ru")}
	for language, email in actors.items():
		frappe.get_doc(
			doctype="User",
			email=email,
			first_name=prefix,
			language=language,
			user_type="System User",
			send_welcome_email=0,
			new_password=password,
			roles=project_user_roles(),
		).insert()
		frappe.get_doc(
			doctype="User Permission",
			user=email,
			allow="Project",
			for_value=project.name,
			apply_to_all_doctypes=1,
		).insert()
		project.append("users", {"user": email})
	actor = actors["en"]
	hidden = make_project(other_category, f"CYPRESS-SCOPE-REPORT-HIDDEN-{run_id}", project.project_type)
	rollout.append("users", {"user": actor, "welcome_email_sent": 1})
	rollout.save()
	frappe.get_doc(
		doctype="User Permission", user=actor, allow="Project", for_value=rollout.name, apply_to_all_doctypes=1
	).insert()

	_named("Requirement Kind", prefix)
	_named("Requirement Kind", other_category)
	parent = frappe.get_doc(
		doctype=REQUIREMENT,
		project=project.name,
		requirement_title=f"{prefix} working",
		author=person,
		responsible="Administrator",
		kind=prefix,
		requirement_importance="Must Have",
		status="New",
		is_group=1,
	).insert()
	child = frappe.get_doc(
		doctype=REQUIREMENT,
		project=project.name,
		requirement_title=f"{prefix} analyzed child",
		author=person,
		responsible="Administrator",
		kind=other_category,
		priority="High",
		requirement_importance="Must Have",
		status="In Progress",
		parent_project_requirement=parent.name,
	).insert()
	nested = frappe.get_doc(
		doctype=SPECIFICATION,
		project=project.name,
		title=f"{prefix} nested specification",
		responsible="Administrator",
		author=person,
		items=[{"reference_doctype": REQUIREMENT, "reference_name": child.name}],
	).insert()
	ordinary = frappe.get_doc(
		doctype=SPECIFICATION,
		project=project.name,
		title=f"{prefix} specification",
		responsible="Administrator",
		author=person,
		items=[
			{"reference_doctype": REQUIREMENT, "reference_name": parent.name},
			{"reference_doctype": REQUIREMENT, "reference_name": child.name},
			{"reference_doctype": SPECIFICATION, "reference_name": nested.name},
		],
	).insert()
	out_of_scope = frappe.get_doc(
		doctype=REQUIREMENT,
		project=project.name,
		requirement_title=f"{prefix} outside scope",
		author=person,
		responsible="Administrator",
		kind=prefix,
		requirement_importance="Must Have",
		status="New",
	).insert()
	detached = frappe.get_doc(
		doctype=SPECIFICATION,
		project=project.name,
		title=f"{prefix} detached specification",
		author=person,
		responsible="Administrator",
		items=[
			{"reference_doctype": SPECIFICATION, "reference_name": nested.name},
			{"reference_doctype": REQUIREMENT, "reference_name": out_of_scope.name},
		],
	).insert()
	hidden_specification = frappe.get_doc(
		doctype=SPECIFICATION,
		project=hidden.name,
		title=f"{prefix} hidden specification",
		author=person,
		responsible="Administrator",
	).insert()
	unlinked = frappe.get_doc(
		doctype=REQUIREMENT,
		project=project.name,
		requirement_title=f"{prefix} unlinked",
		author=person,
		responsible="Administrator",
		kind=prefix,
		requirement_importance="Must Have",
		status="New",
	).insert()
	for requirement in (unlinked.name, child.name, parent.name):
		project.append(PROJECT_REQUIREMENTS, {"project_requirement": requirement})
	project.append(PROJECT_SPECIFICATIONS, {"specification": ordinary.name})
	role = _named("Project Role", prefix, role_name=prefix).name
	second_role = _named("Project Role", other_category, role_name=other_category).name
	category = _named("Project Deliverable Category", prefix).name
	_named("Project Deliverable Category", other_category)
	kind = _named(
		"Project Deliverable Type",
		prefix,
		elements=[
			{"element_key": "nested", "element_name": "Shared work", "element_type": "Project Deliverable"}
		],
	).name
	leaf_kind = _named(
		"Project Deliverable Type",
		other_category,
		elements=[{"element_key": "task", "element_name": "Work task", "element_type": "Task"}],
	).name
	first_code = _named(
		"Project Deliverable Responsibility", prefix, responsibility=f"{prefix} contributor", color="#2C7C70"
	).name
	second_code = _named(
		"Project Deliverable Responsibility",
		other_category,
		responsibility=f"{prefix} reviewer",
		color="#782CC4",
	).name
	impact = _named("Project Change Relation Type", prefix, link_doctype="Project Deliverable").name
	secondary_impact = _named(
		"Project Change Relation Type", other_category, link_doctype="Project Deliverable"
	).name
	hidden_impact = _named(
		"Project Change Relation Type", f"{prefix} hidden", link_doctype="Project Deliverable"
	).name
	for project_role in (role, second_role):
		project.append(
			"custom_ts_details",
			{"pt_role": project_role, "pt_participant_type": "User", "pt_participant": actor},
		)
	project.append("custom_contact_list", {"contact": person, "project_role": role})
	assumption = project.append(
		"project_constraints",
		{
			"subject": f"{prefix} assumption",
			"category": category,
			"record_type": "Assumption",
			"status": "New",
			"review_date": getdate(),
			"verification_status": "Pending",
		},
	)
	verified_assumption = project.append(
		"project_constraints",
		{
			"subject": f"{prefix} verified supplier capacity",
			"category": category,
			"record_type": "Assumption",
			"status": "New",
			"review_date": add_days(getdate(), 7),
			"verification_status": "Confirmed",
			"verification_note": "Confirmed against the supplier calendar.",
		},
	)
	project.save()

	planned_end = add_days(getdate(), -2)
	work = frappe.get_doc(
		doctype="Task",
		project=project.name,
		subject=f"{prefix} work group",
		status="Working",
		is_group=1,
		progress=60,
		custom_planned_start_date=add_days(getdate(), -10),
		custom_planned_end_date=planned_end,
		exp_end_date=add_days(getdate(), 4),
	).insert()
	task = frappe.get_doc(
		doctype="Task",
		project=project.name,
		subject=f"{prefix} detail task",
		parent_task=work.name,
	).insert()
	shared = _result(project.name, prefix, "shared component", other_category, leaf_kind, work=work.name)
	assigned = [
		{
			"project_role": project_role,
			"responsibility": code,
			"responsible_type": target,
			"responsible": member,
		}
		for project_role, code, target, member in (
			(role, first_code, "User", actor),
			(role, second_code, "User", actor),
			(second_role, first_code, "User", actor),
			(role, first_code, "Contact", person),
		)
	]
	if frappe.db.get_value(RESPONSIBILITY, ACCOUNTABLE_CODE, "enabled"):
		assigned.append(
			{
				"project_role": role,
				"responsibility": ACCOUNTABLE_CODE,
				"responsible_type": "User",
				"responsible": actor,
			}
		)
	result = _result(
		project.name,
		prefix,
		"result",
		category,
		kind,
		work=shared.name,
		deliverable_requirements=[{"project_requirement": name} for name in (parent.name, child.name)],
		deliverable_responsibles=assigned,
	)
	_result(project.name, prefix, "peer", category, kind, work=shared.name)
	work.reload()  # The child Task updates the group's dependency list on insert.
	work.progress = 20
	work.save()
	frappe.share.add("Task", work.name, user=actor, write=1, notify=0)
	foreign = _result(hidden.name, prefix, "hidden deliverable", other_category, leaf_kind)

	change = frappe.get_doc(
		doctype="Project Change Request",
		project=project.name,
		title=f"{prefix} change",
		initiator=person,
		status="Draft",
		description="Update the scope of the result",
		change_relations=[
			_impact(impact, "Strong", result.name, estimation="5 days"),
			_impact(
				impact,
				"Weak",
				shared.name,
				estimation="2\u20134 days",
				explanation="Use the shared component.",
			),
			_impact(impact, "Weak", result.name, explanation="Historical assessment."),
			_impact(secondary_impact, "Moderate", result.name),
		],
	).insert()
	rollout_result = _result(rollout.name, prefix, "rollout deliverable", other_category, leaf_kind)
	frappe.get_doc(
		doctype="Project Change Request",
		project=rollout.name,
		title=f"{prefix} rollout change",
		initiator=person,
		description="Update the rollout schedule",
		change_relations=[_impact(impact, "Moderate", rollout_result.name)],
	).insert()
	frappe.get_doc(
		doctype="Project Change Request",
		project=hidden.name,
		title=f"{prefix} hidden change",
		initiator=person,
		status="Draft",
		description="Test hidden project analytics",
		change_relations=[_impact(hidden_impact, "Strong", foreign.name)],
	).insert()
	# Retain historical data that today's form can no longer save.
	frappe.db.set_value("Change Relation", change.change_relations[2].name, "level", None)
	for name in (secondary_impact, hidden_impact):
		frappe.db.set_value("Project Change Relation Type", name, "enabled", 0)

	return dict(
		title=prefix,
		project=project.name,
		ordinary=ordinary.name,
		detached_specification=detached.name,
		hidden_specification=hidden_specification.name,
		working=parent.name,
		contact=person,
		actor=actor,
		russian_actor=actors["ru"],
		password=password,
		result=result.name,
		shared=shared.name,
		work=work.name,
		task=task.name,
		child_requirement=child.name,
		change=change.name,
		change_date=str(getdate(change.creation)),
		planned_end=str(planned_end),
		later_planned_end=str(add_days(getdate(), 7)),
		assumption=assumption.name,
		assumption_verification_note=verified_assumption.verification_note,
		assumption_review_date=str(verified_assumption.review_date),
		assumption_verified_at=str(verified_assumption.verified_at),
		hidden_project=hidden.name,
		hidden_result=foreign.name,
	)


@whitelist_for_tests(methods=["POST"])
def remove_report_fixture(run_id):
	_prefix(run_id)
	prefix = f"Cypress report {run_id}"
	project = frappe.db.get_value("Project", {"project_name": prefix}, "name")
	hidden = frappe.db.get_value("Project", {"project_name": f"{prefix} secondary"}, "name")
	rollout = frappe.db.get_value("Project", {"project_name": f"{prefix} rollout"}, "name")
	projects = [name for name in (project, hidden, rollout) if name]
	for doctype, order in (
		("Project Change Request", "creation desc"),
		("Project Deliverable", "creation desc"),
		("Task", "lft desc"),
		(SPECIFICATION, "creation desc"),
		(REQUIREMENT, "lft desc"),
	):
		for name in frappe.get_all(
			doctype,
			filters={"project": ["in", projects]},
			pluck="name",
			order_by=order,
		):
			if doctype == "Project Deliverable":
				frappe.db.delete("Project Deliverable Log", {"deliverable": name})
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	actors = [_fixture_user(run_id, language) for language in ("en", "ru")]
	for permission in frappe.get_all("User Permission", filters={"user": ["in", actors]}, pluck="name"):
		frappe.delete_doc("User Permission", permission, delete_permanently=True)
	for name in projects:
		frappe.delete_doc("Project", name, force=True, delete_permanently=True)
	for doctype, name in (("Contact", {"first_name": prefix}), ("Project Type", prefix)):
		if existing := frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, existing, force=True, delete_permanently=True)
	for doctype in (
		"Project Change Relation Type",
		"Project Deliverable Responsibility",
		"Project Deliverable Type",
		"Project Deliverable Category",
		"Project Role",
		"Requirement Kind",
	):
		for name in (prefix, f"{prefix} secondary", f"{prefix} hidden"):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	for actor in actors:
		if frappe.db.exists("User", actor):
			frappe.delete_doc("User", actor, force=True, delete_permanently=True)
