"""Save and recalculate project deliverables under their project lock."""

from collections import defaultdict

import frappe
from erpnext.projects.doctype.task.task import Task
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, now_datetime

from dinext_project_scope import access
from dinext_project_scope import deliverable_structure as structure
from dinext_project_scope.deliverable_calculations import (
	DATE_FIELDS,
	DELIVERABLE,
	PROJECTION_FIELDS,
	calculate,
	canonical_json,
	work_blockers,
	work_digest,
)
from dinext_project_scope.deliverable_responsibility import (
	CATEGORY,
	assignment_key,
	category_suggestions,
	current_members,
	default_assignments,
	missing_responsibilities,
	validate_assignments,
)

LOG = "Project Deliverable Log"
TASK_FIELDS = (
	"status",
	"progress",
	"custom_planned_start_date",
	"custom_planned_end_date",
	"exp_end_date",
	"completed_on",
	"act_end_date",
)
RESULT_FIELDS = ("name", "project", "status", "last_acceptance_log", *PROJECTION_FIELDS)
WORK_FIELDS = ("status", *PROJECTION_FIELDS)


def lock_source_projects(doc, additional_project=None):
	"""Acquire aggregate locks before Frappe locks the previous source row."""
	prior_project = None if doc.is_new() else frappe.db.get_value(doc.doctype, doc.name, "project")
	for project in sorted(
		{project for project in (doc.project, prior_project, additional_project) if project}
	):
		access.lock_project(project)


class DeliverableTask(Task):
	def load_doc_before_save(self, *, raise_exception=False):
		# ERPNext fills in Project from the parent Task during validation.
		parent_project = (
			frappe.db.get_value("Task", self.parent_task, "project")
			if not self.project and self.parent_task
			else None
		)
		lock_source_projects(self, parent_project)
		return super().load_doc_before_save(raise_exception=raise_exception)


def before_task_change(doc, method=None):
	structure.validate_referenced_work(doc, doc.get_doc_before_save())


def on_task_change(doc, method=None):
	if (
		getattr(frappe.flags, "in_migrate", False)
		or not doc.project
		or (method == "on_change" and doc.flags.in_delete)
	):
		return
	access.lock_project(doc.project)
	parents = _linked_results(structure.TASK, doc.name, doc.project)
	if parents:
		_recalculate(doc.project, parents, (structure.TASK, doc.name))


def _linked_results(doctype, name, project):
	row = frappe.qb.DocType(structure.STRUCTURE)
	parent = frappe.qb.DocType(DELIVERABLE)
	rows = (
		frappe.qb.from_(row)
		.inner_join(parent)
		.on(row.parent == parent.name)
		.select(row.parent)
		.where(
			(row.parenttype == DELIVERABLE)
			& (row.parentfield == "table_xuct")
			& (row.element_type == doctype)
			& (row.element == name)
			& (parent.project == project)
			& (parent.status != "Template")
		)
		.for_update()
		.run()
	)
	return {name for (name,) in rows}


def _select_rows(doctype, fields, filters, *, current):
	table = frappe.qb.DocType(doctype)
	query = frappe.qb.from_(table).select(*(table[field] for field in fields))
	for field, value in filters.items():
		query = query.where(
			table[field].isin(value) if isinstance(value, (list, set, tuple)) else table[field] == value
		)
	if current:
		query = query.for_update()
	return query.run(as_dict=True)


def _iso_date(value):
	return getdate(value).isoformat() if value else None


def _task_state(task):
	return {
		"status": task.status,
		"progress": flt(task.progress),
		"planned_start_date": _iso_date(task.custom_planned_start_date),
		"planned_end_date": _iso_date(task.custom_planned_end_date),
		"expected_end_date": _iso_date(task.exp_end_date),
		"actual_end_date": _iso_date(task.completed_on or task.act_end_date)
		if task.status == "Completed"
		else None,
	}


class ProjectWork:
	def __init__(self, project, *, current=False, draft=None):
		self.project = project
		self.current = current
		rows = (
			_select_rows(DELIVERABLE, RESULT_FIELDS, {"project": project}, current=current) if project else []
		)
		self.results = {row.name: row for row in rows if row.status != "Template"}
		self.slots = defaultdict(list)
		if self.results:
			for row in sorted(
				_select_rows(
					structure.STRUCTURE,
					("parent", "name", "idx", *structure.SOURCE_FIELDS, "weight", "element"),
					{"parent": list(self.results), "parenttype": DELIVERABLE, "parentfield": "table_xuct"},
					current=current,
				),
				key=lambda row: (row.parent, row.idx),
			):
				self.slots[row.parent].append(row)
		if draft is not None:
			self.results[draft.name] = draft
			self.slots[draft.name] = draft.table_xuct

		self.children = {}
		self.parents = defaultdict(set)
		for name in self.results:
			children = {
				row.element
				for row in self.slots[name]
				if row.element_type == DELIVERABLE and row.element in self.results
			}
			self.children[name] = sorted(children)
			for child in children:
				self.parents[child].add(name)

	def ancestors(self, names):
		result = set()
		pending = list(names)
		while pending:
			name = pending.pop()
			if name in result:
				continue
			result.add(name)
			pending.extend(self.parents[name])
		return result & self.results.keys()

	def evaluate(self, names, *, acceptance=None):
		pending = list(names)
		dependencies = {}
		while pending:
			name = pending.pop()
			if name in dependencies:
				continue
			dependencies[name] = self.children[name]
			pending.extend(self.children[name])
		order = structure.child_first_order(dependencies)
		task_names = {
			row.element
			for name in order
			for row in self.slots[name]
			if row.element and row.element_type == structure.TASK
		}
		task_rows = (
			_select_rows(
				structure.TASK,
				("name", *TASK_FIELDS),
				{"name": list(task_names), "project": self.project},
				current=self.current,
			)
			if task_names
			else []
		)
		tasks = {row.name: _task_state(row) for row in task_rows if row.status != "Template"}
		log_ids = [
			self.results[name].last_acceptance_log for name in order if self.results[name].last_acceptance_log
		]
		previous_acceptances = (
			_select_rows(LOG, ("name", "log_date", "work_digest"), {"name": log_ids}, current=self.current)
			if log_ids
			else []
		)
		accepted = {row.name: row for row in previous_acceptances}

		states = {}
		for name in order:
			row = self.results[name]
			work = self._work_rows(name, tasks, states)
			snapshot = [{**item, "state": state} for item, state in work]
			digest = work_digest(snapshot)
			prior = accepted.get(row.last_acceptance_log)
			decision_date = (acceptance or {}).get(name)
			values = calculate(row.status, work, _iso_date(decision_date or (prior and prior.log_date)))
			values["requires_recheck"] = int(
				bool(
					row.status == "Completed" and prior and not decision_date and prior.work_digest != digest
				)
			)
			states[name] = {
				"status": row.status,
				**values,
				"work_digest": digest,
				"work": work,
				"snapshot": snapshot,
				"accepted_at": decision_date or (prior and prior.log_date),
			}
		return states

	def _work_rows(self, name, tasks, states):
		rows = []
		for item in structure.snapshot(self.slots[name]):
			link = item["element"]
			if item["element_type"] == DELIVERABLE and link in states:
				state = {key: states[link][key] for key in (*WORK_FIELDS, "work_digest")}
			else:
				state = tasks.get(link) if item["element_type"] == structure.TASK else None
			rows.append((item, state))
		return rows


def _fields(row):
	return {
		"progress": flt(row.get("progress")),
		**{field: _iso_date(row.get(field)) for field in DATE_FIELDS},
		**{
			field: cint(row.get(field))
			for field in ("plan_incomplete", "forecast_incomplete", "requires_recheck")
		},
		"status": row.get("status"),
	}


def _latest_logs(name):
	return frappe.db.get_value(
		LOG,
		{"deliverable": name},
		["name", "work_digest"],
		order_by="creation desc, name desc",
		as_dict=True,
		for_update=True,
	)


def _append_log(name, state, before, source, event_type, latest, *, decision=None, previous_structure=None):
	current = {field: state[field] for field in ("status", "progress", *DATE_FIELDS)}
	previous = _fields(before) if before else {}
	snapshot = {"works": state["snapshot"], "calculation": _fields(state)}
	if previous_structure is not None:
		snapshot["previous_works"] = previous_structure
	decision = decision or {}
	event_source = ("Workflow Task", decision["task"]) if decision.get("task") else source
	event_key = work_digest(
		[name, latest and latest.name, event_type, *event_source, state["work_digest"], current]
	)
	doc = frappe.get_doc(
		{
			"doctype": LOG,
			"deliverable": name,
			"log_date": decision.get("timestamp") or now_datetime(),
			"author": frappe.session.user,
			"event_type": event_type,
			"event_key": event_key,
			"source": event_source[0],
			"source_name": event_source[1],
			"workflow_process": decision.get("process"),
			"workflow_task": decision.get("task"),
			"decision_note": decision.get("note"),
			**current,
			**{f"previous_{field}": previous.get(field) for field in current},
			"work_digest": state["work_digest"],
			"work_snapshot": canonical_json(snapshot),
		}
	)
	doc.flags.in_deliverable_calculation = True
	return doc.insert(ignore_permissions=True)


def _recalculate(project, seeds, source, *, saved=None):
	graph = ProjectWork(project, current=True)
	targets = graph.results.keys() if seeds is None else graph.ancestors(seeds)
	decision = saved.flags.acceptance_decision if saved else None
	acceptance = (
		{saved.name: decision["timestamp"]}
		if decision and decision["event_type"] in ("Accepted", "Reconfirmed")
		else None
	)
	states = graph.evaluate(targets, acceptance=acceptance)
	updates = 0
	reopened_routes = []
	for name, state in states.items():
		if name not in targets:
			continue
		stored = graph.results[name]
		edited = saved if saved and saved.name == name else None
		before = edited.get_doc_before_save() if edited else stored
		fields = _fields(state)
		latest = _latest_logs(name)
		old_structure = structure.snapshot(before.table_xuct) if edited and before else None
		structure_changed = old_structure is not None and old_structure != structure.snapshot(
			edited.table_xuct
		)
		active_decision = decision if edited else None
		if active_decision:
			event_type = active_decision["event_type"]
		elif structure_changed:
			event_type = "Structure Changed"
		elif before and before.get("status") != state["status"]:
			event_type = "Status Changed"
		elif fields != _fields(before or {}) or not latest or latest.work_digest != state["work_digest"]:
			event_type = "Calculation"
		else:
			continue
		log = _append_log(
			name,
			state,
			before,
			source,
			event_type,
			latest,
			decision=active_decision,
			previous_structure=old_structure if structure_changed else None,
		)
		old_fields = _fields(stored)
		values = {field: state[field] for field in PROJECTION_FIELDS if fields[field] != old_fields[field]}
		if active_decision and event_type in ("Accepted", "Reconfirmed"):
			values["last_acceptance_log"] = log.name
		if values:
			frappe.db.set_value(DELIVERABLE, name, values, update_modified=False)
			if edited:
				edited.update(values)
			elif "requires_recheck" in values:
				reopened_routes.append(name)
		updates += 1
	if reopened_routes:
		from dinext_project_scope.deliverable_workflow import reconcile_after_calculation

		for name in reopened_routes:
			reconcile_after_calculation(name)
	return updates


def validate_deliverable(doc):
	from dinext_project_scope import deliverable_workflow

	before = doc.get_doc_before_save()
	doc.title = cstr(doc.title).strip()
	doc.status = doc.status or "Not Started"
	if before and before.project != doc.project:
		frappe.throw(_("The project of an existing result cannot be changed."))
	if doc.status != "Template":
		access.check_project(doc.project)
	if not before or doc.category != before.category:
		access.check_document(CATEGORY, doc.category)
		if not frappe.db.get_value(CATEGORY, doc.category, "enabled"):
			frappe.throw(_("Choose an active result category."))

	structure.validate_saved_structure(doc, before)
	structure.validate_links(doc, before)
	structure.validate_work_links(doc, before)
	structure.validate_referenced_work(doc, before)
	missing = validate_assignments(doc, before)
	doc.last_acceptance_log = before.last_acceptance_log if before else None
	graph = ProjectWork(doc.project, current=True, draft=doc)
	state = graph.evaluate({doc.name})[doc.name]
	deliverable_workflow.validate_save(doc, before, state, missing)
	if doc.flags.acceptance_decision and doc.flags.acceptance_decision["event_type"] in (
		"Accepted",
		"Reconfirmed",
	):
		state = graph.evaluate({doc.name}, acceptance={doc.name: doc.flags.acceptance_decision["timestamp"]})[
			doc.name
		]
	doc.update({field: state[field] for field in PROJECTION_FIELDS})


def on_deliverable_update(doc):
	if doc.project and doc.status != "Template":
		source = doc.flags.structural_source or (DELIVERABLE, doc.name)
		_recalculate(doc.project, {doc.name}, source, saved=doc)


@frappe.whitelist(methods=["POST"])
def delete_project_results(project: str, results):
	names = frappe.parse_json(results)
	if (
		not isinstance(names, list)
		or not names
		or any(not isinstance(name, str) or not name for name in names)
	):
		frappe.throw(_("Select at least one project result to delete."))
	access.check_project(project, "write")
	access.lock_project(project)
	selected = {}
	for name in dict.fromkeys(names):
		if not frappe.db.exists(
			DELIVERABLE, {"name": name, "project": project, "status": ("!=", "Template")}
		):
			frappe.throw(_("Select results from the current project."))
		selected[name] = access.check_document(DELIVERABLE, name, "delete")

	dependencies = {
		name: [
			slot.element
			for slot in doc.table_xuct
			if structure.element_doctype(slot) == DELIVERABLE and slot.element in selected
		]
		for name, doc in selected.items()
	}
	# A selected parent must be deleted before its selected children.
	deleted = list(reversed(structure.child_first_order(dependencies)))
	savepoint = f"delete_scope_results_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		for name in deleted:
			if selected[name].last_acceptance_log:
				frappe.db.set_value(DELIVERABLE, name, "last_acceptance_log", None, update_modified=False)
			for log in frappe.get_all(LOG, filters={"deliverable": name}, pluck="name"):
				# The immutable journal follows its parent into Frappe's Deleted Document.
				frappe.delete_doc(LOG, log, ignore_permissions=True, ignore_on_trash=True)
			frappe.delete_doc(DELIVERABLE, name)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	frappe.db.release_savepoint(savepoint)
	return deleted


@frappe.whitelist(methods=["POST"])
def rebuild_project(project: str):
	access.check_project(project, "write")
	access.lock_project(project)
	return {"updated": _recalculate(project, None, ("Project", project))}


@frappe.whitelist()
def preview_structure(deliverable: str, deliverable_type: str | None = None):
	doc = access.check_document(DELIVERABLE, deliverable, "write")
	target_type = deliverable_type or doc.deliverable_type
	rows, changes = structure.reconcile(doc, target_type)
	return {
		"deliverable_type": target_type,
		"changes": changes,
		"token": work_digest([doc.name, cstr(doc.modified), target_type, rows]),
	}


@frappe.whitelist(methods=["POST"])
def apply_structure(deliverable: str, deliverable_type: str, token: str):
	doc = access.check_document(DELIVERABLE, deliverable, "write")
	if doc.project:
		access.lock_project(doc.project)
	doc = frappe.get_doc(DELIVERABLE, doc.name, for_update=True)
	doc.check_permission("write")
	rows, _changes = structure.reconcile(doc, deliverable_type, current=True)
	if token != work_digest([doc.name, cstr(doc.modified), deliverable_type, rows]):
		frappe.throw(_("The result or result type changed. Preview the structure again."))
	doc.flags.structure_refresh = True
	doc.flags.structural_source = (structure.TYPE, deliverable_type)
	doc.deliverable_type = deliverable_type
	doc.set("table_xuct", rows)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def new_result_defaults(project: str, deliverable_type: str | None = None, category: str | None = None):
	access.check_project(project)
	if not frappe.has_permission(DELIVERABLE, "create"):
		frappe.throw(_("You cannot create project results."), frappe.PermissionError)
	rows = structure.from_type(deliverable_type) if deliverable_type else []
	if category:
		access.check_document(CATEGORY, category)
	responsibilities = category_suggestions(project, category)
	return {
		"work": rows,
		"responsibilities": responsibilities,
		"defaults": default_assignments(responsibilities),
	}


@frappe.whitelist()
def get_deliverable_details(deliverable: str):
	from dinext_project_scope import deliverable_workflow

	doc = access.check_document(DELIVERABLE, deliverable)
	if doc.status == "Template":
		return {}
	graph = ProjectWork(doc.project)
	state = graph.evaluate({doc.name})[doc.name]
	members = current_members(doc.project)
	stale = [row.name for row in doc.deliverable_responsibles if assignment_key(row)[1:] not in members]
	return {
		"blocked_work": work_blockers(state["work"]),
		"missing_responsibilities": missing_responsibilities(doc.deliverable_responsibles, members),
		"accepted_at": state["accepted_at"],
		"zero_weight": state["zero_weight"],
		"stale_assignments": stale,
		"missing_approver": deliverable_workflow.manager_missing(doc),
		"work": [
			{"key": item["source_element_key"], **{field: work.get(field) for field in WORK_FIELDS}}
			for item, work in state["work"]
			if work and frappe.has_permission(item["element_type"], doc=item["element"], ptype="read")
		],
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def work_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe.parse_json(filters) or {}
	project = filters.get("project")
	other = filters.get("element_type") == structure.OTHER
	if not project or (not other and doctype not in structure.WORK_TYPES):
		return []
	access.check_project(project)
	if other:
		meta = structure.other_work_meta(doctype) if doctype == filters.get("filter_type") else None
		if not meta:
			return []
		title = meta.title_field or "name"
		query = structure.other_work_filters(meta, project)
	else:
		title = "subject" if doctype == structure.TASK else "title"
		query = {"project": project, "status": ("!=", "Template")}
		if filters.get("filter_type"):
			query[structure.WORK_TYPES[doctype][1]] = filters["filter_type"]
	if not other and doctype == DELIVERABLE and filters.get("deliverable"):
		doc = access.check_document(DELIVERABLE, filters["deliverable"])
		if doc.project != project:
			return []
		excluded = ProjectWork(project).ancestors({doc.name})
		if excluded:
			query["name"] = ("not in", sorted(excluded))
	return frappe.get_list(
		doctype,
		filters=query,
		or_filters={"name": ("like", f"%{txt}%"), title: ("like", f"%{txt}%")},
		fields=list(dict.fromkeys(("name", title))),
		start=cint(start),
		page_length=cint(page_len),
		as_list=True,
		order_by="name asc",
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def participant_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe.parse_json(filters) or {}
	project, role = filters.get("project"), filters.get("project_role")
	if not project or not role or doctype not in ("User", "Contact"):
		return []
	access.check_project(project)
	names = sorted(
		name
		for member_role, kind, name in current_members(project)
		if member_role == role and kind == doctype
	)
	if not names:
		return []
	return frappe.get_list(
		doctype,
		filters={"name": ("in", names)},
		or_filters={"name": ("like", f"%{txt}%"), "full_name": ("like", f"%{txt}%")},
		fields=["name", "full_name"],
		start=cint(start),
		page_length=cint(page_len),
		as_list=True,
		order_by="full_name asc, name asc",
	)
