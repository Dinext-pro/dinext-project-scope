"""Preview and copy result templates with links local to each application."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cstr, escape_html

from dinext_project_scope import access
from dinext_project_scope import deliverable_structure as structure
from dinext_project_scope.deliverable_calculations import DELIVERABLE, work_digest
from dinext_project_scope.deliverable_responsibility import (
	ASSIGNMENT_FIELDS,
	CATEGORY,
	category_suggestions,
	current_members,
	default_assignments,
	responsibility_definitions,
)

TEMPLATE = "Project Deliverables Template"


def _template_items(doc):
	items = {}
	for row in doc.deliverables:
		if row.item_key in items:
			frappe.throw(_("Each result in a template must have a different key."))
		items[row.item_key] = row
	return items


def validate_template(doc):
	before = doc.get_doc_before_save()
	previous = {row.name: row for row in before.deliverables} if before else {}
	for row in doc.deliverables:
		prior = previous.get(row.name)
		key = cstr(row.item_key).strip()
		if prior and prior.item_key and key != prior.item_key:
			frappe.throw(_("The key of an existing template result cannot be changed."))
		row.item_key = key or frappe.generate_hash(length=12)
		row.title = cstr(row.title).strip()
		access.check_document(CATEGORY, row.category)

	items = _template_items(doc)
	source_slots = {key: structure.from_type(row.deliverable_type) for key, row in items.items()}
	slot_keys = {(owner, row["source_element_key"]) for owner, rows in source_slots.items() for row in rows}
	prior_slots = {row.name: row for row in before.elements} if before else {}
	prior_items = {row.item_key for row in before.deliverables} if before else set()
	provided = {}
	for row in doc.elements:
		key = (row.owner_item_key, row.source_element_key)
		if key in provided:
			frappe.throw(_("A result can use each type element only once in a template."))
		prior = prior_slots.get(row.name)
		if key not in slot_keys:
			if prior and key == (prior.owner_item_key, prior.source_element_key):
				continue
			frappe.throw(_("Choose a type element from the template result that owns this work."))
		if (
			prior
			and row.nested_item_key == prior.nested_item_key
			and row.nested_item_key in prior_items - items.keys()
		):
			row.nested_item_key = None
		provided[key] = row

	elements = []
	for owner, rows in source_slots.items():
		for item in rows:
			row = provided.get((owner, item["source_element_key"]))
			element = {key: item[key] for key in (*structure.SOURCE_FIELDS[1:], "weight")}
			element["owner_item_key"] = owner
			element["nested_item_key"] = row.nested_item_key if row and row.nested_item_key else None
			if row:
				element["weight"] = structure.validate_weight(row.weight)
				element["name"] = row.name
			elements.append(element)
	_template_order(items, elements)
	doc.set("elements", elements)


def _template_order(items, elements):
	dependencies = {key: [] for key in items}
	for row in elements:
		owner, target = row.get("owner_item_key"), row.get("nested_item_key")
		if owner not in items:
			frappe.throw(_("Choose the template result that owns this work."))
		if not target:
			continue
		if row.get("element_type") != DELIVERABLE or target not in items:
			frappe.throw(_("Choose a nested result from the same template."))
		if row.get("filter_type") and items[target].deliverable_type != row.get("filter_type"):
			frappe.throw(_("The nested result has a different type than this element allows."))
		dependencies[owner].append(target)
	return structure.child_first_order(dependencies)


def _plan(project, doc, *, current=False):
	if doc.docstatus == 2:
		frappe.throw(_("A cancelled result template cannot be applied."))
	items = _template_items(doc)
	if not items:
		frappe.throw(_("Add at least one result to the template."))
	order = _template_order(items, doc.elements)
	elements = defaultdict(list)
	for row in doc.elements:
		item = structure.snapshot([row])[0]
		item["source_type"] = items[row.owner_item_key].deliverable_type
		item["nested_item_key"] = row.nested_item_key or None
		elements[row.owner_item_key].append(item)

	members = current_members(project, current=current)
	definitions = responsibility_definitions()
	categories = {}
	sources = {}
	for key, row in items.items():
		kind = access.check_document(structure.TYPE, row.deliverable_type)
		if not kind.enabled:
			frappe.throw(
				_("Result type {0} is disabled.").format(frappe.bold(escape_html(row.deliverable_type)))
			)
		if row.category not in categories:
			category = access.check_document(CATEGORY, row.category)
			if not category.enabled:
				frappe.throw(_("Choose an active result category."))
			categories[row.category] = category_suggestions(
				project, row.category, members=members, definitions=definitions
			)
		suggested = categories[row.category]
		sources[key] = {
			"key": key,
			"title": row.title,
			"deliverable_type": row.deliverable_type,
			"category": row.category,
			"work": elements[key],
			"responsibilities": suggested,
			"defaults": default_assignments(suggested, definitions=definitions),
		}
	token = work_digest([project, doc.name, cstr(doc.modified), list(sources.values())])
	return sources, order, token


def _check_application_access(project, template):
	access.check_project(project, "write")
	frappe.has_permission(DELIVERABLE, "create", throw=True)
	return access.check_document(TEMPLATE, template)


@frappe.whitelist()
def preview_template(project: str, template: str):
	doc = _check_application_access(project, template)
	sources, _order, token = _plan(project, doc)
	return {"items": list(sources.values()), "token": token}


def _selections(value):
	if isinstance(value, str):
		value = frappe.parse_json(value)
	if value is None:
		return {}
	if not isinstance(value, dict) or any(not isinstance(selection, dict) for selection in value.values()):
		frappe.throw(_("Choose valid links for the results in the template preview."))
	return value


def _link_values(selection, field):
	value = selection.get(field, [])
	if not isinstance(value, list) or any(not isinstance(name, str) or not name for name in value):
		frappe.throw(_("Choose valid links for the results in the template preview."))
	return list(dict.fromkeys(value))


def _work_selection(source, selection, created):
	work = selection.get("work", {})
	if not isinstance(work, dict) or any(
		name is not None and not isinstance(name, str) for name in work.values()
	):
		frappe.throw(_("Choose valid links for the results in the template preview."))
	allowed = {row["source_element_key"] for row in source["work"] if not row["nested_item_key"]}
	if work.keys() - allowed:
		frappe.throw(_("Links within a result template are filled automatically."))
	rows = []
	for row in source["work"]:
		nested = row["nested_item_key"]
		element = created[nested] if nested else work.get(row["source_element_key"])
		rows.append(
			{
				**{key: value for key, value in row.items() if key != "nested_item_key"},
				"element": element,
				"element_doctype": structure.element_doctype(row),
			}
		)
	return rows


def _assignments(selection):
	value = selection.get("assignments", [])
	if not isinstance(value, list) or any(
		not isinstance(row, dict)
		or any(not isinstance(row.get(field), str) or not row[field] for field in ASSIGNMENT_FIELDS)
		for row in value
	):
		frappe.throw(_("Choose a current project participant in the selected role."))
	return [{field: row[field] for field in ASSIGNMENT_FIELDS} for row in value]


def _create_results(project, template, token, selections):
	doc = frappe.get_doc(TEMPLATE, template, for_update=True)
	doc.check_permission("read")
	sources, order, current_token = _plan(project, doc, current=True)
	if token != current_token:
		frappe.throw(_("The template or project participants changed. Preview it again."))
	if selections.keys() - sources.keys():
		frappe.throw(_("Choose valid links for the results in the template preview."))

	created = {}
	for key in order:
		source = sources[key]
		selection = selections.get(key, {})
		work = _work_selection(source, selection, created)
		result = frappe.get_doc(
			{
				"doctype": DELIVERABLE,
				"project": project,
				"status": "Not Started",
				"title": source["title"],
				"deliverable_type": source["deliverable_type"],
				"category": source["category"],
				"table_xuct": work,
				"deliverable_responsibles": _assignments(selection),
				**{
					table: [{field: name} for name in _link_values(selection, table)]
					for table, field, _doctype in structure.PROJECT_LINKS
				},
			}
		)
		result.flags.initial_structure = work
		result.flags.structural_source = (TEMPLATE, template)
		result.insert()
		created[key] = result.name
	return created


@frappe.whitelist(methods=["POST"])
def apply_template(project: str, template: str, token: str, request_key: str, selections=None):
	from dinext_project_scope.template_application import apply_once

	_check_application_access(project, template)
	selected = _selections(selections)
	created = apply_once(
		project,
		TEMPLATE,
		template,
		request_key,
		{"token": token, "selections": selected},
		lambda: _create_results(project, template, token, selected),
	)
	return {"created": created}
