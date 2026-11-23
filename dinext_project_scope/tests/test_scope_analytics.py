import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe
from openpyxl import load_workbook

from dinext_project_scope import requirements
from dinext_project_scope.analytics import data, export, reports
from dinext_project_scope.dinext_project_scope.doctype.project_deliverable_type.project_deliverable_type import (
	ProjectDeliverableType,
)


class TestScopeAnalytics(TestCase):
	def test_results_use_recorded_progress_and_relative_plan_tolerance(self):
		reporting = date(2026, 11, 15)
		baseline = date(2026, 11, 12)
		today = date(2026, 11, 21)
		task = {
			"document_type": "Task",
			"document": "task",
			"progress": 95,
			"planned_start_date": "2026-11-10",
			"planned_end_date": "2026-11-20",
		}
		other = {"document_type": "Note", "document": "other", "is_other": True}
		result = dict(task, document_type=data.DELIVERABLE, document="result", children=[task, other])
		with patch.object(data, "result_progress_history", return_value={
			(data.DELIVERABLE, "result"): [(baseline, 25), (reporting, 48), (reporting, 52.5)],
			("Task", "task"): [(reporting, 46)],
		}) as history:
			data.add_result_progress([result], reporting, baseline, True, today)
		history.assert_called_once_with({data.DELIVERABLE: {"result"}, "Task": {"task"}}, reporting)
		self.assertEqual(result["progress"], 52.5)
		self.assertEqual(result["baseline_progress"], 25)
		self.assertEqual((result["baseline_delta"], result["baseline_delta_direction"]), (27.5, "up"))
		self.assertEqual(result["planned_progress"], 50)
		self.assertEqual((result["plan_delta"], result["plan_delta_direction"]), (2.5, "flat"))
		self.assertEqual((task["plan_delta"], task["plan_delta_direction"]), (-4, "down"))
		self.assertIsNone(task["baseline_delta"])
		self.assertNotIn("progress", other)

	def test_progress_dates_validate_and_keep_current_progress(self):
		today = date(2026, 11, 21)
		with patch.object(data, "result_progress_history") as history:
			row = {"document_type": data.DELIVERABLE, "document": "result", "progress": 41}
			data.add_result_progress([row], today, None, True, today)
			self.assertEqual(row["progress"], 41)
			self.assertIsNone(row["planned_progress"])
			data.add_result_progress([row], date(2026, 11, 22), None, False, today)
			self.assertIsNone(row["progress"])
		history.assert_not_called()
		for invalid in ("2026-11-21 08:00", "2026-15-12", {"date": "2026-11-18"}):
			with self.assertRaises(frappe.ValidationError):
				data.result_progress_dates(invalid, None, today)
		with self.assertRaises(frappe.ValidationError):
			data.result_progress_dates("2026-11-18", "2026-11-19", today)

	@patch.object(export, "_", lambda string, **_: string)
	def test_results_workbook_exports_visible_progress_columns_and_hierarchy(self):
		with (
			patch.object(export.frappe, "has_permission") as permission,
			patch.object(data, "project_results", return_value={
				"comparison": {"show_plan": True, "baseline_date": "2026-11-12"},
				"rows": [{"label": "Parent", "progress": 54, "baseline_progress": 25,
					"baseline_delta": 29, "baseline_delta_direction": "up", "planned_progress": 50,
					"plan_delta": 4, "plan_delta_direction": "up",
					"children": [{"label": "=Child", "progress": 20}]}],
			}) as payload,
			patch.object(export, "provide_binary_file") as delivery,
		):
			export.download_project_results("Project", "{}", "2026-11-15", "2026-11-12", 1)
		permission.assert_called_once_with(data.DELIVERABLE, "export", throw=True)
		payload.assert_called_once_with("Project", "{}", "2026-11-15", "2026-11-12", 1)
		name, extension, content = delivery.call_args.args
		self.assertEqual((name, extension), ("project-results", "xlsx"))
		sheet = load_workbook(BytesIO(content)).active
		self.assertEqual(
			[cell.value for cell in sheet[1][4:9]],
			["Baseline progress", "Progress", "Planned progress", "Δ from baseline", "Δ from plan"],
		)
		headers = {cell.value: cell.column for cell in sheet[1]}
		self.assertEqual(sheet.cell(2, headers["Progress"]).value, 0.54)
		self.assertEqual(sheet.cell(2, headers["Δ from baseline"]).value, 29)
		self.assertEqual(sheet.cell(2, headers["Δ from plan"]).value, 4)
		self.assertEqual(sheet["A3"].data_type, "s")
		self.assertEqual(sheet.row_dimensions[3].outlineLevel, 1)

	@patch("dinext_project_scope.access.has_project_access", side_effect=lambda project: project == "public")
	@patch("dinext_project_scope.access.readable_projects", return_value=["public", "private"])
	def test_cross_project_scope_checks_each_project(self, _listed, _accessible):
		self.assertEqual(data.project_ids(), ["public"])

	@patch.object(data, "child_rows", return_value={})
	def test_constraint_register_selects_titles_from_canonical_project_table(self, child_rows):
		data.get_constraints(["p1"])
		assert child_rows.call_args.args[:4] == (
			"Project Constraint",
			["p1"],
			"Project",
			"project_constraints",
		)
		self.assertIn("subject", child_rows.call_args.args[4])
		self.assertIn("verification_note", child_rows.call_args.args[4])
		self.assertIn("verified_at", child_rows.call_args.args[4])

	@patch.object(export, "_", lambda string, **_: string)
	@patch.object(reports, "_", lambda string: string)
	def test_constraint_register_exports_actual_verification_separately_from_plan(self):
		planned = date(2026, 11, 29)
		verified = datetime(2026, 11, 20, 10, 30)
		note = "Confirmed against the supplier calendar."
		assumption = {
			"parent": "p1",
			"subject": "Supplier capacity",
			"record_type": "Assumption",
			"review_date": planned,
			"verification_status": "Confirmed",
			"verification_note": note,
			"verified_at": verified,
		}
		with (
			patch.object(data, "project_ids", return_value=["p1"]),
			patch.object(data, "get_constraints", return_value={"assumption": assumption}),
			patch.object(reports, "getdate", return_value=date(2026, 11, 20)),
		):
			columns, rows = reports.constraint_register({"project": "p1", "verification_status": "Confirmed"})

		by_field = {column["fieldname"]: column for column in columns}
		self.assertEqual(by_field["review_date"]["label"], "Planned review date")
		self.assertEqual(by_field["verification_note"]["label"], "Verification Note")
		self.assertEqual(by_field["verification_note"]["kind"], "note")
		self.assertEqual(by_field["verified_at"]["fieldtype"], "Datetime")
		self.assertEqual(rows[0]["verification_note"], note)
		self.assertEqual(rows[0]["verified_at"], verified)
		book = load_workbook(BytesIO(export.make_workbook(reports.CONSTRAINT_REGISTER, columns, rows)))
		headers, values = book.active.values
		exported = dict(zip(headers, values, strict=True))
		self.assertEqual(exported["Planned review date"], datetime.combine(planned, datetime.min.time()))
		self.assertEqual(exported["Verification Note"], note)
		self.assertEqual(exported["Verified At"], verified)

	@patch.object(reports, "_", lambda string, **_: string)
	def test_detached_specification_filters_current_requirements_keeps_their_ancestors(self):
		member = frappe._dict(requirement_title="In scope", status="New", parent_project_requirement="parent")
		project_graph = requirements.Composition(
			requirements={
				"parent": frappe._dict(requirement_title="Parent", status="New"),
				"member": member,
				"other": frappe._dict(requirement_title="Other", status="New"),
			},
			paths={"parent": [[]], "member": [[], ["connected"]], "other": [[]]},
		)
		selected = frappe._dict(name="detached", project="p1", doctype=requirements.SPECIFICATION)
		selected_graph = requirements.Composition(
			requirements={
				"member": member,
				"outside": frappe._dict(requirement_title="Outside current scope", status="New"),
			},
			paths={"member": [["detached", "nested"]], "outside": [["detached"]]},
		)
		with (
			patch.object(requirements, "_project_composition", return_value=project_graph),
			patch.object(requirements.access, "check_document", return_value=selected) as read_specification,
			patch.object(requirements, "specification_graph", return_value=selected_graph) as resolve,
			patch(
				"dinext_project_scope.requirement_approval.requirement_states",
				return_value={name: "Draft" for name in project_graph.requirements},
			),
			patch.object(data, "project_ids", return_value=["p1"]),
			patch.object(data, "get_deliverables", return_value={}),
			patch.object(data, "load_structure", return_value={}),
			patch.object(data, "available_tasks", return_value={}),
			patch.object(reports, "getdate", return_value=date(2026, 11, 20)),
		):
			_, rows = reports.traceability({"project": "p1", "specification": "detached"})

		self.assertEqual(
			[(row["document"], row["context_only"]) for row in rows], [("parent", True), ("member", False)]
		)
		read_specification.assert_called_once_with(requirements.SPECIFICATION, "detached")
		resolve.assert_called_once_with(selected, mode="visible")

	def test_project_tree_keeps_only_matching_sources_when_filtering_by_specification(self):
		member = frappe._dict(requirement_title="In scope", status="New")
		graph = requirements.Composition(
			requirements={"member": member, "other": frappe._dict(requirement_title="Other", status="New")},
			paths={"member": [[], ["selected"], ["outer", "selected"]], "other": [[]]},
		)
		with (
			patch.object(requirements, "_project_composition", return_value=graph),
			patch(
				"dinext_project_scope.requirement_approval.requirement_states",
				return_value={"member": "Draft"},
			),
		):
			rows = requirements.project_rows("p1", "selected")

		self.assertEqual([row["name"] for row in rows], ["member"])
		self.assertEqual(rows[0]["paths"], [["selected"], ["outer", "selected"]])

	def test_root_progress_weights_results_equally(self):
		deliverables = {
			"parent-a": {"progress": 20},
			"parent-b": {"progress": 80},
			"shared": {"progress": 99},
			"cancelled": {"status": "Cancelled", "progress": 80},
			"template": {"status": "Template", "progress": 0},
		}
		structure = {
			"parent-a": [{"element_type": "Project Deliverable", "element": "shared"}],
			"parent-b": [{"element_type": "Project Deliverable", "element": "shared"}],
			"cancelled": [{"element_type": "Project Deliverable", "element": "parent-a"}],
		}
		self.assertEqual(data.root_progress(deliverables, structure), {"count": 2, "progress": 50})
		self.assertEqual(
			data.root_progress({"template": deliverables["template"]}, {}), {"count": 0, "progress": None}
		)

	def test_root_plan_averages_linear_progress_of_the_same_results_as_fact(self):
		today = date(2026, 11, 10)
		deliverables = {
			"dated": {"progress": 20, "planned_start_date": "2026-11-06", "planned_end_date": "2026-11-14"},
			"milestone": {
				"progress": 40,
				"planned_start_date": "2026-11-10",
				"planned_end_date": "2026-11-10",
			},
			"future": {"progress": 60, "planned_start_date": "2026-11-11", "planned_end_date": "2026-11-15"},
			"nested": {"progress": 90},
			"cancelled": {"status": "Cancelled", "progress": 100},
		}
		structure = {"dated": [{"element_type": "Project Deliverable", "element": "nested"}]}
		self.assertEqual(
			data.root_progress(deliverables, structure, plan_date=today),
			{"count": 3, "progress": 40, "planned_progress": 50},
		)
		for dates in (
			{"planned_start_date": None},
			{"planned_end_date": "2026-11-05"},
			{"plan_incomplete": 1},
		):
			with self.subTest(dates=dates):
				results = {**deliverables, "dated": {**deliverables["dated"], **dates}}
				self.assertEqual(
					data.root_progress(results, structure, plan_date=today),
					{"count": 3, "progress": 40, "planned_progress": None},
				)
		self.assertEqual(
			data.root_progress({}, {}, plan_date=today),
			{"count": 0, "progress": None, "planned_progress": None},
		)

	def test_result_tree_hides_only_unlinked_optional_slots(self):
		deliverables = {"D": {"title": "Result", "progress": 75}}
		slots = [
			{"element_name": "Optional", "element_type": "Task", "is_optional": 1},
			{"element_name": "Required", "element_type": "Task", "is_optional": 0},
			{"element_name": "Selected", "element_type": "Task", "is_optional": 1, "element": "T"},
			{"element_name": "Restricted", "element_type": "Task", "is_optional": 1, "element": "H"},
		]
		tree, _ = data.results_view(
			deliverables, {"D": slots}, {"T": {"subject": "Selected", "type": "Bug"}}, {}, {}
		)
		self.assertEqual(tree[0]["progress"], 75)
		children = {row["label"]: row for row in tree[0]["children"]}
		self.assertEqual(set(children), {"Required", "Selected", "Restricted"})
		self.assertEqual(children["Selected"]["deliverable_type"], "Bug")
		self.assertEqual(children["Restricted"]["status_note"], "Work is unavailable")

	def test_result_tree_repeats_shared_result_but_charts_count_one(self):
		deliverables = {
			"early": {"name": "early", "title": "Early", "planned_end_date": "2026-11-09"},
			"late": {"name": "late", "title": "Late", "expected_end_date": "2026-11-12"},
			"shared": {"name": "shared", "title": "Shared", "deliverable_type": "Shared"},
		}
		structure = {
			parent: [{"name": f"slot-{parent}", "element_type": "Project Deliverable", "element": "shared"}]
			for parent in ("early", "late")
		}
		tree, counts = data.results_view(
			deliverables, structure, {}, {}, {"deliverable_type": "Shared"}, date(2026, 11, 17)
		)
		self.assertEqual([row["document"] for row in tree], ["early", "late"])
		self.assertEqual([row["children"][0]["document"] for row in tree], ["shared", "shared"])
		self.assertNotEqual(tree[0]["children"][0]["id"], tree[1]["children"][0]["id"])
		self.assertEqual(counts["deliverable_type"], [{"name": "Shared", "count": 1}])

	def test_project_results_uses_only_readable_type_and_accountable_images(self):
		deliverables = {
			"review": {"title": "Review", "deliverable_type": "Document", "progress": 45},
			"nested": {"title": "Nested review", "deliverable_type": "Restricted type"},
			"untyped": {"title": "Untyped result"},
		}
		structure = {
			"review": [
				{"element_type": data.DELIVERABLE, "element": "nested"},
				{"element_type": "Task", "element": "work"},
			]
		}
		assignments = {
			"review": [
				{
					"responsible_type": doctype,
					"responsible": name,
					"responsibility": data.ACCOUNTABLE_CODE,
				}
				for doctype, name in (
					("User", "manager"),
					("User", "without-image"),
					("Contact", "customer"),
					("Contact", "restricted"),
				)
			]
		}
		assignments["review"] += [
			assignments["review"][0],
			{"responsibility": "other", "responsible_type": "User", "responsible": "not-selected"},
		]
		readable = {
			"Project Deliverable Type": {"Document": {"icon": "/files/document.svg", "color": "#123456"}},
			"User": {
				"manager": {"full_name": "Project manager", "user_image": "/files/manager.png"},
				"without-image": {"full_name": "Without image"},
			},
			"Contact": {"customer": {"full_name": "Customer", "image": "/files/customer.png"}},
		}
		with (
			patch.object(data, "project_ids", return_value=["p1"]),
			patch.object(data, "get_deliverables", return_value=deliverables),
			patch.object(data, "load_structure", return_value=structure),
			patch.object(data, "load_assignments", return_value=assignments),
			patch.object(
				data,
				"result_tree_responsibilities",
				return_value=[data.ACCOUNTABLE_CODE],
			),
			patch.object(
				data, "responsibility_definitions", return_value={data.ACCOUNTABLE_CODE: {"enabled": 1}}
			),
			patch.object(
				data, "available_tasks", return_value={"work": {"subject": "Work", "type": "Task type"}}
			),
			patch.object(data, "getdate", return_value=date(2026, 11, 20)),
			patch.object(data, "work_assignees", return_value={("Task", "work"): [{"name": "assigned"}]}),
			patch.object(data, "select_rows", side_effect=lambda doctype, *_: readable[doctype]) as select,
		):
			result = data.project_results("p1")

		select.assert_has_calls(
			[
				call(
					"Project Deliverable Type",
					{"name": ["in", ["Document", "Restricted type"]]},
					["name", "icon", "color"],
				),
				call(
					"User",
					{"name": ["in", ["manager", "without-image"]]},
					["name", "full_name", "user_image"],
				),
				call("Contact", {"name": ["in", ["customer", "restricted"]]}, ["name", "full_name", "image"]),
			],
			any_order=True,
		)
		self.assertEqual(select.call_count, 3)
		review, untyped = result["rows"]
		self.assertEqual((review["document"], review["label"], review["progress"]), ("review", "Review", 45))
		self.assertEqual(review["deliverable_type"], "Document")
		self.assertEqual(review["deliverable_type_icon"], "/files/document.svg")
		self.assertEqual(review["deliverable_type_color"], "#123456")
		self.assertEqual(
			review["accountable"],
			[
				{
					"doctype": "Contact",
					"name": "customer",
					"label": "Customer",
					"image": "/files/customer.png",
				},
				{"doctype": "Contact", "name": "restricted", "label": "restricted", "image": None},
				{
					"doctype": "User",
					"name": "manager",
					"label": "Project manager",
					"image": "/files/manager.png",
				},
				{"doctype": "User", "name": "without-image", "label": "Without image", "image": None},
			],
		)
		nested, work = review["children"]
		self.assertEqual(nested["deliverable_type"], "Restricted type")
		for row in (nested, untyped):
			self.assertIsNone(row["deliverable_type_icon"])
			self.assertIsNone(row["deliverable_type_color"])
			self.assertEqual(row["accountable"], [])
		self.assertEqual(work["deliverable_type"], "Task type")
		self.assertNotIn("deliverable_type_icon", work)
		self.assertNotIn("accountable", work)
		self.assertEqual(review["assignment"], review["accountable"])
		self.assertEqual(work["assignment"], [{"name": "assigned"}])

	def test_results_tree_honors_configured_responsibility_order_and_empty_list(self):
		settings = frappe._dict(
			result_tree_responsibilities=[
				frappe._dict(responsibility=code) for code in ("review", "obsolete", "work", "review")
			]
		)
		with (
			patch.object(data.frappe, "get_cached_doc", return_value=settings),
			patch.object(
				data,
				"responsibility_definitions",
				return_value={
					"review": {"enabled": 1, "responsibility": "Reviewer"},
					"obsolete": {"enabled": 0, "responsibility": "Obsolete"},
					"work": {"enabled": 1, "responsibility": "Contributor"},
				},
			),
		):
			self.assertEqual(
				data.result_tree_responsibilities(),
				["review", "work"],
			)
			settings.result_tree_responsibilities = []
			self.assertEqual(data.result_tree_responsibilities(), [])

	def test_work_assignees_are_scoped_to_visible_documents_and_open_todos(self):
		todos = [frappe._dict(reference_name="W", allocated_to="user")]
		with (
			patch.object(data.frappe, "get_all", return_value=todos) as query,
			patch.object(data, "_participant_rows", return_value={("User", "user"): {"full_name": "Person"}}),
		):
			assigned = data.work_assignees({"W": {}}, {("Contact", "W"): {}})
		self.assertEqual(assigned[("Task", "W")][0]["label"], "Person")
		self.assertEqual(assigned[("Contact", "W")][0]["name"], "user")
		for kind in ("Task", "Contact"):
			query.assert_any_call(
				"ToDo",
				filters={"reference_type": kind, "reference_name": ["in", ["W"]], "status": "Open"},
				fields=["reference_name", "allocated_to"],
			)

	def test_standard_result_type_icons_are_distinct_bundled_assets(self):
		app = Path(data.__file__).parents[1]
		types = json.loads((app / "fixtures/project_deliverable_type.json").read_text(encoding="utf-8"))
		icons = {row["icon"] for row in types}
		self.assertEqual(len(icons), 5)
		for icon in icons:
			self.assertTrue(icon.startswith("/assets/dinext_project_scope/icons/deliverable-types/"))
			asset = app / "public" / icon.removeprefix("/assets/dinext_project_scope/")
			self.assertTrue(asset.is_file(), icon)

	def test_deliverable_type_fixture_import_preserves_configured_icon(self):
		kind = SimpleNamespace(
			doctype="Project Deliverable Type", name="Document", icon="/assets/default.svg"
		)
		db = Mock()
		db.get_value.return_value = "/files/custom.svg"
		with (
			patch.object(frappe, "db", db),
			patch.object(frappe, "flags", frappe._dict(in_fixtures=True)),
		):
			ProjectDeliverableType.before_import(kind)
			self.assertEqual(kind.icon, "/files/custom.svg")

			db.get_value.return_value = None
			kind.icon = "/assets/default.svg"
			ProjectDeliverableType.before_import(kind)
			self.assertEqual(kind.icon, "/assets/default.svg")

	def test_history_has_no_synthetic_actual_values(self):
		events = [
			{"log_date": datetime(2026, 11, 8, 10), "progress": 25},
			{"log_date": datetime(2026, 11, 10, 10), "progress": 10},
		]
		result = {"planned_start_date": "2026-11-02", "planned_end_date": "2026-11-12"}
		first = data.progress_series(result, events, date(2026, 11, 17))
		second = data.progress_series(dict(result, planned_end_date="2026-11-02"), events, date(2026, 11, 17))
		self.assertEqual([value for _, value in first["actual"]], [25, 10])
		self.assertEqual(first["actual"], second["actual"])
		self.assertIn(["2026-11-02", 100], second["planned"])
		self.assertEqual(second["plan_step"], True)
		self.assertEqual(first["planned"][0], ["2026-11-02", 0])
		self.assertEqual(data.progress_series({}, [], date(2026, 11, 17))["plan_reason"], "missing")
		self.assertEqual(
			data.progress_series(dict(result, planned_end_date="2026-11-01"), [], date(2026, 11, 17))[
				"plan_reason"
			],
			"invalid",
		)

	def test_plan_is_clamped_through_events_on_the_planned_end_date(self):
		result = {"planned_start_date": "2026-11-01", "planned_end_date": "2026-11-10"}
		events = [{"log_date": datetime(2026, 11, 10, 18), "progress": 80}]
		series = data.progress_series(result, events, date(2026, 11, 10))
		self.assertEqual(series["planned"][-1], ["2026-11-10T18:00:00", 100])

	def test_recalculation_with_unchanged_progress_keeps_recorded_points(self):
		events = [
			{"log_date": datetime(2026, 11, 7, 10), "progress": 0},
			{"log_date": datetime(2026, 11, 8, 10), "progress": 60},
			{"log_date": datetime(2026, 11, 10, 10), "progress": 20},
			{"log_date": datetime(2026, 11, 11, 10), "progress": 20},
			{"log_date": datetime(2026, 11, 13, 10), "progress": 60},
		]
		result = {"planned_start_date": "2026-11-02", "planned_end_date": "2026-11-18"}
		series = data.progress_series(result, events, date(2026, 11, 17))
		self.assertEqual(
			series["actual"],
			[
				["2026-11-07T10:00:00", 0],
				["2026-11-08T10:00:00", 60],
				["2026-11-10T10:00:00", 20],
				["2026-11-13T10:00:00", 60],
			],
		)

	def test_traceability_uses_plan_and_retains_terminal_tones(self):
		today = date(2026, 11, 17)
		result = {"planned_end_date": "2026-11-09"}
		self.assertEqual(data.result_tone(dict(result, status="Completed"), today), "green")
		self.assertEqual(data.result_tone(dict(result, status="Cancelled"), today), "gray")
		self.assertEqual(data.result_tone(dict(result, status="Acceptance"), today), "yellow")
		self.assertEqual(data.result_tone(dict(result, status="In Progress"), today), "red")
		self.assertEqual(
			data.result_tone({"status": "In Progress", "expected_end_date": "2026-11-09"}, today), "blue"
		)

	@patch.object(reports, "_", lambda string, **_: string)
	def test_traceability_keeps_context_and_grouped_task_paths(self):
		requirements = {
			"top": {"title": "Navigation parent", "kind": "Other"},
			"first": {"title": "First", "kind": "Selected", "parent": "top"},
			"second": {"title": "Second", "kind": "Selected", "parent": "top"},
			"unlinked": {"title": "Unlinked", "kind": "Selected", "approval_stale": True},
		}
		deliverables = {
			"result": {"title": "Shared result", "status": "Acceptance", "planned_end_date": "2026-11-12"}
		}
		structure = {"result": [{"element_type": "Task", "element": "group"}]}
		tasks = {
			"group": {"subject": "Task group", "progress": 40},
			"subtask": {"subject": "Child task", "parent_task": "group", "progress": 80},
		}
		with (
			patch.object(data, "project_ids", return_value=["p1"]),
			patch.object(data, "get_deliverables", return_value=deliverables),
			patch.object(data, "load_structure", return_value=structure),
			patch.object(data, "available_tasks", return_value=tasks),
			patch.object(reports, "scope_requirement_rows", return_value=requirements),
			patch.object(
				reports, "requirement_results", return_value={"first": ["result"], "second": ["result"]}
			),
			patch.object(reports, "getdate", return_value=date(2026, 11, 17)),
		):
			_, rows = reports.traceability({"project": "p1", "kind": "Selected"})
		parent = next(row for row in rows if row["document"] == "top")
		self.assertTrue(parent["context_only"])
		results = [row for row in rows if row["document"] == "result"]
		self.assertEqual([row["status_tone"] for row in results], ["yellow", "yellow"])
		self.assertNotEqual(results[0]["id"], results[1]["id"])
		self.assertEqual([row["depth"] for row in rows if row["document"] == "subtask"], [4, 4])
		unlinked = next(row for row in rows if row["document"] == "unlinked")
		self.assertEqual(unlinked["status_tone"], "red")
		self.assertTrue(unlinked["approval_stale"])

	@patch.object(reports, "_", lambda string: string)
	def test_impact_filters_match_one_row_and_preserve_unfiltered_maximum(self):
		requests = {"cr": {"name": "cr", "creation": datetime(2026, 11, 17, 23, 59, 59)}}
		impacts = {
			"cr": [
				{"type": "schedule", "level": "Strong"},
				{"type": "schedule", "level": "Weak", "estimation": "3\u20135"},
				{"type": "quality", "level": None},
				{"type": "schedule", "level": None},
			]
		}
		_, rows = reports.impact_matrix(
			requests, impacts, [], {"impact_type": "quality", "impact_level": "Strong"}
		)
		self.assertEqual(rows, [])
		columns, rows = reports.impact_matrix(
			requests,
			impacts,
			["cost"],
			{"impact_type": "schedule", "impact_level": "Weak", "to_date": "2026-11-17"},
		)
		cells = {
			column["label"]: rows[0]["cells"].get(column["fieldname"])
			for column in columns
			if column.get("group")
		}
		self.assertIsNone(cells["cost"])
		self.assertIsNone(cells["quality"]["level"])
		schedule = cells["schedule"]
		self.assertEqual(schedule["level"], "Strong")
		self.assertEqual(schedule["unspecified"], 1)
		self.assertEqual([item["matched"] for item in schedule["details"]], [False, True, False])
		self.assertEqual(schedule["details"][1]["estimation"], "3\u20135")

	@patch.object(export, "_", lambda string: string)
	@patch.object(reports, "_", lambda string: string)
	def test_impact_workbook_retains_colors_matches_and_text(self):
		columns, rows = reports.impact_matrix(
			{"cr": {"name": "cr", "title": "@User text", "creation": datetime(2026, 11, 17, 23, 59, 59)}},
			{
				"cr": [
					{"type": "schedule", "level": "Strong", "estimation": "=3+5"},
					{
						"type": "schedule",
						"level": "Weak",
						"estimation": "3\u20135",
						"explanation": "Two stages",
					},
				]
			},
			["quality"],
			{"impact_type": "schedule", "impact_level": "Weak"},
		)
		book = load_workbook(BytesIO(export.make_workbook(reports.IMPACT, columns, rows)))
		table = book.worksheets[0]
		self.assertEqual(table["G3"].value, "Strong")
		self.assertEqual(table["G3"].fill.fgColor.rgb, "FFC62828")
		self.assertIsNone(table["F3"].value)
		self.assertEqual(table["A3"].value, "@User text")
		self.assertEqual(table["E3"].value, datetime(2026, 11, 17, 23, 59, 59))
		details = book["Impact details"]
		self.assertEqual(details["F2"].value, "=3+5")
		self.assertEqual(details["F2"].data_type, "s")
		self.assertEqual(details["F3"].value, "3\u20135")
		self.assertEqual(details["K3"].value, "Yes")

	@patch.object(export, "_", lambda string: string)
	@patch.object(reports, "_", lambda string: string)
	def test_workbook_keeps_role_groups_typed_values_and_all_codes(self):
		definitions = {
			"Do": {"responsibility": "Does the work", "color": "#12ABFF"},
			"Own": {"responsibility": "Accountable", "color": "#DC2525"},
		}
		assignments = {
			"r1": [
				{
					"project_role": "Lead",
					"responsible_type": "User",
					"responsible": "x",
					"responsibility": "Do",
				},
				{
					"project_role": "Lead",
					"responsible_type": "User",
					"responsible": "x",
					"responsibility": "Own",
				},
				{
					"project_role": "Lead",
					"responsible_type": "Contact",
					"responsible": "x",
					"responsibility": "Do",
				},
			]
		}
		columns, rows = reports.responsibility_matrix(
			{"r1": {"name": "r1", "title": "=1+2", "category": "Cat", "deliverable_type": "Type"}},
			assignments,
			definitions,
			{("Contact", "x"): {"full_name": "Same"}, ("User", "x"): {"full_name": "Same"}},
			{},
			{},
		)
		self.assertEqual(len([column for column in columns if column.get("group")]), 2)
		self.assertEqual(
			data.normalize_filters({"responsibility": ["Do", "Own"]}, list_fields=("responsibility",)),
			{"responsibility": ["Do", "Own"]},
		)
		for filters in (
			{"responsibility": ["Do", {"value": "Own"}]},
			{"project": ["P1", "P2"]},
		):
			with self.assertRaises(frappe.ValidationError):
				data.normalize_filters(filters, list_fields=("responsibility",))
		selected_columns, selected_rows = reports.responsibility_matrix(
			{"r1": {"name": "r1"}},
			assignments,
			definitions,
			{("Contact", "x"): {"full_name": "Same"}, ("User", "x"): {
				"full_name": "Same", "user_image": "/files/member.png",
			}},
			{},
			{"responsibility": ["Own", "Do"], "responsible_type": "User"},
		)
		assignee = selected_columns[-1]["assignee"]
		self.assertEqual(assignee["image"], "/files/member.png")
		self.assertEqual(assignee["label"], "Same")
		self.assertEqual(selected_rows[-1]["assignment_1"], "Do / Own")

		self.assertEqual(
			reports.responsibility_matrix(
				{"r1": {"name": "r1"}},
				assignments,
				definitions,
				{},
				{},
				{"responsibility": "Own", "responsible_type": "Contact", "responsible": "x"},
			)[1],
			[],
		)
		buffer = export.make_workbook("Project Responsibility Matrix", columns, rows)
		book = load_workbook(BytesIO(buffer), rich_text=True)
		table = book.worksheets[0]
		self.assertIn("C1:D1", table.merged_cells)
		self.assertEqual(table["A3"].value, "Cat")
		self.assertEqual(table["A4"].value, "=1+2")
		self.assertEqual(table["A4"].data_type, "s")
		self.assertTrue(table["A4"].alignment.wrap_text)
		self.assertEqual(table["A4"].alignment.indent, 1)
		self.assertEqual(table["B4"].value, "Type")
		multiple = next(cell for cell in table[4][2:] if "Own" in str(cell.value))
		self.assertTrue(multiple.alignment.wrap_text)
		self.assertEqual(
			[block.font.color.rgb for block in multiple.value if hasattr(block, "font")],
			["FF12ABFF", "FFDC2525"],
		)
		self.assertEqual(book["Legend"]["B2"].value, "Does the work")

	@patch.object(export, "_", lambda string: string)
	@patch.object(export, "dataset", side_effect=frappe.PermissionError)
	@patch.object(export, "get_report_doc")
	@patch.object(frappe, "has_permission", return_value=True)
	def test_download_rechecks_project_through_report_selection(self, _, get_report, dataset):
		get_report.return_value = frappe._dict(ref_doctype="Project Deliverable")
		with (
			patch.object(
				frappe.local,
				"flags",
				frappe._dict(in_test=True),
				create=not hasattr(frappe.local, "flags"),
			),
			self.assertRaises(frappe.PermissionError),
		):
			export.download("Project Responsibility Matrix", {"project": "formerly-visible"})
		dataset.assert_called_once_with("Project Responsibility Matrix", {"project": "formerly-visible"})
