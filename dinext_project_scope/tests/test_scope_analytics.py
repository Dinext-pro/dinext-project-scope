from datetime import date, datetime
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

import frappe
from openpyxl import load_workbook

from dinext_project_scope.analytics import data, export, reports


class TestScopeAnalytics(TestCase):
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

	@patch.object(reports, "_", lambda string: string)
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
			{("Contact", "x"): "Same", ("User", "x"): "Same"},
			{},
			{},
		)
		self.assertEqual(len([column for column in columns if column.get("group")]), 2)
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
		self.assertEqual(table["B4"].value, "Type")
		multiple = next(cell.value for cell in table[4][2:] if "Own" in str(cell.value))
		self.assertEqual(
			[block.font.color.rgb for block in multiple if hasattr(block, "font")], ["FF12ABFF", "FFDC2525"]
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
