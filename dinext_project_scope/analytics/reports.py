from collections import Counter, defaultdict
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, getdate

from dinext_project_scope.analytics import data
from dinext_project_scope.deliverable_responsibility import configured_roles, missing_responsibilities

TRACEABILITY = "Requirement Traceability Matrix"
RESPONSIBILITY = "Project Responsibility Matrix"
IMPACT = "Project Change Impact Matrix"
OVERVIEW = "Project Scope Overview"
DELIVERABLE_REGISTER = "Project Deliverable Register"
CONSTRAINT_REGISTER = "Project Constraint Register"
CHANGE_REGISTER = "Project Change Request Register"

IMPACT_COLORS = {"Weak": "#2E7D32", "Moderate": "#F9A825", "Strong": "#C62828"}
IMPACT_TONES = {"Weak": "green", "Moderate": "yellow", "Strong": "red"}
IMPACT_ORDER = {"Weak": 1, "Moderate": 2, "Strong": 3}
PROJECT_LINKS = {
	"Project Requirement",
	"Project Requirement Specification",
	"Project Deliverable",
	"Project Change Request",
	"Task",
}
CHILD_LINKS = {
	"Project Scope": "project_scopes",
	"Project Constraint": "project_constraints",
	"Project Risk": "custom_project_risks",
}
MATCH_IMPACT = {
	"impact_type": "type",
	"impact_level": "level",
	"link_doctype": "link_doctype",
	"link": "link",
}
REQUIREMENT_FILTERS = ("kind", "author", "responsible", "priority", "requirement_importance", "status")
CONSTRAINT_FILTERS = (
	"record_type",
	"category",
	"status",
	"verification_status",
	"responsible_type",
	"responsible",
)


def column(field, label, *, kind=None, width=130, group=None, group_id=None):
	fieldtype = {"date": "Date", "datetime": "Datetime", "progress": "Percent", "count": "Int"}.get(
		kind, "Data"
	)
	return {
		"fieldname": field,
		"label": label,
		"fieldtype": fieldtype,
		"width": width,
		"kind": kind,
		"group": group,
		"group_id": group_id,
	}


def flatten_rows(rows, depth=0):
	for row in rows:
		yield {key: value for key, value in row.items() if key != "children"} | {"depth": depth}
		yield from flatten_rows(row.get("children", ()), depth + 1)


def requirement_results(deliverables):
	links = data.child_rows(
		"Deliverable Requirement",
		deliverables,
		data.DELIVERABLE,
		"deliverable_requirements",
		["project_requirement"],
	)
	by_requirement = defaultdict(set)
	for name, rows in links.items():
		for row in rows:
			if row.get("project_requirement"):
				by_requirement[row["project_requirement"]].add(name)
	return by_requirement


def requirement_subtree(rows, selected):
	if selected not in rows:
		return set()
	edges = defaultdict(list)
	for name, row in rows.items():
		edges[row.get("parent")].append(name)
	visited = set()
	pending = [selected]
	while pending:
		node = pending.pop()
		if node not in visited:
			visited.add(node)
			pending.extend(edges.get(node, ()))
	# Keep descendants whose immediate parent was excluded from the project's saved composition.
	bounds = frappe.db.get_value(data.REQUIREMENT, selected, ["lft", "rgt"], as_dict=True)
	if bounds and bounds.lft and bounds.rgt:
		visited.update(
			data.select_rows(
				data.REQUIREMENT,
				{"name": ["in", list(rows)], "lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
				["name"],
			)
		)
	return visited


def scope_requirement_rows(project):
	from dinext_project_scope.requirements import project_rows

	return {row["name"]: row for row in project_rows(project)}


def traceability(filters):
	from dinext_project_scope.requirements import visible_specification_members

	project = data.project_ids(filters.get("project"), required=True)[0]
	full = scope_requirement_rows(project)
	candidates = full
	if specification := filters.get("specification"):
		members = visible_specification_members(project, specification)
		candidates = {name: row for name, row in candidates.items() if name in members}
	if selected := filters.get("requirement"):
		subtree = requirement_subtree(full, selected)
		candidates = {name: row for name, row in candidates.items() if name in subtree}

	deliverables = data.get_deliverables([project])
	relations = requirement_results(deliverables)
	structure = data.load_structure(deliverables)
	tree = data.StructureTree(
		deliverables,
		structure,
		data.available_tasks(project, structure),
		{},
		getdate(),
		other_work=data.available_other_work(project, structure),
	)
	selected = {
		name
		for name, row in candidates.items()
		if data.matches(row, filters, REQUIREMENT_FILTERS)
		and (not cint(filters.get("without_results")) or not relations.get(name))
	}
	visible = set(selected)
	for name in selected:
		parent = full[name].get("parent")
		while parent in full and parent not in visible:
			visible.add(parent)
			parent = full[parent].get("parent")

	nodes = {}
	for name in sorted(visible, key=lambda value: ((full[value].get("title") or value).casefold(), value)):
		requirement = full[name]
		result_names = relations.get(name, ())
		has_results = bool(result_names)
		status = requirement.get("status")
		nodes[name] = {
			"id": f"requirement-{quote(name, safe='')}",
			"label": requirement.get("title") or name,
			"document_type": data.REQUIREMENT,
			"document": name,
			"category": requirement.get("kind"),
			"status": status,
			"status_tone": data.STATUS_TONES.get(status) if has_results else "red",
			"status_note": "No linked deliverables in this project" if not has_results else None,
			"approval_stale": bool(requirement.get("approval_stale")),
			"context_only": name not in selected,
			"children": [],
		}

	def is_ancestor(child, parent):
		elapsed = {child}
		while parent in nodes:
			if parent in elapsed:
				return True
			elapsed.add(parent)
			parent = full[parent].get("parent")
		return False

	top = []
	for name, node in nodes.items():
		parent = full[name].get("parent")
		if parent in nodes and not is_ancestor(name, parent):
			nodes[parent]["children"].append(node)
		else:
			top.append(node)
	for name in selected:
		nodes[name]["children"].extend(
			sorted(
				(
					tree.deliverable(result, f"{nodes[name]['id']}/result-{quote(result, safe='')}")
					for result in relations.get(name, ())
				),
				key=data.row_sort_key,
			)
		)

	return [
		column("label", _("Traceability"), kind="label", width=330),
		column("category", _("Category"), width=160),
		column("status", _("State / Progress"), kind="trace_state", width=260),
		column("planned_end_date", _("Planned end", context="Dinext.ProjectScope.Dates"), kind="plan_date"),
	], list(flatten_rows(top))


def responsibility_matrix(deliverables, assignments, definitions, participant_profiles, role_names, filters):
	selected = filters.get("responsibility")
	selected_codes = set(selected) if isinstance(selected, list) else {selected} if selected else set()
	assignment_fields = ("project_role", "responsible_type", "responsible")
	filter_assignments = selected_codes or any(filters.get(key) for key in assignment_fields)
	cells_by_result = {}
	members = defaultdict(set)
	for name, result in deliverables.items():
		if not data.matches(result, filters, data.RESULT_FILTERS):
			continue
		cells = defaultdict(set)
		for row in assignments.get(name, ()):
			kind, identity = data.participant(row)
			if kind not in {"User", "Contact"} or not identity:
				continue
			role, code = row.get("project_role") or "", row.get("responsibility")
			if selected_codes and code not in selected_codes:
				continue
			if not data.matches(dict(row, responsible_type=kind), filters, assignment_fields):
				continue
			if code:
				cells[(role, kind, identity)].add(code)
				members[role].add((kind, identity))
		if cells or not filter_assignments:
			cells_by_result[name] = cells

	columns = [
		column("label", _("Category / Deliverable"), kind="label", width=280),
		column("deliverable_type", _("Deliverable type"), width=150),
	]
	fields = {}
	for role in sorted(
		members, key=lambda value: (not value, role_names.get(value, value).casefold(), value)
	):
		group_name = role_names.get(role) or role or _("Role not specified")
		avatars = [
			data.participant_avatar(kind, identity, participant_profiles) for kind, identity in members[role]
		]
		avatars.sort(key=lambda avatar: (avatar["label"].casefold(), avatar["doctype"], avatar["name"]))
		label_counts = Counter(avatar["label"] for avatar in avatars)
		for avatar in avatars:
			kind, identity, label = avatar["doctype"], avatar["name"], avatar["label"]
			if label_counts[label] > 1:
				label = f"{label} ({_(kind)} · {identity})"
			field = f"assignment_{len(fields) + 1}"
			fields[(role, kind, identity)] = field
			assignment_column = column(
				field,
				label,
				kind="raci",
				group=group_name,
				group_id=f"role:{role}",
				width=max(135, min(250, len(label) * 8)),
			)
			assignment_column["assignee"] = dict(avatar, label=label)
			columns.append(assignment_column)

	groups = defaultdict(list)
	for name, slots in cells_by_result.items():
		result = deliverables[name]
		category = result.get("category") or ""
		row = {
			"id": f"result-{quote(name, safe='')}",
			"label": result.get("title") or name,
			"document_type": data.DELIVERABLE,
			"document": name,
			"deliverable_type": result.get("deliverable_type"),
			"cells": {},
		}
		for key, codes in slots.items():
			entries = [
				{
					"code": code,
					"label": definitions.get(code, {}).get("responsibility") or code,
					"color": definitions.get(code, {}).get("color"),
				}
				for code in sorted(codes)
			]
			field = fields[key]
			row["cells"][field] = entries
			row[field] = " / ".join(entry["code"] for entry in entries)
		groups[category].append(row)

	tree = [
		{
			"id": f"category-{quote(category, safe='')}",
			"label": category or _("No category"),
			"is_group": True,
			"children": sorted(children, key=lambda row: (row["label"].casefold(), row["document"])),
		}
		for category, children in sorted(groups.items(), key=lambda pair: pair[0].casefold())
	]
	return columns, list(flatten_rows(tree))


def raci(filters):
	project = data.project_ids(filters.get("project"), required=True)
	deliverables = data.get_deliverables(project)
	assignments = data.load_assignments(deliverables)
	roles = sorted(
		{row["project_role"] for rows in assignments.values() for row in rows if row.get("project_role")}
	)
	role_names = {
		name: row.get("role_name") or name
		for name, row in (
			data.select_rows("Project Role", {"name": ["in", roles]}, ["name", "role_name"]).items()
			if roles
			else ()
		)
	}
	return responsibility_matrix(
		deliverables,
		assignments,
		data.responsibility_definitions(),
		data.participant_profiles(assignments),
		role_names,
		filters,
	)


def date_range(filters, start_field="from_date", end_field="to_date"):
	start = getdate(filters[start_field]) if filters.get(start_field) else None
	end = getdate(filters[end_field]) if filters.get(end_field) else None
	if (filters.get(start_field) and not start) or (filters.get(end_field) and not end):
		frappe.throw(_("Enter a valid report date."))
	if start and end and start > end:
		frappe.throw(_("The start date must be on or before the end date."))
	return start, end


def is_in_period(value, start, end):
	if not (start or end):
		return True
	if not value:
		return False
	day = getdate(value)
	return not ((start and day < start) or (end and day > end))


def matches_change(request, filters, start, end):
	return data.matches(
		request, filters, ("status", "initiator", "implementation_responsible")
	) and is_in_period(request.get("creation"), start, end)


def matches_impact(row, filters):
	return all(
		not filters.get(field)
		or (
			row.get(source) not in IMPACT_ORDER
			if field == "impact_level" and filters[field] == data.ONLY_EMPTY
			else row.get(source) == filters[field]
		)
		for field, source in MATCH_IMPACT.items()
	)


def impact_matrix(requests, impacts, active_types, filters):
	start, end = date_range(filters)
	match_filters = any(filters.get(field) for field in MATCH_IMPACT)
	types = set(active_types)
	selected = []
	for name, request in requests.items():
		if not matches_change(request, filters, start, end):
			continue
		details = [
			{**row, "matched": match_filters and matches_impact(row, filters)}
			for row in impacts.get(name, ())
		]
		if match_filters and not any(row["matched"] for row in details):
			continue
		selected.append((name, request, details))
		types.update(row.get("type") or "" for row in details)

	columns = change_columns(impact=True)
	column_by_type = {}
	for impact_type in sorted(types, key=lambda value: (not bool(value), value.casefold())):
		field = f"impact_{len(column_by_type) + 1}"
		column_by_type[impact_type] = field
		columns.append(
			column(
				field,
				impact_type or _("Impact type not specified"),
				kind="impact",
				group=_("Impact"),
				group_id="impact",
				width=150,
			)
		)

	rows = []
	for name, request, details in selected:
		row = change_row(name, request)
		by_type = defaultdict(list)
		for detail in details:
			by_type[detail.get("type") or ""].append(detail)
		row["cells"] = {}
		for impact_type, entries in by_type.items():
			field = column_by_type[impact_type]
			levels = [entry.get("level") for entry in entries]
			known = [level for level in levels if level in IMPACT_ORDER]
			level = max(known, key=IMPACT_ORDER.get) if known else None
			unspecified = len(entries) - len(known)
			row["cells"][field] = {
				"level": level,
				"unspecified": unspecified,
				"details": entries,
				"color": IMPACT_COLORS.get(level),
				"tone": IMPACT_TONES.get(level),
			}
			row[field] = impact_caption(level, unspecified)
		rows.append(row)
	return columns, rows


def impact_caption(level, unspecified):
	if not level:
		return _("Level not specified")
	if unspecified:
		return _("{0} · {1} without level").format(_(level), unspecified)
	return _(level)


def impact_relations(requests):
	relations = data.child_rows(
		"Change Relation",
		requests,
		data.CHANGE_REQUEST,
		"change_relations",
		["type", "level", "direction", "explanation", "estimation", "uom", "link_doctype", "link"],
	)
	references = defaultdict(set)
	for entries in relations.values():
		for row in entries:
			if row.get("link_doctype") and row.get("link"):
				references[row["link_doctype"]].add(row["link"])
	projects = {row["project"] for row in requests.values()}
	readable = {}
	for doctype, names in references.items():
		if doctype in CHILD_LINKS:
			# Restrict children to readable Project parents and the canonical grid field.
			readable[doctype] = {
				row["name"]: parent
				for parent, entries in data.child_rows(
					doctype, projects, "Project", CHILD_LINKS[doctype], []
				).items()
				for row in entries
				if row["name"] in names
			}
		elif doctype in PROJECT_LINKS or doctype in {"Account", "Project Role", "Territory", "Goal"}:
			project_link = doctype in PROJECT_LINKS
			link_filters = {"name": ["in", list(names)]}
			if project_link:
				link_filters["project"] = ["in", list(projects)]
			fields = ["name", "project"] if project_link else ["name"]
			readable[doctype] = {
				name: row.get("project")
				for name, row in data.select_rows(doctype, link_filters, fields).items()
			}
	for request, entries in relations.items():
		for row in entries:
			link, doctype = row.get("link"), row.get("link_doctype")
			if not link:
				continue
			allowed = readable.get(doctype, {})
			if link not in allowed or (allowed[link] and allowed[link] != requests[request]["project"]):
				row["link"] = None
				row["link_doctype"] = None
				row["link_unavailable"] = True
			elif doctype in CHILD_LINKS:
				row["link_project"] = allowed[link]
				row["link_parentfield"] = CHILD_LINKS[doctype]
	return relations


def change_impact(filters):
	requests = data.get_requests(data.project_ids(filters.get("project")))
	active_types = frappe.get_all("Project Change Relation Type", filters={"enabled": 1}, pluck="name")
	return impact_matrix(requests, impact_relations(requests), active_types, filters)


def change_columns(*, impact=False):
	columns = [
		column("label", _("Change request"), kind="label", width=280),
		column("project", _("Project"), kind="project", width=150),
		column("status", _("Status"), kind="status"),
		column("initiator", _("Initiator"), width=150),
		column("creation", _("Created on"), kind="datetime", width=170),
	]
	if not impact:
		columns.append(column("implementation_responsible", _("Implementation responsible"), width=170))
	return columns


def change_row(name, request):
	return {
		**request,
		"id": name,
		"label": request.get("title") or name,
		"document_type": data.CHANGE_REQUEST,
		"document": name,
	}


def change_register(filters):
	requests = data.get_requests(data.project_ids(filters.get("project")))
	start, end = date_range(filters)
	return change_columns(), [
		change_row(name, request)
		for name, request in requests.items()
		if matches_change(request, filters, start, end)
	]


def missing_required(assignments, definitions, allowed):
	return [
		{
			"code": code,
			"label": definitions[code].get("responsibility") or code,
			"color": definitions[code].get("color"),
		}
		for code in missing_responsibilities(assignments, allowed, definitions)
	]


def result_columns(*, show_project=False):
	columns = [column("label", _("Deliverable / Work"), kind="label", width=285)]
	if show_project:
		columns.append(column("project", _("Project"), kind="project", width=145))
	columns.extend(
		[
			column("status", _("Status"), kind="status", width=148),
			column("deliverable_type", _("Deliverable type"), width=150),
			column("category", _("Category"), width=148),
			column("progress", _("Progress"), kind="progress", width=86),
			column("accountable", _("Accountable"), kind="accountable", width=180),
			column(
				"planned_end_date",
				_("Planned end", context="Dinext.ProjectScope.Dates"),
				kind="plan_date",
				width=132,
			),
			column(
				"expected_end_date",
				_("Expected end", context="Dinext.ProjectScope.Dates"),
				kind="date",
				width=132,
			),
			column(
				"actual_end_date",
				_("Actual end", context="Dinext.ProjectScope.Dates"),
				kind="date",
				width=132,
			),
		]
	)
	return columns


def deliverable_register(filters):
	deliverables = data.get_deliverables(data.project_ids(filters.get("project")))
	assignments = data.load_assignments(deliverables)
	definitions = data.responsibility_definitions()
	accountable = data.accountables(assignments, definitions, data.participant_names(assignments))
	today = getdate()
	allowed = configured_roles(row.get("category") for row in deliverables.values())
	overdue = cint(filters.get("overdue"))
	missing = cint(filters.get("missing_responsibility"))
	rows = []
	for name, row in deliverables.items():
		lacks = missing_required(assignments.get(name, []), definitions, allowed[row.get("category")])
		if (
			not data.matches(row, filters, data.RESULT_FILTERS)
			or (overdue and not data.is_late(row, today))
			or (missing and (not lacks or row.get("status") == "Cancelled"))
		):
			continue
		rows.append(
			{
				**row,
				"id": name,
				"label": row.get("title") or name,
				"document_type": data.DELIVERABLE,
				"document": name,
				"status_tone": data.result_tone(row, today),
				"accountable": accountable.get(name, []),
				"missing_responsibility": lacks,
			}
		)
	return [
		*result_columns(show_project=True),
		column("missing_responsibility", _("Missing required responsibility"), kind="badges", width=200),
	], sorted(rows, key=data.row_sort_key)


def review_due(row, today):
	return (
		bool(row.get("review_date"))
		and getdate(row["review_date"]) <= today
		and row.get("status") not in {"Cancelled", "Template"}
		and (
			row.get("record_type") != "Assumption"
			or row.get("verification_status") not in {"Confirmed", "Disproved"}
		)
	)


def constraint_register(filters):
	constraints = data.get_constraints(data.project_ids(filters.get("project")))
	today = getdate()
	start, end = date_range(filters, "review_from", "review_to")
	rows = [
		{
			**row,
			"id": name,
			"label": row.get("subject") or name,
			"project": row["parent"],
			"document_type": "Project",
			"document": row["parent"],
			"child_document": name,
			"child_field": "project_constraints",
		}
		for name, row in constraints.items()
		if data.matches(row, filters, CONSTRAINT_FILTERS)
		and is_in_period(row.get("review_date"), start, end)
		and (not cint(filters.get("review_due")) or review_due(row, today))
	]
	columns = [
		column("label", _("Constraint or assumption"), kind="label", width=275),
		column("project", _("Project"), kind="project", width=145),
		column("record_type", _("Record type"), kind="status"),
		column("category", _("Category")),
		column("status", _("Status"), kind="status"),
		column("responsible", _("Responsible"), width=150),
		column("review_date", _("Planned review date"), kind="date"),
		column("verification_status", _("Verification status"), kind="status", width=168),
		column("verification_note", _("Verification Note"), kind="note", width=280),
		column("verified_at", _("Verified At"), kind="datetime", width=190),
	]
	return columns, rows


def overview(filters):
	project = data.project_ids(filters.get("project"), required=True)[0]
	requirements = scope_requirement_rows(project)
	deliverables = data.get_deliverables([project])
	constraints = data.get_constraints([project])
	requests = data.get_requests([project])
	links = requirement_results(deliverables)
	assignments = data.load_assignments(deliverables)
	definitions = data.responsibility_definitions()
	today = getdate()
	metrics = []

	def metric(label, count, report, *, chart=None, chart_name=None, **route_filters):
		metrics.append(
			{
				"id": f"metric-{len(metrics) + 1}",
				"label": label,
				"count": count,
				"route_report": report,
				"route_filters": {"project": project, **route_filters},
				"chart": chart,
				"chart_name": chart_name,
			}
		)

	metric(_("Requirements"), len(requirements), TRACEABILITY)
	metric(
		_("Requirements without deliverables"),
		len(set(requirements) - set(links)),
		TRACEABILITY,
		without_results=1,
	)
	metric(_("Project deliverables"), len(deliverables), DELIVERABLE_REGISTER)
	metric(
		_("Overdue deliverables"),
		sum(data.is_late(row, today) for row in deliverables.values()),
		DELIVERABLE_REGISTER,
		overdue=1,
	)
	allowed = configured_roles(row.get("category") for row in deliverables.values())
	metric(
		_("Deliverables missing required responsibility"),
		sum(
			bool(missing_required(assignments.get(name, ()), definitions, allowed[row.get("category")]))
			for name, row in deliverables.items()
			if row.get("status") != "Cancelled"
		),
		DELIVERABLE_REGISTER,
		missing_responsibility=1,
	)
	metric(
		_("Constraints and assumptions due for review"),
		sum(review_due(row, today) for row in constraints.values()),
		CONSTRAINT_REGISTER,
		review_due=1,
	)
	metric(_("Change requests"), len(requests), CHANGE_REGISTER)
	metrics[0]["progress_deliverable"] = next(iter(deliverables), None)
	for rows, key, chart, report, context in [
		(requirements, "status", "requirement_status", TRACEABILITY, data.REQUIREMENT),
		(requirements, "kind", "requirement_category", TRACEABILITY, None),
		(deliverables, "status", "deliverable_status", DELIVERABLE_REGISTER, data.DELIVERABLE),
		(requests, "status", "change_status", CHANGE_REGISTER, None),
	]:
		for item in data.distribution(rows.values(), key):
			value = item["name"]
			metric(
				_(value, context=context) if value else _("Not specified"),
				item["count"],
				report,
				chart=chart,
				chart_name=value,
				**({key: value} if value else {f"{key}_missing": 1}),
			)
	by_day = Counter(str(getdate(row["creation"])) for row in requests.values() if row.get("creation"))
	for day, count in sorted(by_day.items()):
		metric(day, count, CHANGE_REGISTER, chart="change_dates", chart_name=day, from_date=day, to_date=day)

	return [
		column("label", _("Indicator"), kind="label", width=355),
		column("count", _("Count"), kind="count", width=110),
	], metrics


REPORTS = {
	TRACEABILITY: traceability,
	RESPONSIBILITY: raci,
	IMPACT: change_impact,
	OVERVIEW: overview,
	DELIVERABLE_REGISTER: deliverable_register,
	CONSTRAINT_REGISTER: constraint_register,
	CHANGE_REGISTER: change_register,
}


def dataset(report_name, filters=None):
	if report_name not in REPORTS:
		frappe.throw(_("This report is unavailable."))
	list_fields = ("responsibility",) if report_name == RESPONSIBILITY else ()
	return REPORTS[report_name](data.normalize_filters(filters, list_fields=list_fields))


def execute_report(report_name, filters=None):
	columns, rows = dataset(report_name, filters)
	columns[0]["scope_report"] = report_name
	return columns, rows, None, None, None, True


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def reference_query(doctype, txt, searchfield, start, page_len, filters):
	filters = data.normalize_filters(filters)
	project = filters.get("project")
	context = filters.get("context")
	if context in {"assignment", "requirement"} and not project:
		return []
	projects = data.project_ids(project)
	values = {}
	if context == "assignment" and doctype in {"User", "Contact"}:
		rows = data.load_assignments(data.get_deliverables(projects))
		names = data.participant_names(rows)
		for assignments in rows.values():
			for assignment in assignments:
				kind, name = data.participant(assignment)
				if kind == doctype and name:
					values[name] = names.get((kind, name), name)
	elif context == "impact":
		for entries in impact_relations(data.get_requests(projects)).values():
			for row in entries:
				if row.get("link_doctype") == doctype and row.get("link"):
					values[row["link"]] = row["link"]
	elif doctype in {"User", "Contact"}:
		if context == "requirement":
			rows = scope_requirement_rows(project).values()
			field = "author" if doctype == "Contact" else "responsible"
		elif context == "change":
			rows = data.get_requests(projects).values()
			field = "initiator" if doctype == "Contact" else "implementation_responsible"
		elif context == "constraint":
			rows = [
				row for row in data.get_constraints(projects).values() if data.participant(row)[0] == doctype
			]
			field = "responsible"
		else:
			return []
		matches = {row[field] for row in rows if row.get(field)}
		labels = (
			data.select_rows(doctype, {"name": ["in", sorted(matches)]}, ["name", "full_name"])
			if matches
			else {}
		)
		values = {name: labels.get(name, {}).get("full_name") or name for name in matches}
	query = txt.casefold()
	results = sorted(
		(
			(name, label)
			for name, label in values.items()
			if query in name.casefold() or query in label.casefold()
		),
		key=lambda item: (item[1].casefold(), item[0]),
	)
	return results[start : start + page_len]
