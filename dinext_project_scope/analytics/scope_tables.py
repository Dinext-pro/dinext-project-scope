from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from dinext_project_scope import access, project_scope, requirements
from dinext_project_scope.analytics import data
from dinext_project_scope.analytics.contracts import Participant, ReportResponse
from dinext_project_scope.analytics.reports import column

PROJECT_TABLES = {
	"scope_items": project_scope.SCOPE_TABLE,
	"constraints": project_scope.CONSTRAINT_TABLE,
}
TABLE_FILTERS = {
	"scope_items": {"scope_type"},
	"requirements": {"status", "kind", "priority", "requirement_importance"},
	"constraints": {"category", "record_type", "status", "responsible"},
	"change_requests": {"status", "creation", "initiator", "implementation_responsible"},
}


def _parse_argument(value, collection_type):
	if value is None or value == "":
		return None
	try:
		parsed = frappe.parse_json(value)
	except ValueError:
		frappe.throw(_("Invalid report filters."))
	if not isinstance(parsed, collection_type):
		frappe.throw(_("Invalid report filters."))
	return parsed


def _matches(row, filters):
	return all(
		not row.get(key) if value == data.ONLY_EMPTY else row.get(key) == value
		for key, value in filters.items()
		if value
	)


def _person_key(doctype, name):
	return f"{doctype}:{name}" if doctype in data.PARTICIPANT_IMAGE_FIELDS and name else None


def _person_label(row, field):
	return (row.get(f"{field}_profile") or {}).get("label") or row.get(field)


def _translated(value, context):
	return _(value, context=context) if value else None


def _project_child_rows(project, field, *, export=False):
	doc = access.check_project(project)
	if export:
		doc.check_permission("export")
	doc.apply_fieldlevel_read_permissions()
	return doc.get(field) or []


@frappe.whitelist(methods=["GET", "POST"])
def project_constraint_profiles(project: str) -> dict[str, Participant]:
	"""Return profiles for people linked in the readable Project constraints table."""
	rows = _project_child_rows(project, project_scope.CONSTRAINT_TABLE)
	members = [data.participant(row) for row in rows]
	profiles = data.member_profiles(members)
	return {
		key: data.participant_avatar(doctype, name, profiles)
		for doctype, name in members
		if (key := _person_key(doctype, name))
	}


def _scope_items(rows, filters):
	columns = [
		column("scope_title", _("Title"), width=260),
		column("scope_type", _("Type"), width=168),
		column("object_ref", _("Object"), width=200),
		column("description", _("Description"), width=340),
	]
	return columns, [
		{
			"scope_title": row.get("scope_title"),
			"scope_type": _translated(row.get("scope_type"), "Project Scope Type"),
			"object_ref": row.get("object_ref"),
			"description": row.get("description"),
		}
		for row in rows
		if _matches(row, filters)
	]


def _constraints(rows, filters):
	columns = [
		column("subject", _("Subject"), width=260),
		column("category", _("Category"), width=150),
		column("record_type", _("Record Type"), width=128),
		column("status", _("Status"), kind="status", width=128),
		column("responsible", _("Responsible"), width=168),
	]
	matched = []
	for row in rows:
		doctype, name = data.participant(row)
		if _matches(
			{
				"category": row.get("category"),
				"record_type": row.get("record_type"),
				"status": row.get("status"),
				"responsible": _person_key(doctype, name),
			},
			filters,
		):
			matched.append((row, doctype, name))

	profiles = data.member_profiles((doctype, name) for _, doctype, name in matched)
	return columns, [
		{
			"document_type": data.CONSTRAINT,
			"subject": row.get("subject"),
			"category": row.get("category"),
			"record_type": _translated(row.get("record_type"), data.CONSTRAINT),
			"status": row.get("status"),
			"responsible": data.participant_avatar(doctype, name, profiles)["label"] if name else None,
		}
		for row, doctype, name in matched
	]


def _requirement_rows(rows, filters):
	by_name = {row["name"]: row for row in rows}
	visible = set()
	for row in rows:
		if not _matches(row, filters):
			continue
		name = row["name"]
		while name in by_name and name not in visible:
			visible.add(name)
			name = by_name[name].get("parent")

	depths = {}
	for row in rows:
		name = row["name"]
		if name not in visible:
			continue
		depth = depths.get(row.get("parent"), -1) + 1
		depths[name] = depth
		paths = row["paths"]
		specifications = dict.fromkeys(specification for path in paths for specification in path)
		yield {
			**row,
			"document_type": data.REQUIREMENT,
			"title": row.get("title") or name,
			"depth": depth,
			"priority": _translated(row.get("priority"), data.REQUIREMENT),
			"kind": _translated(row.get("kind"), "Requirement Kind"),
			"requirement_importance": _translated(row.get("requirement_importance"), data.REQUIREMENT),
			"author": _person_label(row, "author"),
			"responsible": _person_label(row, "responsible"),
			"specifications": ", ".join(specifications) or "—",
			"inclusion_paths": "\n".join(
				" → ".join(path) if path else _("Included directly") for path in paths
			),
		}


def _requirements(project, specification, filters):
	frappe.has_permission(data.REQUIREMENT, "export", throw=True)
	rows = requirements.project_rows(project, specification)
	columns = [
		column("title", _("Requirement"), width=264),
		column("status", _("Status"), kind="status", width=142),
		column("priority", _("Priority"), width=95),
		column("kind", _("Kind"), width=150),
		column("author", _("Author"), width=160),
		column("requirement_importance", _("Importance"), width=120),
		column("responsible", _("Responsible"), width=168),
		column("specifications", _("Specifications"), width=220),
		column("name", _("ID"), width=138),
		column("parent", _("Parent Requirement"), width=145),
		column("inclusion_paths", _("Inclusion paths"), width=260),
	]
	return columns, list(_requirement_rows(rows, filters))


def _change_requests(project, filters):
	frappe.has_permission(data.CHANGE_REQUEST, "export", throw=True)
	columns = [
		column("title", _("Change Request"), width=264),
		column("status", _("Status"), kind="status", width=145),
		column("implementation_responsible", _("Responsible"), width=168),
		column("initiator", _("Initiator"), width=168),
		column("creation", _("Created on"), kind="datetime", width=150),
		column("name", _("Request ID"), width=138),
	]
	rows = []
	for row in project_scope.project_change_rows(project):
		if not _matches(
			{
				"status": row.get("status"),
				"creation": getdate(row["creation"]).isoformat() if row.get("creation") else None,
				"initiator": _person_key("Contact", row.get("initiator")),
				"implementation_responsible": _person_key("User", row.get("implementation_responsible")),
			},
			filters,
		):
			continue
		rows.append(
			{
				**row,
				"document_type": data.CHANGE_REQUEST,
				"title": row.get("title") or row["name"],
				"initiator": _person_label(row, "initiator"),
				"implementation_responsible": _person_label(row, "implementation_responsible"),
			}
		)
	return columns, rows


def scope_table_dataset(
	project: str,
	table: str,
	filters: dict[str, str | None] | str | None,
	specification: str | None,
	row_names: list[str] | str | None,
) -> ReportResponse:
	if not isinstance(table, str) or table not in TABLE_FILTERS:
		frappe.throw(_("This table is unavailable."))
	values = _parse_argument(filters, dict) or {}
	if any(
		key not in TABLE_FILTERS[table] or (value is not None and not isinstance(value, str))
		for key, value in values.items()
	):
		frappe.throw(_("Invalid report filters."))

	names = _parse_argument(row_names, list)
	if names is not None and (
		table not in PROJECT_TABLES or any(not isinstance(name, str) or not name for name in names)
	):
		frappe.throw(_("Invalid report filters."))
	if specification and table != "requirements":
		frappe.throw(_("Invalid report filters."))

	if table == "requirements":
		return _requirements(project, specification, values)
	if table == "change_requests":
		return _change_requests(project, values)

	rows = _project_child_rows(project, PROJECT_TABLES[table], export=True)
	if names is not None:
		allowed = set(names)
		rows = [row for row in rows if row.name in allowed]
	if table == "scope_items":
		return _scope_items(rows, values)
	return _constraints(rows, values)
