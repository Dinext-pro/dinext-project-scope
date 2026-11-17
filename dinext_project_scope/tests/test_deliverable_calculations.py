from unittest import TestCase

from dinext_project_scope.deliverable_calculations import calculate, work_blockers, work_digest


def slot(key, weight=1, *, name=None, optional=False):
	return {
		"source_element_key": key,
		"element_name": key,
		"element_type": "Task",
		"element": name,
		"weight": weight,
		"is_optional": int(optional),
	}


def task(progress, status="Working", **details):
	return {"progress": progress, "status": status, **details}


class TestDeliverableCalculations(TestCase):
	def test_weighted_progress_supports_missing_cancelled_and_optional_work(self):
		done = task(100, "Completed")
		working = task(20)
		cancelled = task(90, "Cancelled")
		rows = [(slot("done", name="A"), done), (slot("ongoing", 3, name="B"), working)]
		self.assertEqual(calculate("In Progress", rows)["progress"], 40)
		self.assertEqual(calculate("In Progress", [rows[0], (slot("missing"), None)])["progress"], 50)
		self.assertEqual(
			calculate("In Progress", [rows[0], (slot("required", name="C"), cancelled)])["progress"], 50
		)
		self.assertEqual(
			calculate(
				"In Progress",
				[
					rows[0],
					(slot("optional", 100, optional=True), None),
					(slot("cancelled", 100, name="C", optional=True), cancelled),
					(slot("weightless", 0, name="B"), working),
				],
			)["progress"],
			100,
		)
		self.assertEqual(
			calculate("In Progress", [(slot("weightless", 0, name="B"), working)])["progress"], 0
		)

	def test_planned_forecast_and_actual_dates_are_independent(self):
		done = task(
			100,
			"Completed",
			planned_start_date="2026-11-03",
			planned_end_date="2026-11-07",
			expected_end_date="2026-11-08",
			actual_end_date="2026-11-10",
		)
		ongoing = task(90, planned_end_date="2026-11-09", expected_end_date="2026-11-14")
		rows = [(slot("done", name="A"), done), (slot("weightless", 0, name="B"), ongoing)]
		initial = calculate("Acceptance", rows)
		self.assertEqual(initial["planned_start_date"], "2026-11-03")
		self.assertEqual(initial["planned_end_date"], "2026-11-09")
		self.assertTrue(initial["plan_incomplete"])
		self.assertFalse(initial["forecast_incomplete"])
		self.assertEqual(initial["expected_end_date"], "2026-11-14")
		self.assertIsNone(initial["actual_end_date"])

		ongoing["expected_end_date"] = "2026-11-16"
		updated = calculate("Acceptance", rows)
		self.assertEqual(updated["planned_end_date"], initial["planned_end_date"])
		self.assertEqual(updated["expected_end_date"], "2026-11-16")

		ongoing.update(status="Completed", actual_end_date="2026-11-09")
		accepted = calculate("Completed", rows, "2026-11-12")
		self.assertEqual(accepted["expected_end_date"], "2026-11-10")
		self.assertEqual(accepted["actual_end_date"], "2026-11-10")

	def test_missing_and_recursive_dates(self):
		nested = task(
			50,
			"Completed",
			planned_start_date="2026-11-01",
			planned_end_date="2026-11-09",
			expected_end_date="2026-11-18",
			plan_incomplete=True,
			forecast_incomplete=True,
			requires_recheck=True,
		)
		cancelled = task(50, "Cancelled", planned_end_date="2026-11-29", expected_end_date="2026-11-30")
		rows = [
			({**slot("nested", name="D"), "element_type": "Project Deliverable"}, nested),
			(slot("cancelled", name="C", optional=True), cancelled),
		]
		value = calculate("Acceptance", rows)
		self.assertEqual(value["planned_start_date"], "2026-11-01")
		self.assertEqual(value["planned_end_date"], "2026-11-09")
		self.assertTrue(value["plan_incomplete"])
		self.assertEqual(value["expected_end_date"], "2026-11-18")
		self.assertTrue(value["forecast_incomplete"])
		self.assertIsNone(value["actual_end_date"])

		without_plan = calculate(
			"In Progress", [(slot("task", name="A"), task(20, expected_end_date="2026-11-18"))]
		)
		self.assertIsNone(without_plan["planned_end_date"])
		self.assertFalse(without_plan["plan_incomplete"])

	def test_simple_result_uses_acceptance_date(self):
		self.assertEqual(calculate("Acceptance", [])["progress"], 0)
		done = calculate("Completed", [], "2026-11-12")
		self.assertEqual(done["progress"], 100)
		self.assertEqual(done["actual_end_date"], "2026-11-12")
		self.assertIsNone(done["planned_end_date"])

	def test_acceptance_checks_linked_zero_weight_and_optional_work(self):
		rows = [
			(slot("unfilled"), None),
			(slot("weightless", 0, name="A"), task(0)),
			(slot("cancelled", name="B", optional=True), task(80, "Cancelled")),
			(slot("unused", optional=True), None),
			(
				{**slot("nested", name="D"), "element_type": "Project Deliverable"},
				task(100, "Completed", requires_recheck=True),
			),
		]
		self.assertEqual(
			work_blockers(rows),
			[
				("unfilled", "missing"),
				("weightless", "incomplete"),
				("cancelled", "incomplete"),
				("nested", "recheck"),
			],
		)

	def test_work_digest_notices_a_changed_nested_snapshot_with_equal_progress(self):
		first = [{"element": "nested", "state": {"progress": 100, "work_digest": "abc"}}]
		second = [{"element": "nested", "state": {"progress": 100, "work_digest": "def"}}]
		self.assertNotEqual(work_digest(first), work_digest(second))
