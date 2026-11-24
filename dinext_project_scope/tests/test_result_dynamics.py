import json
from datetime import date, datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.utils import getdate

from dinext_project_scope.analytics import data
from dinext_project_scope.analytics.dynamics import project_result_dynamics

TODAY = date(2026, 11, 24)


def deliverable(name, category="Rollout", **values):
	return frappe._dict(
		{
			"name": name,
			"status": "In Progress",
			"category": category,
			"deliverable_type": "Service",
			"progress": 40,
			"planned_start_date": "2026-11-10",
			"planned_end_date": "2026-11-30",
			"expected_end_date": "2026-12-10",
			**values,
		}
	)


def nested(*names):
	return [frappe._dict(element_type=data.DELIVERABLE, element=name) for name in names]


def assignment(person, doctype="User", code=data.ACCOUNTABLE_CODE):
	return frappe._dict(responsible=person, responsible_type=doctype, responsibility=code)


def event(name, on, progress, expected=None, *, forecast_incomplete=0):
	return frappe._dict(
		name=f"{name}:{on}",
		deliverable=name,
		log_date=datetime.fromisoformat(on),
		progress=progress,
		expected_end_date=expected,
		work_snapshot=json.dumps({"calculation": {"forecast_incomplete": forecast_incomplete}}),
	)


class TestResultDynamics(TestCase):
	def setUp(self):
		self.rows = {}
		self.structure = {}
		self.assignments = {}
		self.journal = []
		self.codes = [data.ACCOUNTABLE_CODE, "Reviewer"]

	def add(self, *rows):
		self.rows.update((row.name, row) for row in rows)

	def read(self, **args):
		with (
			patch("dinext_project_scope.access.check_project") as check_project,
			patch.object(data, "get_deliverables", return_value=self.rows),
			patch.object(data, "load_structure", return_value=self.structure),
			patch.object(data, "load_assignments", return_value=self.assignments),
			patch.object(data, "result_tree_responsibilities", return_value=self.codes),
			patch.object(data, "participant_names", return_value={("Contact", "member"): "External member"}),
			patch(
				"dinext_project_scope.analytics.dynamics.getdate",
				side_effect=lambda value=None: TODAY if value is None else getdate(value),
			),
			patch.object(frappe, "get_all", side_effect=self.read_journal) as journal,
		):
			payload = project_result_dynamics("project", **args)
		check_project.assert_called_once_with("project")
		self.journal_query = next(iter(journal.call_args_list), None)
		return payload

	def read_journal(self, doctype, *, filters, **kwargs):
		self.assertEqual(doctype, "Project Deliverable Log")
		if "name" in filters:
			return [row for row in self.journal if row.name in filters["name"][1]]
		return [
			row
			for row in self.journal
			if row.deliverable in filters["deliverable"][1] and row.log_date.date() < filters["log_date"][1]
		]

	def test_roots_follow_nested_paths_and_count_shared_children_once(self):
		self.add(
			deliverable("parent", progress=70),
			deliverable("intermediate", "Integration", progress=55),
			deliverable("child", progress=95),
			deliverable("other-parent", "Testing", progress=30),
			deliverable("another-root", progress=10),
			deliverable("cancelled", status="Cancelled", progress=90),
			deliverable("template", status="Template", progress=100),
		)
		self.structure = {
			"parent": nested("intermediate"),
			"intermediate": nested("child"),
			"other-parent": nested("child"),
		}

		all_results = self.read()["category"]
		self.assertEqual(all_results["count"], 3)
		self.assertAlmostEqual(all_results["series"]["actual"][-1][1], (70 + 30 + 10) / 3)
		rollout = self.read(category="Rollout")["category"]
		self.assertEqual(rollout["count"], 2)
		self.assertEqual(rollout["series"]["actual"][-1], [str(TODAY), 40])
		filtered = self.read(filters={"category": "Rollout"}, category="Testing")
		self.assertEqual(filtered["category"]["selected"], "")
		self.assertEqual(filtered["category"]["count"], 2)
		self.assertEqual(filtered["responsible"]["count"], 2)

	def test_assignments_use_configured_codes_and_distinguish_people(self):
		self.add(deliverable("parent"), deliverable("child", progress=75), deliverable("unassigned", ""))
		self.structure = {"parent": nested("child")}
		self.assignments = {
			"parent": [assignment("excluded", code="Discontinued")],
			"child": [
				assignment("member"),
				assignment("member", code="Reviewer"),
				assignment("member", doctype="Contact"),
			],
		}

		payload = self.read(responsible="User:member")
		self.assertEqual(payload["responsible"]["series"]["actual"][-1], [str(TODAY), 75])
		self.assertEqual(payload["responsible"]["count"], 1)
		self.assertEqual(payload["category"]["count"], 2)
		options = {option["value"] for option in payload["responsible"]["options"]}
		self.assertEqual(options, {"User:member", "Contact:member", data.ONLY_EMPTY})
		self.assertEqual(self.read(responsible=data.ONLY_EMPTY)["responsible"]["count"], 2)
		self.assertEqual(self.read(category=data.ONLY_EMPTY)["category"]["count"], 1)
		self.codes = []
		self.assertEqual(
			[option["value"] for option in self.read()["responsible"]["options"]], [data.ONLY_EMPTY]
		)

	def test_historical_fact_plan_forecast_and_trend_use_reporting_date(self):
		self.add(deliverable("a", progress=82), deliverable("b", progress=99, planned_end_date="2026-11-20"))
		self.journal = [
			event("a", "2026-11-12T10:00", 20, "2026-11-20"),
			event("b", "2026-11-12T10:00", 40),
			event("a", "2026-11-14T09:00", 35, "2026-11-20"),
			event("a", "2026-11-14T10:00", 40, "2026-11-20"),
			event("b", "2026-11-14T10:00", 60),
			event("a", "2026-11-16T10:00", 70, "2026-12-10"),
		]

		payload = self.read(reporting_date="2026-11-15")
		self.assertEqual(payload["cutoff"], "2026-11-15")
		group = payload["category"]
		self.assertEqual(group["forecast_missing"], 1)
		series = group["series"]
		self.assertEqual(series["actual"], [["2026-11-12", 30], ["2026-11-14", 50], ["2026-11-15", 50]])
		self.assertEqual(dict(series["planned"])["2026-11-15"], 37.5)
		self.assertEqual(series["forecast"], [["2026-11-15", 50], ["2026-11-20", 80]])
		self.assertEqual(series["trend"], [["2026-11-15", 50], ["2026-11-20", 100]])
		self.assertLessEqual(payload["range"][0], "2026-11-12")
		self.assertGreaterEqual(payload["range"][1], "2026-11-30")

	def test_historical_forecast_excludes_expected_dates_from_incomplete_snapshots(self):
		self.add(deliverable("a", progress=40))
		self.journal = [
			event("a", "2026-11-12T10:00", 30, "2026-11-20", forecast_incomplete=1),
			event("a", "2026-11-17T10:00", 35, "2026-11-26"),
		]
		early = self.read(reporting_date="2026-11-15")["category"]
		self.assertEqual(early["forecast_missing"], 1)
		self.assertEqual(early["series"]["forecast"], [])
		later = self.read(reporting_date="2026-11-18")["category"]
		self.assertEqual(later["forecast_missing"], 0)
		self.assertEqual(later["series"]["forecast"][-1], ["2026-11-26", 100])

	def test_missing_history_and_schedule_leave_gaps(self):
		self.add(
			deliverable("a", planned_end_date=None, expected_end_date="2026-11-23"),
			deliverable("b", planned_end_date="2026-11-15", forecast_incomplete=1),
		)
		self.journal = [
			event("a", "2026-11-17T10:00", 10, "2026-11-19"),
			event("b", "2026-11-20T10:00", 70, "2026-11-19"),
		]

		early = self.read(reporting_date="2026-11-18")["category"]["series"]
		self.assertTrue(all(progress is None for _, progress in early["actual"]))
		self.assertEqual(early["forecast"], [])
		self.assertEqual(early["trend"], [])
		self.assertEqual(early["planned"], [])
		current = self.read()["category"]
		self.assertEqual(current["forecast_missing"], 2)
		self.assertEqual(current["series"]["forecast"], [])
		self.assertIsNone(current["series"]["actual"][0][1])

	def test_future_reporting_date_anchors_at_today_and_caps_trend(self):
		self.add(deliverable("a", progress=29))
		self.journal = [
			event("a", "2026-11-01T10:00", 99),
			event("a", "2026-11-21T10:00", 26),
			event("a", "2026-11-25T10:00", 72),
		]
		payload = self.read(reporting_date="2027-04-01")
		self.assertEqual(payload["cutoff"], str(TODAY))
		series = payload["category"]["series"]
		self.assertEqual(series["actual"][-1], [str(TODAY), 29])
		self.assertEqual(series["trend"], [[str(TODAY), 29], ["2027-02-03", 100]])
		self.assertEqual(payload["range"][1], "2027-04-01")

		self.rows["a"].progress = 26
		series = self.read()["category"]["series"]
		self.assertEqual(series["trend"][-1], [str(TODAY + timedelta(days=90)), 26])

	def test_dynamics_queries_only_journals_of_readable_filtered_roots(self):
		self.add(deliverable("allowed"), deliverable("other", "Testing"))
		self.structure = {"allowed": nested("foreign")}
		self.assignments = {"foreign": [assignment("private-name")]}
		self.journal = [event("foreign", "2026-11-20", 93), event("allowed", "2026-11-20", 50)]
		payload = self.read(filters={"category": "Rollout"})
		self.assertEqual(payload["category"]["count"], 1)
		self.assertNotIn("private-name", str(payload))
		self.assertEqual(self.journal_query.kwargs["filters"]["deliverable"], ["in", ["allowed"]])

	def test_dynamics_denies_project_access_before_loading_results(self):
		with (
			patch("dinext_project_scope.access.check_project", side_effect=frappe.PermissionError),
			patch.object(data, "get_deliverables") as read_deliverables,
			self.assertRaises(frappe.PermissionError),
		):
			project_result_dynamics("foreign", category="private", responsible="User:private")
		read_deliverables.assert_not_called()
