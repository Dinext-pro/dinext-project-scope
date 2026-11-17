"""Definitions, snapshots and project links for result work."""

from graphlib import CycleError, TopologicalSorter
from math import isfinite

import frappe
from frappe import _
from frappe.utils import cint, cstr, escape_html

from dinext_project_scope import access
from dinext_project_scope.deliverable_calculations import DELIVERABLE

TYPE = "Project Deliverable Type"
TASK = "Task"
WORK_TYPES = {TASK: ("Task Type", "type"), DELIVERABLE: (TYPE, "deliverable_type")}
STRUCTURE = "Project Deliverable Structure"
SOURCE_FIELDS = (
	"source_type",
	"source_element_key",
	"element_name",
	"element_type",
	"filter_doctype",
	"filter_type",
	"is_optional",
)
PROJECT_LINKS = (
	("deliverable_scopes", "project_scope", "Project Scope"),
	("deliverable_requirements", "project_requirement", "Project Requirement"),
	("deliverable_constraints", "project_constraint", "Project Constraint"),
)


def validate_type_definition(doc):
	before = doc.get_doc_before_save()
	previous = {row.name: row for row in before.elements} if before else {}
	keys = set()
	for row in doc.elements:
		prior = previous.get(row.name)
		key = cstr(row.element_key).strip()
		if prior and prior.element_key and key != prior.element_key:
			frappe.throw(_("The key of an existing type element cannot be changed."))
		row.element_key = key or (prior and prior.name) or frappe.generate_hash(length=12)
		if row.element_key in keys:
			frappe.throw(_("Each element in a result type must have a different key."))
		keys.add(row.element_key)
		if row.element_type not in WORK_TYPES:
			frappe.throw(_("Choose Task or Project Deliverable as the work type."))
		row.filter_doctype = WORK_TYPES[row.element_type][0]
		if row.filter_type and (
			not prior or (row.filter_doctype, row.filter_type) != (prior.filter_doctype, prior.filter_type)
		):
			access.check_document(row.filter_doctype, row.filter_type)
		row.weight = validate_weight(row.weight)


def validate_weight(value):
	if value is None or value == "":
		return 1.0
	try:
		weight = float(value)
	except (TypeError, ValueError, OverflowError):
		weight = -1
	if not isfinite(weight) or weight < 0:
		frappe.throw(_("The work weight must be a non-negative number."))
	if weight >= 10**12:
		frappe.throw(_("The work weight is outside the supported range."))
	return weight


def from_type(deliverable_type, *, current=False):
	if current:
		doc = frappe.get_doc(TYPE, deliverable_type, for_update=True)
		doc.check_permission("read")
	else:
		doc = access.check_document(TYPE, deliverable_type)
	if not doc.enabled:
		frappe.throw(_("Result type {0} is disabled.").format(frappe.bold(escape_html(deliverable_type))))
	return [
		{
			"source_type": deliverable_type,
			"source_element_key": row.element_key or row.name,
			"element_name": row.element_name,
			"element_type": row.element_type,
			"filter_doctype": WORK_TYPES[row.element_type][0],
			"filter_type": row.filter_type or None,
			"is_optional": cint(row.is_optional),
			"weight": validate_weight(row.weight),
			"element": None,
		}
		for row in doc.elements
	]


def snapshot(rows):
	data = []
	for row in rows:
		item = {field: row.get(field) or None for field in SOURCE_FIELDS}
		item["source_element_key"] = item["source_element_key"] or row.get("name")
		item["is_optional"] = cint(row.get("is_optional"))
		item["weight"] = validate_weight(row.get("weight"))
		item["element"] = row.get("element") or None
		data.append(item)
	return data


def seed_structure(doc, new_rows):
	provided = snapshot(doc.table_xuct)
	provided_by_key = {row["source_element_key"]: row for row in provided}
	keys = {row["source_element_key"] for row in new_rows}
	if len(provided_by_key) != len(provided) or not provided_by_key.keys() <= keys:
		frappe.throw(_("Select work for the elements defined by the result type."))
	for row in new_rows:
		initial = provided_by_key.get(row["source_element_key"])
		if initial:
			row.update({"element": initial["element"], "weight": initial["weight"]})
	doc.set("table_xuct", new_rows)


def validate_saved_structure(doc, before):
	if not before:
		seed_structure(
			doc,
			doc.flags.initial_structure
			if doc.flags.initial_structure is not None
			else from_type(doc.deliverable_type, current=True),
		)
		return
	if doc.flags.structure_refresh:
		return
	if before.deliverable_type != doc.deliverable_type:
		frappe.throw(_("Use the structure preview to change the result type."))
	old = [tuple(row[field] for field in SOURCE_FIELDS) for row in snapshot(before.table_xuct)]
	new = [tuple(row[field] for field in SOURCE_FIELDS) for row in snapshot(doc.table_xuct)]
	if old != new:
		frappe.throw(
			_("Keep all elements of the saved result structure. Use the structure preview to update it.")
		)


def validate_links(doc, before):
	for table_field, link_field, target in PROJECT_LINKS:
		prior = {row.get(link_field) for row in before.get(table_field)} if before else set()
		for name in {row.get(link_field) for row in doc.get(table_field)} - {None, ""}:
			if not doc.project or doc.status == "Template":
				frappe.throw(_("A result template cannot link to project records."))
			access.validate_project_target(
				doc.project,
				target,
				name,
				require_membership=name not in prior,
				check_permission=name not in prior,
			)


def work_target(row, project, *, for_update=False):
	doctype = row["element_type"]
	if doctype not in WORK_TYPES:
		frappe.throw(_("Choose Task or Project Deliverable as the work type."))
	type_field = WORK_TYPES[doctype][1]
	return frappe.db.get_value(
		doctype,
		{"name": row["element"], "project": project},
		["project", "status", type_field],
		as_dict=True,
		for_update=for_update,
	)


def target_matches(row, project, *, for_update=False):
	work = work_target(row, project, for_update=for_update)
	return bool(
		work
		and work.project == project
		and work.status != "Template"
		and (not row["filter_type"] or work.get(WORK_TYPES[row["element_type"]][1]) == row["filter_type"])
	)


def validate_work_links(doc, before):
	old = {row["source_element_key"]: row for row in snapshot(before.table_xuct)} if before else {}
	for row in snapshot(doc.table_xuct):
		if not row["element"]:
			continue
		if not doc.project or doc.status == "Template":
			frappe.throw(_("A result template cannot link to project work."))
		if row["element_type"] == DELIVERABLE and row["element"] == doc.name:
			frappe.throw(_("A result cannot be included in its own structure."))
		if not target_matches(row, doc.project, for_update=True):
			frappe.throw(
				_("Choose work from this project with the type required for {0}.").format(
					frappe.bold(escape_html(row["element_name"]))
				)
			)
		previous = old.get(row["source_element_key"])
		if not previous or (row["element_type"], row["element"]) != (
			previous["element_type"],
			previous["element"],
		):
			access.check_document(row["element_type"], row["element"])


def validate_referenced_work(doc, before):
	if not before:
		return
	type_field = WORK_TYPES[doc.doctype][1]
	if (doc.project, doc.get(type_field), doc.status == "Template") == (
		before.project,
		before.get(type_field),
		before.status == "Template",
	):
		return
	table = frappe.qb.DocType(STRUCTURE)
	rows = (
		frappe.qb.from_(table)
		.select(table.element_name, table.filter_type)
		.where(
			(table.parenttype == DELIVERABLE)
			& (table.parentfield == "table_xuct")
			& (table.element_type == doc.doctype)
			& (table.element == doc.name)
		)
		.for_update()
		.run(as_dict=True)
	)
	for row in rows:
		if (
			doc.project != before.project
			or doc.status == "Template"
			or (row.filter_type and doc.get(type_field) != row.filter_type)
		):
			frappe.throw(
				_("Remove or replace the work linked to {0} before changing its project or type.").format(
					frappe.bold(escape_html(row.element_name))
				)
			)


def child_first_order(dependencies):
	try:
		return list(TopologicalSorter(dependencies).static_order())
	except CycleError:
		frappe.throw(_("The selected work creates a cycle between results."))


def reconcile(doc, new_type, *, current=False):
	new_rows = from_type(new_type, current=current)
	old_rows = snapshot(doc.table_xuct)
	old_by_key = {row["source_element_key"]: (index, row) for index, row in enumerate(old_rows)}
	new_keys = {row["source_element_key"] for row in new_rows}
	changes = []
	for index, row in enumerate(new_rows):
		previous = old_by_key.get(row["source_element_key"])
		if not previous:
			changes.append({"action": "Added", "before": None, "after": row})
			continue
		old_index, old = previous
		row["weight"] = old["weight"]
		if old["element"] and old["element_type"] == row["element_type"]:
			row["element"] = old["element"]
			if not target_matches(row, doc.project, for_update=current):
				row["element"] = None
		if row != old or old_index != index:
			changes.append(
				{
					"action": "Updated" if row != old else "Reordered",
					"before": old,
					"after": row,
					"previous_position": old_index + 1,
					"position": index + 1,
				}
			)
	for row in old_rows:
		if row["source_element_key"] not in new_keys:
			changes.append({"action": "Removed", "before": row, "after": None})
	return new_rows, changes
