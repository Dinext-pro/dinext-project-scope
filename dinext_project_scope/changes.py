"""Project change evaluation, standard Workflow integration and implementation record."""

import json
from contextlib import contextmanager

import frappe
from dinext_common.workflow_approval.engine import WorkflowDomainRollbackError
from dinext_common.workflow_approval.scenarios.compat import is_authorized_finalization, transition_execution
from frappe import _
from frappe.utils import now_datetime

from dinext_project_scope.access import (
	check_document,
	check_project,
	lock_project,
	project_participants,
	validate_project_target,
)
from dinext_project_scope.approvers import current_manager, require_manager
from dinext_project_scope.requirements import validate_child_rows
from dinext_project_scope.template_application import digest

CHANGE = "Project Change Request"
APPROVAL = "Project Scope Approval"
DEFAULT_WORKFLOW = "Dinext Project Change Request"
REVIEW = "In Review"
APPROVED = "Approved"
IMPLEMENTED = "Implemented"
DRAFT = "Draft"
CANCELLED = "Cancelled"
DOCSTATUS = {DRAFT: 0, REVIEW: 0, "Rejected": 0, APPROVED: 1, IMPLEMENTED: 1, CANCELLED: 2}
OUTCOMES = {APPROVED: APPROVED, "Rejected": "Rejected", DRAFT: "Withdrawn", CANCELLED: "Cancelled"}
RELATION_FIELDS = ("type", "direction", "level", "explanation", "estimation", "uom", "link_doctype", "link")
CONTENT_FIELDS = ("project", "title", "initiator", "description", "reason", "alternative")
IMPLEMENTATION_FIELDS = ("reference_doctype", "reference_name", "change_note")


def change_snapshot(doc):
	return {
		**{key: doc.get(key) for key in CONTENT_FIELDS},
		"change_relations": [
			{key: row.get(key) for key in RELATION_FIELDS} for row in doc.get("change_relations") or []
		],
	}


def validate_relation(row, project, prior=None, *, reviewing=False):
	changed = not prior or any(row.get(key) != prior.get(key) for key in RELATION_FIELDS if key != "uom")
	if not changed and not reviewing:
		row.uom = prior.uom
		return
	kind = check_document("Project Change Relation Type", row.type)
	if not kind.enabled and (not prior or prior.type != row.type):
		raise frappe.ValidationError(_("This impact type is disabled."))
	if row.get("level") not in {"Strong", "Moderate", "Weak"}:
		raise frappe.ValidationError(_("Select an impact level."))
	for required, field, message in (
		("reqd_explanation", "explanation", _("Add an explanation for this impact type.")),
		("reqd_estimation", "estimation", _("Enter an estimate for this impact type.")),
		("reqd_link", "link", _("Select a related document for this impact type.")),
	):
		if kind.get(required) and not str(row.get(field) or "").strip():
			raise frappe.ValidationError(message)
	row.direction = row.get("direction") or "target"
	row.uom = prior.uom if prior and prior.type == row.type else kind.get("uom")
	if row.get("link"):
		target_type = kind.get("link_doctype")
		if not row.get("link_doctype") or (target_type and row.link_doctype != target_type):
			raise frappe.ValidationError(_("Select a related document of the impact type's configured type."))
		validate_project_target(
			project,
			row.link_doctype,
			row.link,
			require_membership=not prior or (row.link_doctype, row.link) != (prior.link_doctype, prior.link),
		)
	else:
		row.link_doctype = kind.get("link_doctype") or None


def _project_users(project):
	return {row["name"] for row in project_participants(project, "User")}


def _workflow_name(doc):
	from dinext_common.workflow_approval.scenarios import service
	from frappe.model.workflow import get_workflow_name

	execution = transition_execution(doc)
	if execution:
		return execution.workflow
	if service.is_ready():
		return service.get_context(doc).get("workflow") or get_workflow_name(doc.doctype)
	return get_workflow_name(doc.doctype)


def _previous_implementation(doc):
	return {
		row.name: {key: row.get(key) for key in IMPLEMENTATION_FIELDS}
		for row in doc.get("implementation_items") or []
	}


def _validate_implementation(doc, previous):
	state = doc.workflow_state
	items = doc.get("implementation_items") or []
	entered = bool(doc.implementation_date or doc.implementation_note or items)
	if entered and state not in {APPROVED, IMPLEMENTED, CANCELLED}:
		raise frappe.ValidationError(_("Record implementation after the change request is approved."))
	old = _previous_implementation(previous) if previous else {}
	targets = set()
	for row in items:
		key = (row.reference_doctype, row.reference_name)
		if key in targets:
			raise frappe.ValidationError(_("List each changed document only once."))
		targets.add(key)
		fields = {name: row.get(name) for name in IMPLEMENTATION_FIELDS}
		if fields != old.get(row.name):
			prior = old.get(row.name) or {}
			validate_project_target(
				doc.project,
				*key,
				require_membership=key != (prior.get("reference_doctype"), prior.get("reference_name")),
			)
	if state != IMPLEMENTED:
		return
	if not (doc.implementation_date and str(doc.implementation_note or "").strip() and items):
		raise frappe.ValidationError(
			_("Enter an implementation date, explanation, and the changed documents.")
		)
	if previous and previous.workflow_state == IMPLEMENTED:
		doc.implemented_by = previous.implemented_by
		doc.implemented_at = previous.implemented_at
		return
	if frappe.session.user != doc.implementation_responsible:
		raise frappe.PermissionError(_("Only the implementation owner can complete this change request."))
	frappe.has_permission(CHANGE, "write", doc=doc, throw=True)
	doc.implemented_by = frappe.session.user
	doc.implemented_at = now_datetime()


def _approval_filters(doc):
	return {"reference_doctype": CHANGE, "reference_name": doc.name}


def _review_task(doc, round_id=None, next_state=None):
	filters = {**_approval_filters(doc), "workflow_state": REVIEW}
	if round_id:
		filters["approval_round_id"] = round_id
	if next_state:
		filters.update(
			next_state=next_state, status="Completed", round_status="Finalizing", approver=frappe.session.user
		)
	return frappe.db.get_value(
		"Workflow Task",
		filters,
		["approval_round_id", "workflow", "workflow_process", "round_manifest", "vote_comment"],
		as_dict=True,
		order_by="creation desc",
		for_update=True,
	)


def _pending_approval(doc, round_id=None):
	filters = {**_approval_filters(doc), "decision": REVIEW}
	if round_id:
		filters["submission_key"] = round_id
	name = frappe.db.get_value(APPROVAL, filters, "name", order_by="round_number desc", for_update=True)
	return frappe.get_doc(APPROVAL, name, for_update=True) if name else None


def _close(approval, decision, task):
	approval.update(
		dict(
			decision=decision,
			decided_by=frappe.session.user,
			decided_at=now_datetime(),
			decision_key=task.approval_round_id,
			decision_reason=task.vote_comment,
		)
	)
	approval.save(ignore_permissions=True)


def round_opened(doc, round_id):
	if doc.doctype != CHANGE or doc.get("workflow_state") != REVIEW:
		return
	if frappe.db.exists(APPROVAL, {"submission_key": round_id}):
		return
	task = _review_task(doc, round_id)
	if not task:
		raise WorkflowDomainRollbackError(_("No review task was created for this change request."))
	manifest = frappe.parse_json(task.round_manifest)
	if not any(
		row["next_state"] == APPROVED and row["eligible_approvers"] for row in manifest["transitions"]
	):
		raise WorkflowDomainRollbackError(_("No eligible approver can approve this change request."))
	if previous := _pending_approval(doc):
		previous.decision = "Superseded"
		previous.decided_by = frappe.session.user
		previous.decided_at = now_datetime()
		previous.save(ignore_permissions=True)
	data = change_snapshot(doc)
	number = frappe.db.get_value(
		APPROVAL, _approval_filters(doc), "round_number", order_by="round_number desc", for_update=True
	)
	frappe.get_doc(
		{
			"doctype": APPROVAL,
			**_approval_filters(doc),
			"round_number": int(number or 0) + 1,
			"workflow": task.workflow,
			"workflow_process": task.workflow_process,
			"submission_key": round_id,
			"submitted_at": now_datetime(),
			"submitted_by": frappe.session.user,
			"content_digest": digest(data),
			"snapshot": json.dumps(data, ensure_ascii=False, default=str),
			"participants_snapshot": task.round_manifest,
			"decision": REVIEW,
		}
	).insert(ignore_permissions=True)


def lock_dependencies(doctype, name):
	if doctype == CHANGE and (project := frappe.db.get_value(CHANGE, name, "project")):
		return [("Project", project)]
	return []


def _validate_review(doc):
	if not str(doc.description or "").strip() or not doc.implementation_responsible:
		raise WorkflowDomainRollbackError(
			_("Enter the description and implementation owner before submitting the change request.")
		)
	if doc.implementation_responsible not in _project_users(doc.project):
		raise WorkflowDomainRollbackError(
			_("Select an active user from the project team as implementation owner.")
		)
	for row in doc.get("change_relations") or []:
		validate_relation(row, doc.project, row, reviewing=True)
	_check_impact_targets(doc)


def _check_impact_targets(doc):
	for row in doc.get("change_relations") or []:
		if row.link:
			validate_project_target(doc.project, row.link_doctype, row.link, require_membership=False)


def _validate_decision_actor(doc):
	if _workflow_name(doc) == DEFAULT_WORKFLOW and frappe.session.user != current_manager(
		doc.project, current=True
	):
		raise WorkflowDomainRollbackError(
			_("Only the current project manager can decide this change request.")
		)
	_check_impact_targets(doc)


def validate_workflow_vote(doc, next_state):
	check_project(doc.project)
	if next_state == REVIEW:
		_validate_review(doc)
		if _workflow_name(doc) == DEFAULT_WORKFLOW:
			require_manager(doc.project)
	if doc.workflow_state == REVIEW and next_state in {APPROVED, "Rejected"}:
		_validate_decision_actor(doc)
		approval = _pending_approval(doc)
		if not approval or approval.content_digest != digest(change_snapshot(doc)):
			raise WorkflowDomainRollbackError(
				_("The submitted estimate changed. Withdraw and submit the change request again.")
			)
	if next_state == IMPLEMENTED:
		if frappe.session.user != doc.implementation_responsible:
			raise WorkflowDomainRollbackError(
				_("Only the implementation owner can complete this change request.")
			)
		doc.check_permission("write")


def validate_change(doc, *, cancelling=False):
	previous = doc.get_doc_before_save()
	if previous and previous.project != doc.project:
		raise frappe.ValidationError(_("The project cannot be changed after the first save."))
	check_project(doc.project)
	lock_project(doc.project)
	if previous and previous.amended_from != doc.amended_from:
		raise frappe.ValidationError(_("The amended request cannot be changed after the first save."))
	if not previous and doc.amended_from:
		source = check_document(CHANGE, doc.amended_from)
		if source.project != doc.project or source.docstatus != 2:
			raise frappe.ValidationError(_("Amend a cancelled change request from this project."))
	state = doc.workflow_state or DRAFT
	if DOCSTATUS.get(state) != doc.docstatus:
		raise WorkflowDomainRollbackError(_("Change status with the workflow actions."))
	validate_child_rows(doc, "change_relations", previous)
	validate_child_rows(doc, "implementation_items", previous)
	old_state = (previous.workflow_state or DRAFT) if previous else DRAFT
	transitioned = state != old_state
	if transitioned and not is_authorized_finalization(doc):
		raise WorkflowDomainRollbackError(_("Change status with the workflow actions."))
	if not transitioned and doc.status != state:
		raise frappe.ValidationError(_("Change status with the workflow actions."))
	doc.status = state
	if not previous or previous.initiator != doc.initiator:
		check_document("Contact", doc.initiator)
	if not previous or previous.implementation_responsible != doc.implementation_responsible:
		if doc.implementation_responsible and doc.implementation_responsible not in _project_users(
			doc.project
		):
			raise frappe.ValidationError(
				_("Select an active user from the project team as implementation owner.")
			)
	if (
		old_state in {REVIEW, APPROVED, IMPLEMENTED, CANCELLED}
		and previous
		and change_snapshot(previous) != change_snapshot(doc)
	):
		raise frappe.ValidationError(_("The submitted text and impact estimates are locked."))
	if old_state in {DRAFT, "Rejected"}:
		old_relations = {row.name: row for row in previous.change_relations or []} if previous else {}
		for row in doc.get("change_relations") or []:
			validate_relation(row, doc.project, old_relations.get(row.name))
	if _workflow_name(doc) == DEFAULT_WORKFLOW:
		doc.approval_approver = (
			require_manager(doc.project)
			if transitioned and state == REVIEW
			else current_manager(doc.project, current=True)
		)
	else:
		doc.approval_approver = None
	if transitioned and state == REVIEW:
		_validate_review(doc)
	if transitioned and old_state == REVIEW and state in OUTCOMES:
		task = _review_task(doc, next_state=state)
		approval = _pending_approval(doc, task.approval_round_id) if task else None
		if not approval:
			raise WorkflowDomainRollbackError(_("Submit the change request before recording a decision."))
		if state in {APPROVED, "Rejected"}:
			_validate_decision_actor(doc)
			if approval.content_digest != digest(change_snapshot(doc)):
				raise WorkflowDomainRollbackError(
					_("The submitted estimate changed. Withdraw and submit the change request again.")
				)
		_close(approval, OUTCOMES[state], task)
	if cancelling and state != CANCELLED:
		raise WorkflowDomainRollbackError(_("Use the workflow cancellation action and enter a reason."))
	_validate_implementation(doc, previous)
	if state not in {IMPLEMENTED, CANCELLED}:
		doc.implemented_by = None
		doc.implemented_at = None
	elif state == CANCELLED and previous:
		doc.implemented_by = previous.implemented_by
		doc.implemented_at = previous.implemented_at


@contextmanager
def workflow_vote_context():
	name = f"scope_change_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(name)
	try:
		yield
	except Exception:
		frappe.db.rollback(save_point=name)
		raise


@frappe.whitelist()
def approval_history(name):
	doc = check_document(CHANGE, name)
	fields = [
		"round_number",
		"workflow_process",
		"submitted_by",
		"submitted_at",
		"decided_by",
		"decided_at",
		"decision",
		"decision_reason",
		"snapshot",
	]
	rounds = frappe.get_all(
		APPROVAL, filters=_approval_filters(doc), fields=fields, order_by="round_number desc"
	)
	for entry in rounds:
		snapshot = frappe.parse_json(entry.snapshot) or {}
		for relation in snapshot.get("change_relations", []):
			if relation.get("link") and not _can_read(relation["link_doctype"], relation["link"]):
				relation["link"] = None
				relation["link_doctype"] = None
		entry.snapshot = snapshot
		for field, target_type in (
			("workflow_process", "Workflow Process"),
			("submitted_by", "User"),
			("decided_by", "User"),
		):
			if entry.get(field) and not _can_read(target_type, entry[field]):
				entry[field] = None
	return rounds


def _can_read(doctype, name):
	try:
		check_document(doctype, name)
		return True
	except (frappe.DoesNotExistError, frappe.PermissionError):
		return False


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def project_user_query(doctype, txt, searchfield, start, page_len, filters):
	if doctype != "User":
		return []
	project = (frappe.parse_json(filters) or {}).get("project")
	if not project:
		return []
	check_project(project)
	return frappe.get_list(
		"User",
		filters={"name": ("in", sorted(_project_users(project)))},
		or_filters={"name": ("like", f"%{txt}%"), "full_name": ("like", f"%{txt}%")},
		fields=["name", "full_name"],
		as_list=True,
		start=start,
		page_length=page_len,
	)
