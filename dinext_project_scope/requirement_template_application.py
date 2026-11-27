from __future__ import annotations

import json
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from dinext_project_scope import access
from dinext_project_scope import requirements as req
from dinext_project_scope.requirement_graph import content_digest, display_order

APPLICATION = "Project Scope Template Application"


@dataclass
class TemplatePlan:
	graph: req.Composition
	root: str
	assignees: dict[str, req.ParticipantLink]
	requirement_order: list[tuple[str, str | None]]
	digest: str


def _parse_assignments(assignments) -> dict[str, str | None]:
	if isinstance(assignments, str):
		try:
			assignments = json.loads(assignments)
		except ValueError:
			frappe.throw(_("Choose a responsible user for each source that needs an assignment."))
	if assignments is None:
		return {}
	if not isinstance(assignments, dict) or any(
		not isinstance(key, str) or (user is not None and not isinstance(user, str))
		for key, user in assignments.items()
	):
		frappe.throw(_("Choose a responsible user for each source that needs an assignment."))
	return {key: user or None for key, user in assignments.items()}


def _project_assignees(project: Document) -> list[str]:
	users = {frappe.session.user, project.owner, *(row.user for row in project.get("users") or ())}
	groups = set()
	today = getdate()
	for row in project.get("custom_ts_details") or ():
		if (row.pt_valid_from and getdate(row.pt_valid_from) > today) or (
			row.pt_valid_for and getdate(row.pt_valid_for) < today
		):
			continue
		if row.pt_participant_type in (None, "", "User"):
			users.add(row.pt_participant)
		elif row.pt_participant_type == "User Group" and row.pt_participant:
			groups.add(row.pt_participant)
	if groups:
		users.update(
			frappe.get_all("User Group Member", filters={"parent": ("in", list(groups))}, pluck="user")
		)
	users.discard(None)
	users.discard("")
	users.discard("Guest")
	return frappe.get_all(
		"User", filters={"enabled": 1, "name": ("in", list(users))}, pluck="name", order_by="name"
	)


def _plan(
	project: Document, template: str, assignments: dict, assignees: list[str], *, for_update=False
) -> TemplatePlan:
	doc = frappe.get_doc(req.SPEC_TEMPLATE, template, for_update=for_update)
	doc.check_permission("read")
	graph = req.specification_graph(doc, for_update=for_update)
	for doctype in (req.SPECIFICATION, req.REQUIREMENT):
		if doctype == req.REQUIREMENT and not graph.requirements:
			continue
		frappe.has_permission(doctype, "create", throw=True)
	nodes = {**graph.specifications, **graph.requirements}
	if assignments.keys() - nodes.keys():
		frappe.throw(_("An assignment refers to a document outside this template."))
	actor = frappe.session.user if frappe.session.user in assignees else None
	contacts = {row["name"] for row in access.project_participants(project.name, "Contact")}
	visible_users = {user for user in assignees if frappe.has_permission("User", "select", doc=user)}
	selected = {}
	blueprint = []
	for name, source in nodes.items():
		if source.doctype == req.REQUIREMENT:
			author_type, author = req.participant_link(source, "author")
			req.check_requirement_participant("author", author_type, author)
			chosen = _requirement_assignee(source, visible_users, contacts, actor, assignments)
			content = req.requirement_content(source)
			for goal in content["goals"]:
				access.check_document("Goal", goal)
			content.update(parent=source.get(req.PARENT), is_group=source.is_group)
		else:
			author_type, author = "Contact", source.author
			access.check_document(author_type, author)
			responsible = source.responsible if source.responsible in assignees else actor
			user = assignments.get(name, responsible)
			if user not in assignees:
				frappe.throw(_("Choose an active user from the target project for this assignment."))
			chosen = ("User", user)
			content = req.specification_content(source)
		selected[name] = chosen
		blueprint.append(
			{
				"doctype": source.doctype,
				"name": name,
				"revision": source.content_revision,
				"creation": str(source.creation),
				"content": content,
				"author": (author_type, author),
				"responsible": chosen,
			}
		)
	order = display_order({name: source.get(req.PARENT) for name, source in graph.requirements.items()})
	digest = content_digest({"project": project.name, "template": template, "nodes": blueprint})
	return TemplatePlan(graph, template, selected, order, digest)


def _requirement_assignee(source, users, contacts, actor, overrides) -> req.ParticipantLink:
	if source.name in overrides:
		user = overrides[source.name]
		if user and user not in users:
			frappe.throw(_("Choose an active user from the target project for this assignment."))
		return "User", user

	doctype, name = req.participant_link(source, "responsible")
	if doctype == "Contact" and name in contacts and req.can_read(doctype, name):
		return doctype, name
	if doctype == "User" and name in users:
		return doctype, name
	return "User", actor if actor in users else None


def preview(project: str, template: str, assignments) -> req.SpecificationTemplatePreviewResponse:
	access.check_project(project, "write")
	doc = frappe.get_doc("Project", project)
	assignees = _project_assignees(doc)
	plan = _plan(doc, template, _parse_assignments(assignments), assignees)
	return {
		"digest": plan.digest,
		"assignees": assignees,
		"specifications": [
			{"name": name, "title": source.title, "responsible": plan.assignees[name][1]}
			for name, source in plan.graph.specifications.items()
		],
		"requirements": [
			{
				"name": name,
				"parent": parent,
				"responsible_type": plan.assignees[name][0],
				"responsible": plan.assignees[name][1],
				"title": plan.graph.requirements[name].requirement_title,
			}
			for name, parent in plan.requirement_order
		],
	}


def _copy_requirements(plan: TemplatePlan, project: str) -> dict[str, str]:
	created = {}
	for name, parent in plan.requirement_order:
		source = plan.graph.requirements[name]
		author_type, author = req.participant_link(source, "author")
		responsible_type, responsible = plan.assignees[name]
		data = {key: source.get(key) for key in req.REQUIREMENT_CONTENT_FIELDS}
		doc = frappe.get_doc(
			{
				**data,
				"doctype": req.REQUIREMENT,
				"project": project,
				"status": "New",
				"template_source": name,
				"author_type": author_type,
				"author": author,
				"responsible_type": responsible_type,
				"responsible": responsible,
				"is_group": source.is_group,
				req.PARENT: created.get(parent),
				"goals": [{"goal": row.goal} for row in source.goals],
			}
		)
		with req.copying_from(req.REQUIREMENT, name):
			doc.insert()
		created[name] = doc.name
	return created


def _copy_specifications(
	plan: TemplatePlan, project: str, requirement_names: dict[str, str]
) -> dict[str, str]:
	created = {}
	stack = [(plan.root, False)]
	while stack:
		name, ready = stack.pop()
		if name in created:
			continue
		source = plan.graph.specifications[name]
		if not ready:
			stack.append((name, True))
			stack.extend(
				(target, False)
				for doctype, target in reversed(req.item_edges(source))
				if doctype == req.SPEC_TEMPLATE
			)
			continue
		items = [
			{
				"reference_doctype": req.REQUIREMENT if doctype == req.REQUIREMENT else req.SPECIFICATION,
				"reference_name": requirement_names[target]
				if doctype == req.REQUIREMENT
				else created[target],
			}
			for doctype, target in req.item_edges(source)
		]
		doc = frappe.get_doc(
			{
				"doctype": req.SPECIFICATION,
				"project": project,
				"template_source": name,
				"title": source.title,
				"description": source.description,
				"author": source.author,
				"responsible": plan.assignees[name][1],
				"items": items,
			}
		)
		with req.copying_from(req.SPECIFICATION, name):
			doc.insert()
		created[name] = doc.name
	return created


def _replay(application_name: str, request_digest: str) -> req.SpecificationTemplateResponse | None:
	row = frappe.db.get_value(
		APPLICATION, application_name, ["request_digest", "created_map"], as_dict=True, for_update=True
	)
	if not row:
		return None
	if row.request_digest != request_digest:
		frappe.throw(_("This template request key was already used with different parameters."))
	result = json.loads(row.created_map)
	for doctype, field in ((req.SPECIFICATION, "specifications"), (req.REQUIREMENT, "requirements")):
		for name in result[field].values():
			access.check_document(doctype, name)
	return result


def apply(project: str, template: str, request_key: str, preview_digest: str, assignments) -> req.SpecificationTemplateResponse:
	if not request_key or len(request_key) > 140 or not preview_digest or len(preview_digest) != 64:
		frappe.throw(_("Open the template preview before applying it."))
	selected = _parse_assignments(assignments)
	actor = frappe.session.user
	application_name = content_digest([APPLICATION, req.SPEC_TEMPLATE, actor, request_key])
	request_digest = content_digest([project, template, preview_digest, selected])
	access.check_project(project)
	req.lock_graph()
	access.lock_project(project)
	if result := _replay(application_name, request_digest):
		return result
	access.check_project(project, "write")
	project_doc = frappe.get_doc("Project", project, for_update=True)
	plan = _plan(project_doc, template, selected, _project_assignees(project_doc), for_update=True)
	if plan.digest != preview_digest:
		frappe.throw(_("The template or project assignments changed. Open the preview again."))

	savepoint = f"apply_requirement_template_{frappe.generate_hash(length=12)}"
	frappe.db.savepoint(savepoint)
	try:
		requirement_names = _copy_requirements(plan, project)
		specification_names = _copy_specifications(plan, project, requirement_names)
		result: req.SpecificationTemplateResponse = {
			"root": specification_names[template],
			"specifications": specification_names,
			"requirements": requirement_names,
		}
		project_doc.append(req.PROJECT_SPECIFICATIONS, {"specification": result["root"]})
		project_doc.save()
		# The graph and project are locked, and the caller was authorized for each created record.
		frappe.get_doc(
			{
				"doctype": APPLICATION,
				"project": project,
				"template_doctype": req.SPEC_TEMPLATE,
				"template": template,
				"requested_by": actor,
				"applied_at": now_datetime(),
				"request_digest": request_digest,
				"created_map": json.dumps(result),
			}
		).insert(ignore_permissions=True, set_name=application_name)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	else:
		frappe.db.release_savepoint(savepoint)
	return result
