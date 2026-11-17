"""Seed project-specific routes through the existing Dinext Workflow API."""

import frappe

EDIT_ROLE = "Projects User"
ACTORS = {
	"manager": "doc.approval_approver == frappe.session.user",
	"acceptance": "doc.acceptance_approver == frappe.session.user",
	"implementation": "doc.implementation_responsible == frappe.session.user",
	"author": "doc.owner == frappe.session.user",
	"responsible": "doc.responsible == frappe.session.user",
}


def transition(state, action, target, *, condition="", comment=False, reset=False):
	return dict(
		state=state,
		action=action,
		next_state=target,
		allowed="All",
		condition=condition,
		allow_self_approval=1,
		custom_parallel_approval_policy="Any",
		custom_comment_is_required=int(comment),
		custom_reset_on_change=int(reset),
		custom_auto_complete_unchanged=0,
		send_email_to_creator=0,
	)


def state(name, docstatus=0, update_status=False):
	return dict(
		state=name,
		doc_status=docstatus,
		allow_edit=EDIT_ROLE,
		**(dict(update_field="status", update_value=name) if update_status else {}),
	)


def approval_route(doctype):
	return (
		doctype,
		[state(name) for name in ("Draft", "In Review", "Approved", "Rejected")],
		[
			transition("Draft", "Submit for Review", "In Review", condition=ACTORS["author"]),
			transition("In Review", "Approve", "Approved", condition=ACTORS["responsible"]),
			transition("In Review", "Reject", "Rejected", condition=ACTORS["responsible"], comment=True),
			transition("In Review", "Withdraw Review", "Draft", condition=ACTORS["author"], comment=True),
			transition("Approved", "Submit for Review", "In Review", condition=ACTORS["author"]),
			transition("Rejected", "Return to Draft", "Draft", condition=ACTORS["author"]),
		],
	)


def default_routes():
	for doctype in (
		"Project Requirement",
		"Project Requirement Specification",
		"Project Requirement Specification Template",
	):
		yield approval_route(doctype)
	yield (
		"Project Change Request",
		[
			state(name, status, True)
			for name, status in (
				("Draft", 0),
				("In Review", 0),
				("Approved", 1),
				("Rejected", 0),
				("Implemented", 1),
				("Cancelled", 2),
			)
		],
		[
			transition("Draft", "Submit for Review", "In Review", condition=ACTORS["author"]),
			transition("In Review", "Approve", "Approved", condition=ACTORS["manager"]),
			transition("In Review", "Reject", "Rejected", condition=ACTORS["manager"], comment=True),
			transition("In Review", "Withdraw Review", "Draft", condition=ACTORS["author"], comment=True),
			transition("Rejected", "Return to Draft", "Draft", condition=ACTORS["author"]),
			transition("Approved", "Mark Implemented", "Implemented", condition=ACTORS["implementation"]),
			transition("Approved", "Cancel", "Cancelled", condition=ACTORS["manager"], comment=True),
			transition("Implemented", "Cancel", "Cancelled", condition=ACTORS["manager"], comment=True),
		],
	)
	yield (
		"Project Deliverable",
		[
			state(name, 0, True)
			for name in (
				"Not Started",
				"In Progress",
				"Acceptance",
				"Completed",
				"Cancelled",
				"Template",
			)
		],
		[
			transition("Not Started", "Start Work", "In Progress"),
			transition("Not Started", "Request Acceptance", "Acceptance"),
			transition("Not Started", "Cancel", "Cancelled", comment=True),
			transition("In Progress", "Request Acceptance", "Acceptance"),
			transition("In Progress", "Cancel", "Cancelled", comment=True),
			transition(
				"Acceptance", "Accept Deliverable", "Completed", condition=ACTORS["acceptance"], reset=True
			),
			transition(
				"Acceptance",
				"Return to Work",
				"In Progress",
				condition=ACTORS["acceptance"],
				comment=True,
				reset=True,
			),
			transition(
				"Acceptance", "Cancel", "Cancelled", condition=ACTORS["acceptance"], comment=True, reset=True
			),
			transition(
				"Completed",
				"Reconfirm Acceptance",
				"Completed",
				condition="doc.requires_recheck and " + ACTORS["acceptance"],
				comment=True,
				reset=True,
			),
			transition(
				"Completed",
				"Return to Acceptance",
				"Acceptance",
				condition="doc.requires_recheck and " + ACTORS["acceptance"],
				comment=True,
				reset=True,
			),
		],
	)


def ensure_default_workflows():
	if not frappe.db.exists("DocType", "Workflow Process"):
		return
	for doctype, states, transitions in default_routes():
		if not frappe.db.exists("DocType", doctype) or frappe.db.exists(
			"Workflow", {"document_type": doctype}
		):
			continue
		for row in states:
			if not frappe.db.exists("Workflow State", row["state"]):
				frappe.get_doc(doctype="Workflow State", workflow_state_name=row["state"]).insert(
					ignore_permissions=True
				)
		for row in transitions:
			if not frappe.db.exists("Workflow Action Master", row["action"]):
				frappe.get_doc(doctype="Workflow Action Master", workflow_action_name=row["action"]).insert(
					ignore_permissions=True
				)
		frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": f"Dinext {doctype}",
				"document_type": doctype,
				"is_active": 1,
				"override_status": 0,
				"workflow_state_field": "workflow_state",
				"custom_selection_order": 1,
				"custom_activation_condition": 'doc.status not in ("Template", "Cancelled")'
				if doctype == "Project Deliverable"
				else None,
				"states": states,
				"transitions": transitions,
			}
		).insert(ignore_permissions=True)
