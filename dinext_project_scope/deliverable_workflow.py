"""Subject validation and decision capture for the common Workflow engine."""

from contextlib import contextmanager

import frappe
from dinext_common.workflow_approval import engine, lifecycle
from dinext_common.workflow_approval.scenarios import service
from frappe import _
from frappe.model.workflow import get_workflow_name
from frappe.utils import cstr, escape_html, now_datetime

from dinext_project_scope import approvers
from dinext_project_scope.deliverable_calculations import DELIVERABLE, work_blockers
from dinext_project_scope.deliverable_responsibility import (
	configured_roles,
	current_members,
	missing_responsibilities,
)

DEFAULT_WORKFLOW = "Dinext Project Deliverable"
COMPLETED = "Completed"
ACCEPTANCE = "Acceptance"
STATE_FLAGS = "project_deliverable_workflow_vote"
WORKING_STATUSES = {"Not Started", "In Progress", ACCEPTANCE, COMPLETED, "Cancelled"}


def workflow_lock_dependencies(doctype, name):
	if doctype == DELIVERABLE:
		project = frappe.db.get_value(doctype, name, "project")
		if project:
			return [("Project", project)]
	return []


@contextmanager
def workflow_vote_context():
	previous = frappe.flags.get(STATE_FLAGS)
	frappe.flags[STATE_FLAGS] = None
	try:
		yield
	finally:
		frappe.flags[STATE_FLAGS] = previous


def capture_workflow_vote(task, source, transition):
	if source.doctype == DELIVERABLE:
		frappe.flags[STATE_FLAGS] = {
			"deliverable": source.name,
			"workflow": task.workflow,
			"next_state": transition.get("next_state"),
			"task": task.name,
			"process": task.get("workflow_process"),
			"note": task.get("vote_comment"),
		}


def _workflow(doc):
	if service.is_ready():
		context = service.workflow_context(doc)
		return context[1] if context else None
	name = get_workflow_name(doc.doctype)
	return frappe.get_cached_doc("Workflow", name) if name else None


def _destination_status(workflow, next_state):
	row = next((row for row in workflow.states if row.state == next_state), None)
	if not row:
		return None
	if row.update_field == "status" and row.update_value in WORKING_STATUSES:
		return row.update_value
	return next_state if next_state in WORKING_STATUSES else None


def _manager_error(error):
	frappe.throw(
		_("Assign one active user to the project manager role before submitting for approval."), error
	)


def _validate_manager(doc, workflow, *, decision=False, error=frappe.ValidationError):
	if not workflow or workflow.name != DEFAULT_WORKFLOW:
		return
	manager = approvers.current_manager(doc.project, current=True)
	if not manager:
		_manager_error(error)
	if decision and manager != frappe.session.user:
		frappe.throw(_("Only the current project manager can record this acceptance decision."), error)


def _validate_responsibilities(missing, error=frappe.ValidationError):
	if missing:
		frappe.throw(
			_("Assign participants for required responsibilities ({0}).").format(
				", ".join(frappe.bold(escape_html(name)) for name in missing)
			),
			error,
		)


def _validate_ready(state, missing, error=frappe.ValidationError):
	_validate_responsibilities(missing, error)
	messages = {
		"missing": _("Link the required work for {0}."),
		"incomplete": _("Complete the linked work for {0}."),
		"recheck": _("Confirm the changed result linked to {0} again."),
	}
	blocked = work_blockers(state["work"])
	if blocked:
		frappe.throw(
			"<br>".join(messages[reason].format(frappe.bold(escape_html(name))) for name, reason in blocked),
			error,
		)


def validate_workflow_vote(doc, next_state):
	"""The engine calls this under the project and Workflow Task locks."""
	from dinext_project_scope.deliverables import ProjectWork

	workflow = _workflow(doc)
	target = _destination_status(workflow, next_state) if workflow else None
	if target == COMPLETED:
		_validate_manager(doc, workflow, decision=True)
		state = ProjectWork(doc.project, current=True).evaluate({doc.name})[doc.name]
		missing = missing_responsibilities(
			doc.deliverable_responsibles,
			configured_roles([doc.category])[doc.category],
			members=current_members(doc.project, current=True),
		)
		_validate_ready(state, missing)
	elif target == ACCEPTANCE:
		_validate_manager(doc, workflow, decision=doc.status == COMPLETED)
	elif target == "In Progress":
		_validate_responsibilities(
			missing_responsibilities(
				doc.deliverable_responsibles,
				configured_roles([doc.category])[doc.category],
				members=current_members(doc.project, current=True),
			)
		)


def _decision_details(doc, workflow, next_state):
	vote = frappe.flags.get(STATE_FLAGS)
	if vote and (vote["deliverable"], vote["workflow"], vote["next_state"]) == (
		doc.name,
		workflow.name,
		next_state,
	):
		return vote
	tasks = frappe.get_all(
		"Workflow Task",
		filters={
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"workflow": workflow.name,
			"round_status": "Finalizing",
			"status": "Completed",
			"next_state": next_state,
			"approver": frappe.session.user,
		},
		fields=["name", "workflow_process", "vote_comment"],
		order_by="completed_at desc, name desc",
		limit=1,
	)
	if tasks:
		return {"task": tasks[0].name, "process": tasks[0].workflow_process, "note": tasks[0].vote_comment}
	return {"process": service.get_context(doc).get("process_id") if service.is_ready() else None}


def validate_save(doc, before, state, missing):
	doc.flags.acceptance_decision = None
	doc.acceptance_approver = (
		approvers.current_manager(doc.project, current=True)
		if doc.project and doc.status != "Template"
		else None
	)
	finalizing = bool(getattr(frappe.flags, "in_dinext_workflow_finalization", False))
	_validate_responsibilities(
		missing, engine.WorkflowDomainRollbackError if finalizing else frappe.ValidationError
	)
	if not before:
		if doc.status not in ("Not Started", "Template"):
			frappe.throw(_("Create a working result in Not Started status."))
		return

	workflow = _workflow(doc) if finalizing else None
	next_state = doc.get(workflow.workflow_state_field) if workflow else None
	status = _destination_status(workflow, next_state) if next_state else None
	if not finalizing:
		if doc.status != before.status:
			frappe.throw(_("Use a Workflow action to change the result status."))
		return
	if status:
		doc.status = status
	if doc.status == ACCEPTANCE and before.status != ACCEPTANCE:
		_validate_manager(
			doc, workflow, decision=before.status == COMPLETED, error=engine.WorkflowDomainRollbackError
		)
		if before.status == COMPLETED:
			_record_decision(doc, workflow, next_state, "Reopened")
	elif doc.status == COMPLETED:
		if before.status == COMPLETED and not state["requires_recheck"]:
			return
		_validate_manager(doc, workflow, decision=True, error=engine.WorkflowDomainRollbackError)
		_validate_ready(state, missing, engine.WorkflowDomainRollbackError)
		_record_decision(
			doc, workflow, next_state, "Reconfirmed" if before.status == COMPLETED else "Accepted"
		)


def _record_decision(doc, workflow, next_state, event_type):
	details = _decision_details(doc, workflow, next_state)
	note = cstr(details.get("note")).strip()
	if event_type in ("Reconfirmed", "Reopened") and not note:
		frappe.throw(_("Enter a reason for the acceptance decision."), engine.WorkflowDomainRollbackError)
	doc.flags.acceptance_decision = {
		"event_type": event_type,
		"timestamp": now_datetime(),
		"task": details.get("task"),
		"process": details.get("process"),
		"note": note or None,
	}


def manager_missing(doc):
	workflow = _workflow(doc)
	return workflow and workflow.name == DEFAULT_WORKFLOW and not approvers.current_manager(doc.project)


def reconcile_after_calculation(name):
	if not lifecycle.is_engine_enabled():
		return
	doc = frappe.get_doc(DELIVERABLE, name, for_update=True)
	workflow = _workflow(doc)
	if workflow and workflow.name == DEFAULT_WORKFLOW:
		manager = approvers.current_manager(doc.project, current=True)
		if doc.acceptance_approver != manager:
			frappe.db.set_value(DELIVERABLE, name, "acceptance_approver", manager, update_modified=False)
	if workflow:
		engine.reconcile_source(doc, apply_automatic=False)


def _team_configuration(doc):
	fields = ("pt_role", "pt_participant_type", "pt_participant", "pt_valid_from", "pt_valid_for")
	return {tuple(cstr(row.get(field)) for field in fields) for row in doc.get("custom_ts_details") or []}


def on_project_team_change(doc, method=None):
	if not lifecycle.is_engine_enabled() or getattr(frappe.flags, "in_migrate", False):
		return
	before = doc.get_doc_before_save()
	if not before or _team_configuration(doc) == _team_configuration(before):
		return
	manager = approvers.current_manager(doc.name, current=True)
	result = frappe.qb.DocType(DELIVERABLE)
	rows = (
		frappe.qb.from_(result)
		.select(result.name, result.acceptance_approver)
		.where(
			(result.project == doc.name)
			& (
				(result.status == ACCEPTANCE)
				| ((result.status == COMPLETED) & (result.requires_recheck == 1))
			)
		)
		.for_update()
		.run(as_dict=True)
	)
	for row in rows:
		if row.acceptance_approver != manager:
			reconcile_after_calculation(row.name)
