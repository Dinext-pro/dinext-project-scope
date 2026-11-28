from __future__ import annotations

import json
from collections import defaultdict

import frappe
from dinext_common.workflow_approval.engine import WorkflowDomainRollbackError
from dinext_common.workflow_approval.scenarios.compat import is_authorized_finalization, transition_execution
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from dinext_project_scope import access
from dinext_project_scope import requirements as req
from dinext_project_scope.requirement_graph import content_digest

APPROVAL = "Project Scope Approval"
COVERAGE = "Project Scope Approval Requirement"
REVIEW = "In Review"
APPROVED = "Approved"
REAPPROVAL = "Reapproval Required"
OUTCOMES = {APPROVED: APPROVED, "Rejected": "Rejected", "Draft": "Withdrawn", "Cancelled": "Cancelled"}


def lock_dependencies(doctype: str, name: str) -> list[tuple[str, str]]:
	if doctype not in req.SOURCE_TYPES:
		return []
	locks = [req.GRAPH_LOCK]
	if doctype != req.SPEC_TEMPLATE and (project := frappe.db.get_value(doctype, name, "project")):
		locks.append(("Project", project))
	return locks


def _requirement_entry(doc: Document) -> dict:
	return {
		"creation": str(doc.creation),
		"revision": doc.content_revision or 1,
		"content": req.requirement_content(doc),
	}


def _snapshot(doc: Document, *, check_permission: bool, for_update=False) -> dict:
	if check_permission:
		doc.check_permission("read")
	graph = (
		req.Composition(requirements={doc.name: doc})
		if doc.doctype == req.REQUIREMENT
		else (
			req.specification_graph(
				doc, mode="strict" if check_permission else "internal", for_update=for_update
			)
		)
	)
	requirements = {}
	for name, requirement in graph.requirements.items():
		entry = _requirement_entry(requirement)
		if check_permission:
			for goal in entry["content"]["goals"]:
				access.check_document("Goal", goal)
		requirements[name] = {
			**entry,
			"digest": content_digest(entry),
			"parent": requirement.get(req.PARENT)
			if requirement.get(req.PARENT) in graph.requirements
			else None,
		}
	return {
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"project": doc.get("project") or None,
		"specifications": {
			name: {
				"creation": str(specification.creation),
				"revision": specification.content_revision or 1,
				"content": req.specification_content(specification),
			}
			for name, specification in graph.specifications.items()
		},
		"requirements": requirements,
	}


def _approval_filters(doc: Document) -> dict:
	return {
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"reference_created_at": doc.creation,
	}


def _latest_round(doc: Document, *, decision=None, for_update=False) -> str | None:
	filters = _approval_filters(doc)
	if decision:
		filters["decision"] = decision
	return frappe.db.get_value(APPROVAL, filters, "name", order_by="round_number desc", for_update=for_update)


def _decision_task(doc: Document, *, round_id=None, next_state=None):
	filters = {
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"source_created_at": doc.creation,
		"workflow_state": REVIEW,
	}
	if round_id:
		filters["approval_round_id"] = round_id
	if next_state:
		filters.update(
			round_status="Finalizing", next_state=next_state, status="Completed", approver=frappe.session.user
		)
	return frappe.db.get_value(
		"Workflow Task",
		filters,
		["approval_round_id", "workflow", "workflow_process", "round_manifest", "vote_comment"],
		as_dict=True,
		for_update=True,
		order_by="creation desc",
	)


def _finish(approval: Document, decision: str, *, key: str, reason: str | None = None) -> None:
	if approval.decision == decision and approval.decision_key == key:
		return
	if approval.decision != REVIEW:
		frappe.throw(_("This approval round has already closed."), WorkflowDomainRollbackError)
	approval.update(
		{
			"decision": decision,
			"decision_key": key,
			"decided_by": frappe.session.user,
			"decided_at": now_datetime(),
			"decision_reason": reason,
		}
	)
	approval.save(ignore_permissions=True)


def round_opened(doc: Document, round_id: str) -> None:
	"""Capture a Common review round before any vote or automatic transition applies."""
	if doc.doctype not in req.SOURCE_TYPES or doc.get("workflow_state") != REVIEW:
		return
	if frappe.db.get_value(APPROVAL, {"submission_key": round_id}, "name", for_update=True):
		return
	snapshot = _snapshot(doc, check_permission=True, for_update=True)
	digest = content_digest(snapshot)
	if previous := _latest_round(doc, decision=REVIEW, for_update=True):
		previous = frappe.get_doc(APPROVAL, previous, for_update=True)
		if previous.content_digest != digest:
			# The Common route may rebuild a round, but only a fresh submission may capture changed content.
			return
		_finish(
			previous,
			"Superseded",
			key=f"superseded-{previous.submission_key}",
			reason=_("The workflow review was restarted."),
		)
	task = _decision_task(doc, round_id=round_id)
	if not task:
		frappe.throw(
			_("No review task was created for this requirement composition."), WorkflowDomainRollbackError
		)
	manifest = json.loads(task.round_manifest)
	if not any(
		row["next_state"] == APPROVED and row["eligible_approvers"] for row in manifest["transitions"]
	):
		frappe.throw(_("The review has no eligible approver."), WorkflowDomainRollbackError)
	initiator = manifest.get("entry_context", {}).get("actor") or frappe.session.user
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
			"submitted_by": initiator,
			"submitted_at": now_datetime(),
			"content_digest": digest,
			"snapshot": json.dumps(snapshot, ensure_ascii=False),
			"participants_snapshot": json.dumps(manifest["transitions"], ensure_ascii=False),
			"decision": REVIEW,
		}
	).insert(ignore_permissions=True)


def _verify_review(doc: Document, approval: Document) -> dict:
	snapshot = _review_snapshot(doc)
	if content_digest(snapshot) != approval.content_digest:
		frappe.throw(
			_("The requirement composition changed. Withdraw the review and submit it again."),
			WorkflowDomainRollbackError,
		)
	return snapshot


def _review_snapshot(doc: Document) -> dict:
	try:
		return _snapshot(doc, check_permission=True, for_update=True)
	except frappe.PermissionError:
		frappe.clear_last_message()
		frappe.throw(
			_("You need read access to the full requirement composition."), WorkflowDomainRollbackError
		)


def validate_vote(doc: Document, next_state: str) -> None:
	if next_state == REVIEW and doc.workflow_state != REVIEW:
		_review_snapshot(doc)
	elif doc.workflow_state == REVIEW and next_state in (APPROVED, "Rejected"):
		name = _latest_round(doc, decision=REVIEW, for_update=True)
		if not name:
			frappe.throw(
				_("Submit the requirement composition before recording a decision."),
				WorkflowDomainRollbackError,
			)
		approval = frappe.get_doc(APPROVAL, name, for_update=True)
		if frappe.session.user != "Administrator":
			_check_participant(approval, next_state)
		_verify_review(doc, approval)


def _check_participant(approval: Document, next_state: str, transition_uuid: str | None = None) -> None:
	if not any(
		row["next_state"] == next_state
		and (not transition_uuid or row["transition_uuid"] == transition_uuid)
		and frappe.session.user in row["eligible_approvers"]
		for row in json.loads(approval.participants_snapshot)
	):
		frappe.throw(
			_("This user was not authorized to decide the submitted composition."),
			WorkflowDomainRollbackError,
		)


def _cover_requirements(approval: Document, source: Document, snapshot: dict) -> None:
	for name, entry in snapshot["requirements"].items():
		approval.append(
			"requirements",
			{
				"requirement": name,
				"requirement_created_at": entry["creation"],
				"requirement_content_revision": entry["revision"],
				"requirement_digest": entry["digest"],
			},
		)
		if source.doctype == req.REQUIREMENT and name == source.name:
			if source.status == "New":
				source.status = APPROVED
			continue
		requirement = frappe.get_doc(req.REQUIREMENT, name, for_update=True)
		if requirement.status == "New":
			# The Common task authorizes this specific status write after full-set read checks.
			with req.approving_status(requirement.name):
				requirement.status = APPROVED
				requirement.save(ignore_permissions=True)


def apply_transition(doc: Document) -> None:
	before = doc.get_doc_before_save()
	state = doc.get("workflow_state")
	if not before:
		if state in (REVIEW, APPROVED, "Rejected"):
			frappe.throw(_("Change approval states with the workflow actions."), WorkflowDomainRollbackError)
		return
	if before.get("workflow_state") == state:
		return
	if state not in (REVIEW, APPROVED, "Rejected") and before.workflow_state != REVIEW:
		return
	if not is_authorized_finalization(doc):
		frappe.throw(_("Change approval states with the workflow actions."), WorkflowDomainRollbackError)
	if state == REVIEW:
		_review_snapshot(doc)
		return
	if before.workflow_state != REVIEW or state not in OUTCOMES:
		frappe.throw(
			_("Submit the requirement composition before recording a decision."), WorkflowDomainRollbackError
		)
	decision = OUTCOMES[state]
	task = _decision_task(doc, next_state=state)
	if not task:
		frappe.throw(_("A workflow task must authorize the decision."), WorkflowDomainRollbackError)
	name = frappe.db.get_value(APPROVAL, {"submission_key": task.approval_round_id}, "name", for_update=True)
	if not name and decision in ("Withdrawn", "Cancelled"):
		name = _latest_round(doc, decision=REVIEW, for_update=True)
	if not name:
		frappe.throw(
			_("Submit the requirement composition before recording a decision."), WorkflowDomainRollbackError
		)
	approval = frappe.get_doc(APPROVAL, name, for_update=True)
	if approval.decision_key == task.approval_round_id and approval.decision == decision:
		return
	reason = task.vote_comment
	if decision in (APPROVED, "Rejected"):
		execution = transition_execution(doc)
		if not execution:
			frappe.throw(
				_("This user was not authorized to decide the submitted composition."),
				WorkflowDomainRollbackError,
			)
		_check_participant(approval, state, execution.uuid)
		snapshot = _verify_review(doc, approval)
		if decision == APPROVED:
			_cover_requirements(approval, doc, snapshot)
	else:
		current = _snapshot(doc, check_permission=False, for_update=True)
		if content_digest(current) != approval.content_digest:
			decision = "Superseded"
			reason = reason or _("The requirement composition changed during review.")
	_finish(approval, decision, key=task.approval_round_id, reason=reason)


def _source_digest(doctype: str, name: str) -> str | None:
	if not frappe.db.exists(doctype, name):
		return None
	return content_digest(_snapshot(frappe.get_doc(doctype, name), check_permission=False))


def _is_current(approval, cache: dict) -> bool:
	if approval.decision not in (APPROVED, REVIEW, "Rejected"):
		return False
	source = (approval.reference_doctype, approval.reference_name)
	if source not in cache:
		cache[source] = _source_digest(*source)
	return cache[source] == approval.content_digest


def _state(approval, cache: dict) -> str:
	if approval.decision in (APPROVED, REVIEW, "Rejected"):
		return approval.decision if _is_current(approval, cache) else REAPPROVAL
	return "Draft"


ROUND_FIELDS = [
	"name",
	"reference_doctype",
	"reference_name",
	"reference_created_at",
	"decision",
	"content_digest",
	"round_number",
]


def requirement_states(documents: dict[str, Document]) -> dict[str, str]:
	if not documents:
		return {}
	coverage = frappe.get_all(
		COVERAGE,
		filters={"requirement": ("in", list(documents))},
		fields=[
			"parent",
			"requirement",
			"requirement_created_at",
			"requirement_content_revision",
			"requirement_digest",
		],
	)
	approvals = {}
	if coverage:
		approvals = {
			row.name: row
			for row in frappe.get_all(
				APPROVAL,
				filters={"name": ("in", sorted({row.parent for row in coverage})), "decision": APPROVED},
				fields=ROUND_FIELDS,
			)
		}
	own_rounds = {}
	for row in frappe.get_all(
		APPROVAL,
		filters={"reference_doctype": req.REQUIREMENT, "reference_name": ("in", list(documents))},
		fields=ROUND_FIELDS,
		order_by="round_number desc",
	):
		if str(row.reference_created_at) == str(documents[row.reference_name].creation):
			own_rounds.setdefault(row.reference_name, row)
	by_requirement = defaultdict(list)
	for row in coverage:
		if row.parent in approvals and str(row.requirement_created_at) == str(
			documents[row.requirement].creation
		):
			by_requirement[row.requirement].append(row)
	states = {}
	digests = {}
	for name, doc in documents.items():
		entry = _requirement_entry(doc)
		digest = content_digest(entry)
		linked = by_requirement[name]
		if any(
			row.requirement_content_revision == entry["revision"]
			and row.requirement_digest == digest
			and _is_current(approvals[row.parent], digests)
			for row in linked
		):
			states[name] = APPROVED
		elif own := own_rounds.get(name):
			states[name] = _state(own, digests)
			if linked and states[name] == "Draft":
				states[name] = REAPPROVAL
		else:
			states[name] = REAPPROVAL if linked else "Draft"
	return states


def _visible_snapshot(row: Document, readable) -> dict:
	snapshot = json.loads(row.snapshot)
	doctype = row.reference_doctype
	requirements = {
		name: entry
		for name, entry in snapshot["requirements"].items()
		if _same_document(req.REQUIREMENT, name, entry["creation"]) and readable(req.REQUIREMENT, name)
	}
	specifications = {
		name: entry
		for name, entry in snapshot["specifications"].items()
		if _same_document(doctype, name, entry["creation"]) and readable(doctype, name)
	}
	for entry in requirements.values():
		if entry["parent"] not in requirements:
			entry["parent"] = None
		entry["content"]["goals"] = [goal for goal in entry["content"]["goals"] if readable("Goal", goal)]
		del entry["digest"]
	for entry in specifications.values():
		entry["content"]["items"] = [
			(target_type, name)
			for target_type, name in entry["content"]["items"]
			if name in (requirements if target_type == req.REQUIREMENT else specifications)
		]
	return {"requirements": requirements, "specifications": specifications}


def _same_document(doctype, name, created_at):
	return bool(created_at and str(frappe.db.get_value(doctype, name, "creation")) == str(created_at))


HISTORY_FIELDS = [
	*ROUND_FIELDS,
	"workflow_process",
	"submitted_by",
	"submitted_at",
	"decided_by",
	"decided_at",
	"decision_reason",
	"snapshot",
	"participants_snapshot",
]


def _history_rows(doc: Document, readable) -> list:
	own = frappe.get_all(APPROVAL, filters=_approval_filters(doc), fields=HISTORY_FIELDS)
	if doc.doctype != req.REQUIREMENT:
		return sorted(own, key=lambda row: (row.submitted_at, row.name), reverse=True)
	parents = set(
		frappe.get_all(
			COVERAGE,
			filters={"requirement": doc.name, "requirement_created_at": doc.creation},
			pluck="parent",
		)
	) - {row.name for row in own}
	if parents:
		rows = frappe.get_all(APPROVAL, filters={"name": ("in", sorted(parents))}, fields=HISTORY_FIELDS)
		own.extend(
			row
			for row in rows
			if _same_document(row.reference_doctype, row.reference_name, row.reference_created_at)
			and readable(row.reference_doctype, row.reference_name)
		)
	return sorted(own, key=lambda row: (row.submitted_at, row.name), reverse=True)


@frappe.whitelist(methods=["GET", "POST"])
def approval_history(doctype: str, name: str) -> dict:
	if doctype not in req.SOURCE_TYPES:
		frappe.throw(_("Choose a requirement, a specification or a specification template."))
	doc = access.check_document(doctype, name)
	digests = {}
	visible = {}

	def readable(target_type, target_name):
		key = (target_type, target_name)
		if key not in visible:
			visible[key] = bool(target_name and req.can_read(target_type, target_name))
		return visible[key]

	history = []
	for row in _history_rows(doc, readable):
		process = row.workflow_process if readable("Workflow Process", row.workflow_process) else None
		participants = (
			sorted(
				{
					user
					for transition in json.loads(row.participants_snapshot)
					for user in transition["eligible_approvers"]
					if readable("User", user)
				}
			)
			if process
			else []
		)
		history.append(
			{
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"round_number": row.round_number,
				"decision": row.decision,
				"status": _state(row, digests),
				"submitted_by": row.submitted_by if readable("User", row.submitted_by) else None,
				"submitted_at": row.submitted_at,
				"decided_by": row.decided_by if readable("User", row.decided_by) else None,
				"decided_at": row.decided_at,
				"decision_reason": row.decision_reason,
				"workflow_process": process,
				"participants": participants,
				"snapshot": _visible_snapshot(row, readable),
			}
		)
	status = (
		requirement_states({name: doc})[name]
		if doctype == req.REQUIREMENT
		else (_own_specification_state(doc, history[0]["status"]) if history else "Draft")
	)
	return {"status": status, "rounds": history}


def _own_specification_state(doc: Document, latest_status: str) -> str:
	return "Draft" if doc.get("workflow_state") == "Draft" else latest_status


@frappe.whitelist(methods=["GET", "POST"])
def approval_summary(doctype: str, name: str) -> dict:
	if doctype not in req.SOURCE_TYPES:
		frappe.throw(_("Choose a requirement, a specification or a specification template."))
	doc = access.check_document(doctype, name)
	if doctype == req.REQUIREMENT:
		return {"status": requirement_states({name: doc})[name]}
	digests = {}
	own_round = _latest_round(doc)
	status = (
		_own_specification_state(doc, _state(frappe.get_doc(APPROVAL, own_round), digests))
		if own_round
		else "Draft"
	)
	usage = _specification_usage(doc)
	covered_by = []
	if usage:
		approvals = frappe.get_all(
			APPROVAL,
			filters={"reference_doctype": doctype, "reference_name": ("in", usage), "decision": APPROVED},
			fields=ROUND_FIELDS,
			order_by="round_number desc",
		)
		for row in approvals:
			if row.reference_name not in covered_by and _is_current(row, digests):
				covered_by.append(row.reference_name)
	project = doc.get("project")
	in_project = project and doc.name in req._project_composition(project).specifications
	return {
		"status": status,
		"used_by": usage,
		"covered_by": covered_by,
		"project": project if in_project else None,
	}


def _specification_usage(doc: Document) -> list[str]:
	child = f"{doc.doctype} Item"
	result = []
	seen = {doc.name}
	pending = [doc.name]
	while pending:
		parents = frappe.get_all(
			child,
			filters={
				"parenttype": doc.doctype,
				"parentfield": "items",
				"reference_doctype": doc.doctype,
				"reference_name": ("in", pending),
			},
			pluck="parent",
		)
		pending = []
		for name in sorted(set(parents) - seen):
			if req.can_read(doc.doctype, name):
				pending.append(name)
				result.append(name)
			seen.add(name)
	return result
