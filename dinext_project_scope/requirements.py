from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TypedDict

import frappe
from frappe import _
from frappe.model.document import Document

from dinext_project_scope import access
from dinext_project_scope.requirement_graph import (
	REQUIREMENT,
	CompositionError,
	display_order,
	next_revision,
	walk_composition,
)

SPECIFICATION = "Project Requirement Specification"
SPEC_TEMPLATE = "Project Requirement Specification Template"
SOURCE_TYPES = (REQUIREMENT, SPECIFICATION, SPEC_TEMPLATE)
PROJECT_REQUIREMENTS = "custom_project_requirements"
PROJECT_SPECIFICATIONS = "custom_project_requirement_specifications"
PARENT = "parent_project_requirement"
GRAPH_LOCK = ("DocType", "Project Scope Settings")

REQUIREMENT_CONTENT_FIELDS = (
	"requirement_title",
	"description",
	"reason",
	"kind",
	"priority",
	"requirement_importance",
)

_copying_template = ContextVar("copying_requirement_template", default=None)
_approving_requirement = ContextVar("approving_project_requirement", default=None)


class RequirementRow(TypedDict):
	name: str
	title: str
	parent: str | None
	status: str
	kind: str | None
	author: str | None
	responsible: str | None
	priority: str | None
	requirement_importance: str | None
	paths: list[list[str]]
	approval_stale: bool
	approval_status: str


@dataclass
class Composition:
	specifications: dict[str, Document] = field(default_factory=dict)
	requirements: dict[str, Document] = field(default_factory=dict)
	paths: dict[str, list[list[str]]] = field(default_factory=dict)
	complete: bool = True


def lock_graph(*, wait=True) -> None:
	# NestedSet offsets are shared by all projects and by template requirements.
	frappe.db.get_value(*GRAPH_LOCK, "name", for_update=True, wait=wait)


def lock_source(doc: Document, *, wait=True) -> None:
	lock_graph(wait=wait)
	project = (
		doc.get("project")
		if doc.is_new()
		else (frappe.db.get_value(doc.doctype, doc.name, "project") if doc.doctype != SPEC_TEMPLATE else None)
	)
	if project:
		if wait:
			access.lock_project(project)
		else:
			frappe.db.get_value("Project", project, "name", for_update=True, wait=False)


class GraphDocument:
	protected_links: str

	def check_if_latest(self):
		lock_source(self)
		return super().check_if_latest()

	def apply_fieldlevel_read_permissions(self):
		super().apply_fieldlevel_read_permissions()
		rows = self.get(self.protected_links)
		if rows:
			self.__dict__[self.protected_links] = [row for row in rows if self.can_view_link(row)]

	def as_dict(self, *args, **kwargs):
		data = super().as_dict(*args, **kwargs)
		if data.get(self.protected_links) and getattr(frappe.local, "request", None):
			data[self.protected_links] = [
				row for row in data[self.protected_links] if self.can_view_link(row)
			]
		return data

	def can_view_link(self, row):
		if self.doctype == REQUIREMENT:
			return can_read("Goal", row.get("goal"))
		return can_read(row.get("reference_doctype"), row.get("reference_name"))


class RequirementChild(Document):
	link_doctype: str | None = None
	link_field = "reference_name"

	def validate(self):
		frappe.throw(_("Edit this row from its parent document."))

	def on_trash(self):
		frappe.throw(_("Edit this row from its parent document."))

	def has_permission(self, permtype="read", *, debug=False, user=None):
		if permtype in ("read", "select", "export", "print") and not can_read(
			self.link_doctype or self.get("reference_doctype"), self.get(self.link_field), user=user
		):
			return False
		return super().has_permission(permtype, debug=debug, user=user)


@contextmanager
def copying_from(doctype: str, source: str):
	token = _copying_template.set((doctype, source))
	try:
		yield
	finally:
		_copying_template.reset(token)


@contextmanager
def approving_status(requirement: str):
	token = _approving_requirement.set(requirement)
	try:
		yield
	finally:
		_approving_requirement.reset(token)


def _validate_origin(doc: Document, before: Document | None) -> None:
	origin = doc.get("template_source") or None
	if before and (before.get("template_source") or None) != origin:
		frappe.throw(_("The template source cannot be changed."))
	if origin and not before and _copying_template.get() != (doc.doctype, origin):
		frappe.throw(_("The template source is set when the template is applied."))


def can_read(doctype: str, name: str, *, user=None) -> bool:
	if not doctype or not name:
		return False
	try:
		return bool(frappe.has_permission(doctype, "read", doc=name, user=user))
	except (frappe.DoesNotExistError, frappe.PermissionError):
		frappe.clear_last_message()
		return False


def _load_target(doctype: str, name: str, *, for_update=False) -> Document:
	try:
		return frappe.get_doc(doctype, name, for_update=for_update)
	except frappe.DoesNotExistError:
		frappe.clear_last_message()
		frappe.throw(_("A linked requirement or specification is missing."))


def _validate_target(doc: Document, project: str | None, *, template: bool) -> None:
	if doc.get("docstatus") == 2:
		frappe.throw(_("A cancelled document cannot be included in the composition."))
	if doc.doctype == REQUIREMENT and (doc.status == "Template") != template:
		frappe.throw(_("Template and working requirements must be kept in separate compositions."))
	if (doc.get("project") or None) != project:
		frappe.throw(_("Every working requirement and specification must belong to the same project."))


def _check_read(doc: Document, mode: str) -> bool:
	if mode == "internal" or doc.has_permission("read"):
		return True
	if mode == "visible":
		return False
	frappe.throw(_("You need read access to the full requirement composition."), frappe.PermissionError)


def item_edges(doc: Document) -> list[tuple[str, str]]:
	return [(row.reference_doctype, row.reference_name) for row in doc.get("items") or ()]


def _project_edges(doc: Document) -> list[tuple[str, str]]:
	return [
		*((REQUIREMENT, row.project_requirement) for row in doc.get(PROJECT_REQUIREMENTS) or ()),
		*((SPECIFICATION, row.specification) for row in doc.get(PROJECT_SPECIFICATIONS) or ()),
	]


def _resolve_composition(
	specification_type: str,
	project: str | None,
	edges: list[tuple[str, str]],
	*,
	root: Document | None = None,
	mode="strict",
	for_update=False,
) -> Composition:
	graph = Composition()
	if root:
		graph.specifications[root.name] = root

	def resolve(name):
		doc = _load_target(specification_type, name, for_update=for_update)
		_validate_target(doc, project, template=specification_type == SPEC_TEMPLATE)
		if _check_read(doc, mode):
			graph.specifications[name] = doc
			return item_edges(doc)
		graph.complete = False
		return None

	try:
		paths = walk_composition(edges, resolve, specification_type, root=root.name if root else None)
	except CompositionError as error:
		messages = {
			"cycle": _("The specification composition contains a cycle."),
			"duplicate": _("The composition contains the same direct link more than once."),
			"target": _("Choose an allowed type and a document for each composition row."),
		}
		frappe.throw(messages[error.args[0]])

	for name, sources in paths.items():
		doc = _load_target(REQUIREMENT, name, for_update=for_update)
		_validate_target(doc, project, template=specification_type == SPEC_TEMPLATE)
		if _check_read(doc, mode):
			graph.requirements[name] = doc
			graph.paths[name] = sources
		else:
			graph.complete = False
	return graph


def specification_graph(doc: Document, *, mode="strict", for_update=False) -> Composition:
	return _resolve_composition(
		doc.doctype, doc.get("project") or None, item_edges(doc), root=doc, mode=mode, for_update=for_update
	)


def requirement_content(doc: Document) -> dict:
	return {
		**{key: doc.get(key) or "" for key in REQUIREMENT_CONTENT_FIELDS},
		"goals": sorted(row.goal for row in doc.get("goals") or () if row.goal),
	}


def specification_content(doc: Document) -> dict:
	return {"title": doc.title or "", "description": doc.description or "", "items": item_edges(doc)}


def _validate_people(doc: Document, before: Document | None) -> None:
	if doc.author and (not before or before.author != doc.author):
		access.check_document("Contact", doc.author)
	if doc.responsible and (not before or before.responsible != doc.responsible):
		if not frappe.db.get_value("User", doc.responsible, "enabled"):
			frappe.throw(_("The responsible user must be active."))


def validate_child_rows(doc: Document, fieldname: str, before: Document | None) -> None:
	# Frappe updates saved children by name after setting the parent from the incoming document.
	saved = {row.name for row in before.get(fieldname) or ()} if before else set()
	seen = set()
	for index, row in enumerate(doc.get(fieldname) or (), 1):
		if row.name in seen or (before and not row.is_new() and row.name not in saved):
			frappe.throw(_("An existing row must belong to this document."))
		if row.name:
			seen.add(row.name)
		row.idx = index


def _validate_goals(doc: Document, before: Document | None) -> None:
	validate_child_rows(doc, "goals", before)
	goals = [row.goal for row in doc.get("goals") or ()]
	if any(not goal for goal in goals) or len(set(goals)) != len(goals):
		frappe.throw(_("Choose a different goal for each row."))
	previous = {row.goal: row for row in before.get("goals") or ()} if before else {}
	for goal in set(goals) - previous.keys():
		access.check_document("Goal", goal)
	# Desk hides unreadable goals. A save by that reader must not remove those links.
	for goal in previous.keys() - set(goals):
		if not can_read("Goal", goal):
			doc.append("goals", {**previous[goal].as_dict(), "idx": len(doc.goals) + 1})


def _validate_parent(doc: Document, before: Document | None) -> None:
	name = doc.get(PARENT)
	seen = {doc.name}
	changed = not before or before.get(PARENT) != name
	while name:
		if name in seen:
			frappe.throw(_("The requirement hierarchy contains a cycle."))
		seen.add(name)
		parent = _load_target(REQUIREMENT, name, for_update=True)
		_validate_target(parent, doc.get("project") or None, template=doc.status == "Template")
		if changed:
			_check_read(parent, "strict")
			if not parent.is_group:
				frappe.throw(_("Only a group requirement can be selected as a parent."))
		name = parent.get(PARENT)


def _validate_status(doc: Document, before: Document | None) -> None:
	previous = before.status if before else None
	if before and (doc.status == "Template") != (previous == "Template"):
		frappe.throw(_("A saved requirement cannot change between working and template status."))
	if doc.status == previous:
		return
	if doc.status == "Approved" and _approving_requirement.get() != doc.name:
		frappe.throw(_("Approve the requirement through its workflow or a specification."))
	if doc.status == "Done":
		assigned = before.responsible if before else None
		if not assigned:
			frappe.throw(
				_("Assign a responsible user before marking this requirement Done."), frappe.PermissionError
			)
		if (
			assigned != frappe.session.user
			or assigned != doc.responsible
			or not frappe.db.get_value("User", assigned, "enabled")
			or not doc.has_permission("write")
		):
			frappe.throw(
				_("Only the assigned responsible user {0} can mark this requirement Done.").format(assigned),
				frappe.PermissionError,
			)


def validate_requirement(doc: Document) -> None:
	before = doc.get_doc_before_save()
	project = doc.get("project") or None
	if doc.status == "Template" and project:
		frappe.throw(_("A template requirement cannot have a project."))
	if doc.status != "Template" and not project:
		frappe.throw(_("A working requirement needs a project."))
	if before and project != (before.get("project") or None):
		frappe.throw(_("The project of a saved document cannot be changed."))
	if project:
		access.check_project(project)
	_validate_status(doc, before)
	_validate_origin(doc, before)
	_validate_people(doc, before)
	_validate_parent(doc, before)
	_validate_goals(doc, before)
	for key in ("lft", "rgt", "old_parent"):
		doc.set(key, before.get(key) if before else None)
	doc.content_revision = next_revision(
		before.content_revision if before else 0,
		requirement_content(before) if before else None,
		requirement_content(doc),
	)


def validate_specification(doc: Document) -> None:
	before = doc.get_doc_before_save()
	if doc.doctype == SPECIFICATION:
		if not doc.project:
			frappe.throw(_("A working specification needs a project."))
		if before and doc.project != before.project:
			frappe.throw(_("The project of a saved document cannot be changed."))
		access.check_project(doc.project)
		_validate_origin(doc, before)
	elif doc.get("project"):
		frappe.throw(_("A template specification cannot have a project."))
	_validate_people(doc, before)
	validate_child_rows(doc, "items", before)
	if before:
		visible_items = [row for row in before.items if doc.can_view_link(row)]
		if len(visible_items) != len(before.items):
			visible_edges = [(row.reference_doctype, row.reference_name) for row in visible_items]
			if item_edges(doc) == visible_edges:
				doc.set("items", [row.as_dict() for row in before.items])
	if not before or item_edges(doc) != item_edges(before):
		if before:
			specification_graph(before, for_update=True)
		specification_graph(doc, for_update=True)
	doc.content_revision = next_revision(
		before.content_revision if before else 0,
		specification_content(before) if before else None,
		specification_content(doc),
	)


def validate_project(doc: Document, method=None) -> None:
	before = doc.get_doc_before_save()
	for fieldname in (PROJECT_REQUIREMENTS, PROJECT_SPECIFICATIONS):
		validate_child_rows(doc, fieldname, before)
	edges = _project_edges(doc)
	if (before and _project_edges(before) == edges) or not edges:
		return
	access.check_project(doc.name, "write")
	access.lock_project(doc.name)
	_resolve_composition(SPECIFICATION, doc.name, edges, for_update=True)


def _project_composition(project: str, *, check_permission=True, for_update=False) -> Composition:
	if check_permission:
		access.check_project(project)
	doc = frappe.get_doc("Project", project, for_update=for_update)
	return _resolve_composition(
		SPECIFICATION,
		project,
		_project_edges(doc),
		mode="visible" if check_permission else "internal",
		for_update=for_update,
	)


def project_membership(project: str, *, check_permission=True) -> dict[str, list[list[str]]]:
	return _project_composition(
		project, check_permission=check_permission, for_update=not check_permission
	).paths


def _rows(graph: Composition) -> list[RequirementRow]:
	from dinext_project_scope.requirement_approval import requirement_states

	states = requirement_states(graph.requirements)
	parents = {name: doc.get(PARENT) for name, doc in graph.requirements.items()}
	rows = []
	for name, parent in display_order(parents):
		doc = graph.requirements[name]
		state = states[name]
		rows.append(
			{
				"name": name,
				"title": doc.requirement_title,
				"parent": parent,
				"status": doc.status,
				"kind": doc.kind,
				"author": doc.author,
				"responsible": doc.responsible,
				"priority": doc.priority,
				"requirement_importance": doc.requirement_importance,
				"paths": graph.paths[name],
				"approval_stale": state == "Reapproval Required",
				"approval_status": state,
			}
		)
	return rows


@frappe.whitelist(methods=["GET", "POST"])
def project_rows(project: str, specification: str | None = None) -> list[RequirementRow]:
	graph = _project_composition(project)
	if specification:
		doc = _get_specification(SPECIFICATION, specification)
		_validate_target(doc, project, template=False)
		members = specification_graph(doc, mode="visible").requirements
		graph.paths = {name: paths for name, paths in graph.paths.items() if name in members}
		graph.requirements = {name: graph.requirements[name] for name in graph.paths}
	return _rows(graph)


def _get_specification(doctype: str, name: str) -> Document:
	if doctype not in (SPECIFICATION, SPEC_TEMPLATE):
		frappe.throw(_("Choose a specification or a specification template."))
	return access.check_document(doctype, name)


@frappe.whitelist(methods=["GET", "POST"])
def composition_rows(doctype: str, name: str) -> list[RequirementRow]:
	doc = _get_specification(doctype, name)
	return _rows(specification_graph(doc, mode="visible"))


@frappe.whitelist(methods=["GET", "POST"])
def direct_composition(doctype: str, name: str) -> dict:
	doc = _get_specification(doctype, name)
	graph = specification_graph(doc, mode="visible")
	items = []
	for target_type, target_name in item_edges(doc):
		targets = graph.requirements if target_type == REQUIREMENT else graph.specifications
		if target := targets.get(target_name):
			items.append(
				{"reference_doctype": target_type, "reference_name": target_name, "title": target.get_title()}
			)
	return {
		"items": items,
		"can_edit": graph.complete and doc.has_permission("write"),
		"modified": str(doc.modified),
	}


@frappe.whitelist(methods=["POST"])
def replace_composition(doctype: str, name: str, modified: str, items: list | str) -> None:
	if isinstance(items, str):
		items = frappe.parse_json(items)
	if not isinstance(items, list) or any(
		not isinstance(row, dict)
		or not isinstance(row.get("reference_doctype"), str)
		or not isinstance(row.get("reference_name"), str)
		for row in items
	):
		frappe.throw(_("Choose an allowed type and a document for each composition row."))
	doc = _get_specification(doctype, name)
	doc.check_permission("write")
	if str(doc.modified) != modified:
		frappe.throw(
			_("The specification changed. Reopen the composition dialog."), frappe.TimestampMismatchError
		)
	saved = {(row.reference_doctype, row.reference_name): row for row in doc.items}
	doc.set("items", None)
	for row in items:
		key = (row["reference_doctype"], row["reference_name"])
		doc.append("items", saved.get(key) or {"reference_doctype": key[0], "reference_name": key[1]})
	doc.save()


@frappe.whitelist(methods=["GET", "POST"])
def linkable_requirement_branch(project: str, requirement: str) -> list[dict]:
	access.check_project(project, "write")
	access.check_document(REQUIREMENT, requirement)
	root = frappe.get_doc(REQUIREMENT, requirement)
	_validate_target(root, project, template=False)
	return frappe.get_list(
		REQUIREMENT,
		filters={
			"project": project,
			"status": ("!=", "Template"),
			"lft": (">=", root.lft),
			"rgt": ("<=", root.rgt),
		},
		fields=["name", "requirement_title as title"],
		order_by="lft asc",
		limit_page_length=0,
	)


@frappe.whitelist(methods=["GET", "POST"])
def related_documents(name: str) -> dict:
	doc = access.check_document(REQUIREMENT, name)
	goals = [
		{"name": row.goal, "title": frappe.db.get_value("Goal", row.goal, "subject")}
		for row in doc.get("goals") or ()
		if can_read("Goal", row.goal)
	]
	if not doc.project:
		return {"goals": goals, "deliverables": [], "changes": [], "in_scope": False}
	deliverables = frappe.get_all(
		"Deliverable Requirement",
		filters={"parenttype": "Project Deliverable", "project_requirement": name},
		pluck="parent",
	)
	changes = frappe.get_all(
		"Change Relation",
		filters={"parenttype": "Project Change Request", "link_doctype": REQUIREMENT, "link": name},
		pluck="parent",
	)
	if frappe.get_meta("Project Change Request").has_field("implementation_items"):
		changes.extend(
			frappe.get_all(
				"Project Change Request Implementation Item",
				filters={
					"parenttype": "Project Change Request",
					"reference_doctype": REQUIREMENT,
					"reference_name": name,
				},
				pluck="parent",
			)
		)

	def allowed(doctype, ids):
		if not ids or not frappe.has_permission(doctype, "read"):
			return []
		return frappe.get_list(
			doctype,
			filters={"project": doc.project, "name": ("in", sorted(set(ids)))},
			fields=["name", "title", "status"],
			limit_page_length=0,
		)

	return {
		"goals": goals,
		"deliverables": allowed("Project Deliverable", deliverables),
		"changes": allowed("Project Change Request", changes),
		"in_scope": name in _project_composition(doc.project, check_permission=False).paths,
	}


@frappe.whitelist(methods=["GET", "POST"])
def preview_specification_template(
	project: str, template: str, assignments: dict | str | None = None
) -> dict:
	from dinext_project_scope.requirement_template_application import preview

	return preview(project, template, assignments)


@frappe.whitelist(methods=["POST"])
def apply_specification_template(
	project: str, template: str, request_key: str, preview_digest: str, assignments: dict | str | None = None
) -> dict:
	from dinext_project_scope.requirement_template_application import apply

	return apply(project, template, request_key, preview_digest, assignments)
