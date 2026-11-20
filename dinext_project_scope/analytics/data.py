from collections import Counter, defaultdict
from datetime import timedelta
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

DELIVERABLE = "Project Deliverable"
REQUIREMENT = "Project Requirement"
CHANGE_REQUEST = "Project Change Request"
CONSTRAINT = "Project Constraint"
RESPONSIBILITY = "Project Deliverable Responsibility"
ACCOUNTABLE_CODE = "\u041e"  # Cyrillic O in the responsibility catalog.
PARTICIPANT_IMAGE_FIELDS = {"User": "user_image", "Contact": "image"}

RESULT_FIELDS = [
	"name",
	"title",
	"project",
	"deliverable_type",
	"category",
	"status",
	"progress",
	"planned_start_date",
	"planned_end_date",
	"expected_end_date",
	"actual_end_date",
	"plan_incomplete",
	"forecast_incomplete",
	"requires_recheck",
]
REQUEST_FIELDS = ["name", "title", "project", "status", "initiator", "creation", "implementation_responsible"]
CONSTRAINT_FIELDS = [
	"subject",
	"record_type",
	"category",
	"status",
	"responsible",
	"responsible_type",
	"review_date",
	"verification_status",
	"verification_note",
	"verified_at",
]
TASK_FIELDS = [
	"name",
	"subject",
	"project",
	"type",
	"status",
	"progress",
	"parent_task",
	"custom_planned_end_date",
	"exp_end_date",
	"completed_on",
	"act_end_date",
]
STATUS_TONES = {
	"Approved": "cyan",
	"In Progress": "blue",
	"Working": "blue",
	"Acceptance": "light-green",
	"Done": "green",
	"Completed": "green",
	"Cancelled": "gray",
}
RESULT_FILTERS = ("status", "deliverable_type", "category")
ONLY_EMPTY = "__dinext_scope_no_value__"


def normalize_filters(filters=None):
	values = frappe.parse_json(filters) or {}
	if not isinstance(values, dict) or any(
		value is not None and not isinstance(value, (str, int, float, bool)) for value in values.values()
	):
		frappe.throw(_("Invalid report filters."))
	return values


def project_ids(project=None, *, required=False):
	from dinext_project_scope.access import check_project, has_project_access, readable_projects

	if project:
		if not isinstance(project, str):
			frappe.throw(_("Select a project."))
		check_project(project)
		return [project]
	if required:
		frappe.throw(_("Select a project."))
	return [name for name in readable_projects() if has_project_access(name)]


def select_rows(doctype, filters, fields, *, order_by="name asc"):
	if not frappe.has_permission(doctype, "read"):
		return {}
	valid_columns = set(frappe.get_meta(doctype).get_valid_columns())
	columns = [field for field in fields if field in valid_columns]
	rows = frappe.get_list(doctype, filters=filters, fields=columns, order_by=order_by, limit_page_length=0)
	return {row.name: row for row in rows}


def child_rows(doctype, parents, parenttype, parentfield, fields):
	if not parents:
		return {}
	valid_columns = set(frappe.get_meta(doctype).get_valid_columns())
	columns = [field for field in ["name", "parent", *fields] if field in valid_columns]
	# Only fetch child rows whose exact parent and table have already passed the caller's read check.
	rows = frappe.get_all(
		doctype,
		filters={"parent": ["in", list(parents)], "parenttype": parenttype, "parentfield": parentfield},
		fields=columns,
		order_by="idx asc, name asc",
	)
	grouped = defaultdict(list)
	for row in rows:
		grouped[row.parent].append(row)
	return grouped


def get_deliverables(projects):
	if not projects:
		return {}
	return select_rows(
		DELIVERABLE, {"project": ["in", projects], "status": ["!=", "Template"]}, RESULT_FIELDS
	)


def get_requests(projects):
	if not projects:
		return {}
	return select_rows(
		CHANGE_REQUEST, {"project": ["in", projects]}, REQUEST_FIELDS, order_by="creation desc, name asc"
	)


def get_constraints(projects):
	grouped = child_rows(CONSTRAINT, projects, "Project", "project_constraints", CONSTRAINT_FIELDS)
	return {row.name: row for rows in grouped.values() for row in rows if row.status != "Template"}


def load_structure(deliverables):
	return child_rows(
		"Project Deliverable Structure",
		deliverables,
		DELIVERABLE,
		"table_xuct",
		["element", "element_name", "element_type", "is_optional"],
	)


def load_assignments(deliverables):
	return child_rows(
		"Project Deliverable Responsible",
		deliverables,
		DELIVERABLE,
		"deliverable_responsibles",
		["project_role", "responsibility", "responsible_type", "responsible"],
	)


def responsibility_definitions():
	# These are public-facing configuration values used for every readable result.
	return {
		row.name: row
		for row in frappe.get_all(
			RESPONSIBILITY, fields=["name", "responsibility", "color", "enabled", "required", "single"]
		)
	}


def _participant_rows(assignments, *, include_images=False):
	values = defaultdict(set)
	for rows in assignments.values():
		for row in rows:
			doctype, name = participant(row)
			if doctype in PARTICIPANT_IMAGE_FIELDS and name:
				values[doctype].add(name)
	participants = {}
	for doctype, names in values.items():
		fields = ["name", "full_name"]
		if include_images:
			fields.append(PARTICIPANT_IMAGE_FIELDS[doctype])
		rows = select_rows(doctype, {"name": ["in", sorted(names)]}, fields)
		participants.update({(doctype, name): row for name, row in rows.items()})
	return participants


def _participant_names(participants):
	return {key: row.get("full_name") or key[1] for key, row in participants.items()}


def participant_names(assignments):
	return _participant_names(_participant_rows(assignments))


def participant(row):
	return row.get("responsible_type") or "User", row.get("responsible")


def matches(row, filters, fields):
	return all(
		(
			not row.get(key)
			if cint(filters.get(f"{key}_missing"))
			else not filters.get(key) or filters[key] == row.get(key)
		)
		for key in fields
	)


def is_late(row, today):
	if not row.get("planned_end_date") or row.get("status") in {"Completed", "Cancelled", "Template"}:
		return False
	end_date = getdate(row["planned_end_date"])
	return bool(end_date and end_date < today)


def result_tone(row, today):
	status = row.get("status")
	if is_late(row, today):
		return "yellow" if status == "Acceptance" else "red"
	return STATUS_TONES.get(status)


def numeric_progress(value):
	return min(100.0, max(0.0, flt(value)))


def root_names(deliverables, structure):
	nested = {
		slot.get("element")
		for name in deliverables
		for slot in structure.get(name, ())
		if slot.get("element_type") == DELIVERABLE
	}
	return set(deliverables) - nested


def root_progress(deliverables, structure):
	eligible = {
		name: row for name, row in deliverables.items() if row.get("status") not in {"Cancelled", "Template"}
	}
	roots = root_names(eligible, structure)
	return {
		"count": len(roots),
		"progress": sum(numeric_progress(eligible[name].get("progress")) for name in roots) / len(roots)
		if roots
		else None,
	}


def row_sort_key(row):
	due = row.get("planned_end_date") or row.get("expected_end_date")
	return (not bool(due), str(due or ""), row.get("label", "").casefold(), row.get("document") or row["id"])


class StructureTree:
	def __init__(self, deliverables, structure, tasks, accountable, today):
		self.deliverables = deliverables
		self.structure = structure
		self.tasks = tasks
		self.accountable = accountable
		self.today = today
		self.task_children = defaultdict(list)
		for name, row in tasks.items():
			self.task_children[row.get("parent_task")].append(name)
		self.encountered = set()

	def deliverable(self, name, row_id=None, ancestors=frozenset()):
		row = self.deliverables[name]
		row_id = row_id or f"result-{quote(name, safe='')}"
		self.encountered.add(name)
		ancestors = ancestors | {name}
		children = [
			self.slot(slot, f"{row_id}/work-{quote(str(slot.get('name') or index), safe='')}", ancestors)
			for index, slot in enumerate(self.structure.get(name, ()), start=1)
		]
		return {
			**row,
			"id": row_id,
			"label": row.get("title") or name,
			"document_type": DELIVERABLE,
			"document": name,
			"accountable": self.accountable.get(name, []),
			"status_tone": result_tone(row, self.today),
			"children": sorted(children, key=row_sort_key),
		}

	def slot(self, slot, row_id, ancestors):
		kind = slot.get("element_type")
		target = slot.get("element")
		label = slot.get("element_name")
		if kind == DELIVERABLE and target in self.deliverables and target not in ancestors:
			row = self.deliverable(target, row_id, ancestors)
			if label and label != row["label"]:
				row["slot_label"] = label
			return row
		if kind == "Task" and target in self.tasks:
			row = self.task(target, row_id)
			if label and label != row["label"]:
				row["slot_label"] = label
			return row
		return {
			"id": row_id,
			"label": label,
			"status_note": "Work is unavailable" if target else "Work is unassigned",
		}

	def task(self, name, row_id, ancestors=frozenset()):
		row = self.tasks[name]
		status = row.get("status")
		ancestors = ancestors | {name}
		children = [
			self.task(child, f"{row_id}/task-{quote(child, safe='')}", ancestors)
			for child in self.task_children.get(name, ())
			if child not in ancestors
		]
		return {
			"id": row_id,
			"label": row.get("subject") or name,
			"document_type": "Task",
			"document": name,
			"deliverable_type": row.get("type"),
			"status": status,
			"status_tone": STATUS_TONES.get(status),
			"progress": row.get("progress"),
			"planned_end_date": row.get("custom_planned_end_date"),
			"expected_end_date": row.get("exp_end_date"),
			"actual_end_date": (row.get("completed_on") or row.get("act_end_date"))
			if status == "Completed"
			else None,
			"children": sorted(children, key=row_sort_key),
		}


def distribution(rows, key):
	counts = Counter(row.get(key) or "" for row in rows)
	return [
		{"name": value, "count": count}
		for value, count in sorted(counts.items(), key=lambda item: item[0].casefold())
	]


def results_view(deliverables, structure, tasks, accountable, filters, today=None):
	today = today or getdate()
	# Compute the filtered document set once; a document may appear in more than one branch.
	matching = {
		name: row
		for name, row in deliverables.items()
		if matches(row, filters, RESULT_FILTERS) and (not cint(filters.get("overdue")) or is_late(row, today))
	}
	tree = StructureTree(deliverables, structure, tasks, accountable, today)
	roots = [tree.deliverable(name) for name in sorted(root_names(deliverables, structure))]
	# A historical cycle may have no root. Its reads stay available without following the loop.
	for name in deliverables:
		if name not in tree.encountered:
			roots.append(tree.deliverable(name))

	def retain_branch(row, *, keep_work=False):
		if row.get("document_type") != DELIVERABLE:
			return row if keep_work else None
		selected = row["document"] in matching
		children = [
			visible
			for child in row["children"]
			if (visible := retain_branch(child, keep_work=selected)) is not None
		]
		if selected or children:
			return {**row, "context_only": not selected, "children": children}
		return None

	filtered = [branch for row in roots if (branch := retain_branch(row)) is not None]
	return sorted(filtered, key=row_sort_key), {
		key: distribution(matching.values(), key) for key in RESULT_FILTERS
	}


def progress_series(deliverable, events, today=None):
	today = today or getdate()
	actual = []
	for event in events:
		if not event.get("log_date") or event.get("progress") is None:
			continue
		progress = numeric_progress(event["progress"])
		# Date changes can create journal entries without changing recorded progress.
		if not actual or actual[-1][1] != progress:
			actual.append([str(event["log_date"]).replace(" ", "T"), progress])
	start = deliverable.get("planned_start_date")
	end = deliverable.get("planned_end_date")
	result = {
		"planned": [],
		"actual": actual,
		"plan_step": False,
		"plan_reason": None,
		"plan_incomplete": bool(cint(deliverable.get("plan_incomplete"))),
	}
	if not start or not end:
		result["plan_reason"] = "missing"
		return result
	start, end = getdate(start), getdate(end)
	if not start or not end or end < start:
		result["plan_reason"] = "invalid"
		return result
	timeline = [str(today), *(point[0] for point in actual)]
	before, after = min(timeline), max(timeline)
	if start == end:
		# A single-day plan reaches 100% at the start of that day.
		result["plan_step"] = True
		result["planned"].append([min(before, str(start - timedelta(days=1))), 0])
		result["planned"].append([str(start), 100])
	else:
		if before < str(start):
			result["planned"].append([before, 0])
		result["planned"].extend([[str(start), 0], [str(end), 100]])
	if after > str(end):
		result["planned"].append([after, 100])
	return result


def accountables(assignments, definitions, names):
	if not definitions.get(ACCOUNTABLE_CODE, {}).get("enabled"):
		return {}
	values = {}
	for name, rows in assignments.items():
		members = {
			participant(row)
			for row in rows
			if row.get("responsibility") == ACCOUNTABLE_CODE and row.get("responsible")
		}
		values[name] = [
			{"doctype": doctype, "name": member, "label": names.get((doctype, member), member)}
			for doctype, member in sorted(members)
		]
	return values


def available_tasks(project, structure):
	if not any(
		slot.get("element_type") == "Task" and slot.get("element")
		for slots in structure.values()
		for slot in slots
	):
		return {}
	return select_rows("Task", {"project": project, "status": ["!=", "Template"]}, TASK_FIELDS)


@frappe.whitelist(methods=["GET"])
def project_results(project, filters=None):
	filters = normalize_filters(filters)
	projects = project_ids(project, required=True)
	deliverables = get_deliverables(projects)
	type_names = sorted(
		{row["deliverable_type"] for row in deliverables.values() if row.get("deliverable_type")}
	)
	types = (
		select_rows("Project Deliverable Type", {"name": ["in", type_names]}, ["name", "icon", "color"])
		if type_names
		else {}
	)
	for row in deliverables.values():
		deliverable_type = types.get(row.get("deliverable_type"), {})
		row["deliverable_type_icon"] = deliverable_type.get("icon") or None
		row["deliverable_type_color"] = deliverable_type.get("color") or None
	structure = load_structure(deliverables)
	assignments = load_assignments(deliverables)
	participants = _participant_rows(assignments, include_images=True)
	accountable = accountables(assignments, responsibility_definitions(), _participant_names(participants))
	for members in accountable.values():
		for member in members:
			doctype = member["doctype"]
			profile = participants.get((doctype, member["name"]), {})
			member["image"] = profile.get(PARTICIPANT_IMAGE_FIELDS.get(doctype)) or None
	filters = {
		(f"{key}_missing" if value == ONLY_EMPTY else key): (1 if value == ONLY_EMPTY else value)
		for key, value in filters.items()
	}
	rows, counts = results_view(
		deliverables, structure, available_tasks(project, structure), accountable, filters
	)
	return {
		"rows": rows,
		"counts": counts,
		"options": {key: distribution(deliverables.values(), key) for key in RESULT_FILTERS},
		"progress": root_progress(deliverables, structure),
	}


@frappe.whitelist(methods=["GET"])
def project_progress(project):
	projects = project_ids(project, required=True)
	deliverables = get_deliverables(projects)
	return root_progress(deliverables, load_structure(deliverables))


@frappe.whitelist(methods=["GET"])
def deliverable_progress(deliverable):
	from dinext_project_scope.access import check_document

	if not isinstance(deliverable, str) or not deliverable:
		frappe.throw(_("Select a deliverable."))
	row = check_document(DELIVERABLE, deliverable)
	# The journal is server-owned. Expose only this readable result's recorded progress, without journal metadata.
	history = frappe.get_all(
		"Project Deliverable Log",
		filters={"deliverable": deliverable},
		fields=["log_date", "progress"],
		order_by="log_date asc, creation asc, name asc",
	)
	return progress_series(row, history)
