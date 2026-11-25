"""Validate and manage scope and assumptions in the canonical Project tables."""

from __future__ import annotations

from datetime import date
from typing import TypedDict

import frappe
from frappe import _
from frappe.utils import now_datetime

from dinext_project_scope.access import (
	check_document,
	check_project,
	lock_project,
	project_participants,
	validate_project_target,
)
from dinext_project_scope.requirements import validate_child_rows
from dinext_project_scope.template_application import apply_once, digest

CONSTRAINT_TEMPLATE = "Project Constraints Template"
SCOPE_TABLE = "project_scopes"
CONSTRAINT_TABLE = "project_constraints"
FINAL_VERIFICATION = {"Confirmed", "Disproved"}
CONSTRAINT_FIELDS = (
	"subject",
	"record_type",
	"category",
	"description",
	"consequences",
	"review_date",
	"responsible_type",
	"responsible",
)
VERIFICATION_FIELDS = ("verification_status", "verification_note", "verification_evidence")


class ConstraintAssignmentFormInput(TypedDict):
	doctype: str
	name: str


class ConstraintPreviewRow(TypedDict):
	subject: str
	record_type: str
	category: str | None
	description: str | None
	consequences: str | None
	review_date: date | str | None
	responsible_type: str | None
	responsible: str | None
	source: str
	needs_assignment: bool


class ConstraintsTemplatePreviewResponse(TypedDict):
	rows: list[ConstraintPreviewRow]
	digest: str
	participants: list[tuple[str, str]]


class ConstraintsTemplateResponse(TypedDict):
	constraints: dict[str, str]


ConstraintAssignments = dict[str, ConstraintAssignmentFormInput] | str | None


def _value_changed(row, prior, keys):
	return not prior or any(row.get(key) != prior.get(key) for key in keys)


def validate_constraint(row, project=None, prior=None):
	row.record_type = row.get("record_type") or "Constraint"
	row.status = row.get("status") or ("New" if project else "Template")
	if not project and row.status != "Template":
		raise frappe.ValidationError(_("A constraints template contains template rows only."))
	if project and row.status == "Template":
		raise frappe.ValidationError(_("Apply a constraints template to create a project record."))
	if row.get("category") and _value_changed(row, prior, ("category",)):
		category = check_document("Project Deliverable Category", row.category)
		if not category.enabled:
			raise frappe.ValidationError(_("The selected category is disabled."))
	if project and row.get("responsible") and _value_changed(row, prior, ("responsible", "responsible_type")):
		registrations = project_participants(project, row.responsible_type)
		if not any(participant["name"] == row.responsible for participant in registrations):
			raise frappe.ValidationError(_("Select a responsible person from this project."))
		check_document(row.responsible_type, row.responsible)
	if project and row.record_type == "Assumption":
		row.verification_status = row.get("verification_status") or "Pending"
		changed = _value_changed(row, prior, VERIFICATION_FIELDS)
		if row.verification_status in FINAL_VERIFICATION:
			if not (str(row.get("verification_note") or "").strip() or row.get("verification_evidence")):
				raise frappe.ValidationError(
					_("Describe the evidence or select an attachment to verify an assumption.")
				)
			if changed and row.get("verification_evidence"):
				file_doc = check_document("File", row.verification_evidence)
				if file_doc.attached_to_doctype != "Project" or file_doc.attached_to_name != project:
					raise frappe.ValidationError(_("Attach the verification evidence to this project first."))
			row.verified_by = frappe.session.user if changed else prior.verified_by
			row.verified_at = now_datetime() if changed else prior.verified_at
			return
	else:
		row.verification_status = None
		row.verification_note = None
		row.verification_evidence = None
	row.verified_at = None
	row.verified_by = None


def _validate_scope_row(row, prior=None):
	if not _value_changed(row, prior, ("scope_type", "object_ref", "linked_doctype")):
		return
	kind = check_document("Project Scope Type", row.scope_type)
	if not kind.enabled and _value_changed(row, prior, ("scope_type",)):
		raise frappe.ValidationError(_("The selected scope type is disabled."))
	row.linked_doctype = kind.object_doctype or None
	if row.object_ref and not row.linked_doctype:
		raise frappe.ValidationError(_("The selected scope type has no target document type."))
	if row.linked_doctype and not row.object_ref:
		raise frappe.ValidationError(_("Select a related document for this scope type."))
	if row.object_ref:
		check_document(row.linked_doctype, row.object_ref)


def validate_project(doc, method=None):
	"""Apply scope rules to Desk, REST and Import saves of the owning Project."""
	previous = doc.get_doc_before_save()
	validate_child_rows(doc, SCOPE_TABLE, previous)
	validate_child_rows(doc, CONSTRAINT_TABLE, previous)
	old_scope = {row.name: row for row in previous.get(SCOPE_TABLE) or []} if previous else {}
	old_constraints = {row.name: row for row in previous.get(CONSTRAINT_TABLE) or []} if previous else {}
	for row in doc.get(SCOPE_TABLE) or []:
		_validate_scope_row(row, old_scope.get(row.name))
	for row in doc.get(CONSTRAINT_TABLE) or []:
		validate_constraint(row, doc.name, old_constraints.get(row.name))
	if previous:
		for field, doctype, backlink, target in (
			(SCOPE_TABLE, "Deliverable Scope", "project_scope", "Project Scope"),
			(CONSTRAINT_TABLE, "Deliverable Constraint", "project_constraint", "Project Constraint"),
		):
			removed = {r.name for r in previous.get(field) or []} - {r.name for r in doc.get(field) or []}
			for name in removed:
				if (
					frappe.db.exists(doctype, {backlink: name})
					or frappe.db.exists("Change Relation", {"link_doctype": target, "link": name})
					or frappe.db.exists(
						"Project Change Request Implementation Item",
						{"reference_doctype": target, "reference_name": name},
					)
				):
					raise frappe.ValidationError(
						_("Remove references to the project row before deleting it.")
					)


@frappe.whitelist()
def project_change_rows(project):
	check_project(project)
	return frappe.get_list(
		"Project Change Request",
		filters={"project": project},
		fields=["name", "title", "status", "initiator", "implementation_responsible"],
		order_by="creation desc",
		limit_page_length=0,
	)


def _constraint_preview(project: str, template: str, assignments: ConstraintAssignments = None) -> ConstraintsTemplatePreviewResponse:
	check_project(project, "write")
	source = check_document(CONSTRAINT_TEMPLATE, template)
	if source.docstatus == 2:
		raise frappe.ValidationError(_("The selected template is cancelled."))
	people = {(person["doctype"], person["name"]) for person in project_participants(project)}
	assignments = frappe.parse_json(assignments) if assignments else {}
	if not isinstance(assignments, dict):
		raise frappe.ValidationError(_("Template assignments must be a mapping."))
	rows = []
	for row in source.project_constraints or []:
		values = {field: row.get(field) for field in CONSTRAINT_FIELDS}
		selected = assignments.get(row.name)
		if selected is not None:
			if (
				not isinstance(selected, dict)
				or (selected.get("doctype"), selected.get("name")) not in people
			):
				raise frappe.ValidationError(_("Select a responsible person from this project."))
			values.update(responsible_type=selected["doctype"], responsible=selected["name"])
		needs_assignment = (
			bool(values["responsible"]) and (values["responsible_type"], values["responsible"]) not in people
		)
		if needs_assignment:
			values["responsible"] = None
		rows.append(dict(values, source=row.name, needs_assignment=needs_assignment))
	return {"rows": rows, "digest": digest((str(source.modified), rows)), "participants": sorted(people)}


@frappe.whitelist()
def preview_constraints_template(
	project: str, template: str, assignments: ConstraintAssignments = None,
) -> ConstraintsTemplatePreviewResponse:
	"""Preview copied constraints and resolve assignments in the target project."""
	return _constraint_preview(project, template, assignments)


@frappe.whitelist(methods=["POST"])
def apply_constraints_template(
	project: str, template: str, request_key: str, preview_digest: str,
	assignments: ConstraintAssignments = None,
) -> ConstraintsTemplateResponse:
	"""Create the reviewed constraints once and return their new row IDs."""
	check_project(project, "write")

	def create() -> ConstraintsTemplateResponse:
		preview = _constraint_preview(project, template, assignments)
		if preview["digest"] != preview_digest:
			raise frappe.ValidationError(
				_("The template or the project assignments changed. Review the preview again.")
			)
		if any(row["needs_assignment"] for row in preview["rows"]):
			raise frappe.ValidationError(_("Select replacements for the template assignments."))
		project_doc = frappe.get_doc("Project", project)
		created = []
		for row in preview["rows"]:
			values = {field: row[field] for field in CONSTRAINT_FIELDS}
			created.append(project_doc.append(CONSTRAINT_TABLE, dict(values, status="New")))
		project_doc.save()
		return {
			"constraints": {
				row["source"]: new.name for row, new in zip(preview["rows"], created, strict=True)
			}
		}

	return apply_once(
		project,
		CONSTRAINT_TEMPLATE,
		template,
		request_key,
		{"digest": preview_digest, "assignments": (frappe.parse_json(assignments) if assignments else {})},
		create,
	)


@frappe.whitelist(methods=["POST"])
def create_project_requirement(project, title, category, author, responsible=None):
	check_project(project, "write")
	requirement = frappe.get_doc(
		doctype="Project Requirement",
		project=project,
		requirement_title=title,
		kind=category,
		author=author,
		responsible=responsible,
		priority="Medium",
		requirement_importance="Must Have",
		status="New",
	).insert()
	project_doc = frappe.get_doc("Project", project, for_update=True)
	project_doc.append("custom_project_requirements", {"project_requirement": requirement.name})
	project_doc.save()
	return requirement.name
