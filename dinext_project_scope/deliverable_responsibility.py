"""Project roles, assignment suggestions and required responsibilities."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import escape_html

from dinext_project_scope import access

CATEGORY = "Project Deliverable Category"
RESPONSIBILITY = "Project Deliverable Responsibility"
ASSIGNMENT_FIELDS = ("responsibility", "project_role", "responsible_type", "responsible")


def assignment_key(row):
	return tuple(row.get(key) or ("User" if key == "responsible_type" else None) for key in ASSIGNMENT_FIELDS)


def current_members(project, *, current=False):
	participants = access.project_participants(project, current=current)
	roles = sorted({row["role"] for row in participants if row["role"]})
	if not roles:
		return set()
	enabled = set(frappe.get_all("Project Role", filters={"enabled": 1, "name": ("in", roles)}, pluck="name"))
	return {
		(row["role"], row["doctype"], row["name"])
		for row in participants
		if row["role"] in enabled and row["doctype"] in ("User", "Contact")
	}


def responsibility_definitions():
	return {
		row.name: row
		for row in frappe.get_all(RESPONSIBILITY, fields=["name", "enabled", "required", "single"])
	}


def configured_roles(categories):
	pairs = defaultdict(set)
	categories = sorted({category for category in categories if category})
	if categories:
		for row in frappe.get_all(
			"Project Deliverable Category Responsibility",
			filters={"parent": ("in", categories), "parenttype": CATEGORY, "parentfield": "responsibilities"},
			fields=["parent", "responsibility", "project_role"],
		):
			pairs[row.parent].add((row.responsibility, row.project_role))
	return pairs


def validate_category(doc):
	seen = set()
	for row in doc.responsibilities:
		key = row.project_role, row.responsibility
		if key in seen:
			frappe.throw(_("A category can suggest a responsibility only once per project role."))
		seen.add(key)


def category_suggestions(project, category, *, members=None, definitions=None):
	if not category:
		return []
	members = current_members(project) if members is None else members
	definitions = responsibility_definitions() if definitions is None else definitions
	suggestions = []
	for row in frappe.get_doc(CATEGORY, category).responsibilities:
		definition = definitions.get(row.responsibility)
		if not definition or not definition.enabled:
			continue
		if not frappe.has_permission("Project Role", doc=row.project_role, ptype="select"):
			continue
		candidates = [
			{"doctype": doctype, "name": name}
			for role, doctype, name in sorted(members)
			if role == row.project_role and frappe.has_permission(doctype, doc=name, ptype="select")
		]
		suggestions.append(
			{"responsibility": row.responsibility, "project_role": row.project_role, "candidates": candidates}
		)
	return suggestions


def default_assignments(suggestions, existing=(), definitions=None):
	definitions = responsibility_definitions() if definitions is None else definitions
	explicit = defaultdict(set)
	automatic = defaultdict(set)
	existing_keys = {assignment_key(row) for row in existing}
	for responsibility, _role, doctype, name in existing_keys:
		explicit[responsibility].add((doctype, name))
	for suggestion in suggestions:
		if len(suggestion["candidates"]) == 1:
			member = suggestion["candidates"][0]
			automatic[suggestion["responsibility"]].add((member["doctype"], member["name"]))

	result = []
	for suggestion in suggestions:
		responsibility = suggestion["responsibility"]
		role = suggestion["project_role"]
		if len(suggestion["candidates"]) != 1 or any(
			key[:2] == (responsibility, role) for key in existing_keys
		):
			continue
		member = suggestion["candidates"][0]
		identity = member["doctype"], member["name"]
		if definitions[responsibility].single and (explicit[responsibility] or automatic[responsibility]) != {
			identity
		}:
			continue
		result.append(dict(zip(ASSIGNMENT_FIELDS, (responsibility, role, *identity), strict=True)))
	return result


def validate_assignments(doc, before):
	members = current_members(doc.project, current=True)
	definitions = responsibility_definitions()
	allowed = configured_roles([doc.category])[doc.category]
	if not before:
		category = category_suggestions(doc.project, doc.category, members=members, definitions=definitions)
		doc.extend(
			"deliverable_responsibles",
			default_assignments(category, doc.deliverable_responsibles, definitions),
		)
	prior = (
		{assignment_key(row) for row in before.deliverable_responsibles}
		if before and before.category == doc.category
		else set()
	)
	seen = set()
	people = defaultdict(set)
	for row in list(doc.deliverable_responsibles):
		key = assignment_key(row)
		responsibility, role, doctype, name = key
		if key in seen:
			doc.remove(row)
			continue
		seen.add(key)
		definition = definitions.get(responsibility)
		if key not in prior:
			if not role or (role, doctype, name) not in members:
				frappe.throw(_("Choose a current project participant in the selected role."))
			if not definition or not definition.enabled:
				frappe.throw(_("Choose an active responsibility."))
			if (responsibility, role) not in allowed:
				frappe.throw(
					_("Choose a project role configured for this responsibility in the result category.")
				)
			access.check_document("Project Role", role, "select")
			access.check_document(doctype, name, "select")
		if definition and definition.single:
			people[responsibility].add((doctype, name))
			if len(people[responsibility]) > 1:
				frappe.throw(
					_("Responsibility {0} can have only one participant.").format(
						frappe.bold(escape_html(responsibility))
					)
				)
	return missing_responsibilities(doc.deliverable_responsibles, allowed, definitions, members=members)


def missing_responsibilities(rows, allowed, definitions=None, *, members=None):
	definitions = responsibility_definitions() if definitions is None else definitions
	assigned = {
		key[0]
		for row in rows
		if (key := assignment_key(row))[:2] in allowed
		and key[2] in ("User", "Contact")
		and key[3]
		and (members is None or key[1:] in members)
	}
	return sorted(
		name
		for name in {responsibility for responsibility, _role in allowed}
		if (definition := definitions.get(name))
		and definition.get("enabled")
		and definition.get("required")
		and name not in assigned
	)
