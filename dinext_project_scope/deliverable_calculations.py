"""Progress, dates and acceptance readiness for one result's current work."""

import hashlib
import json
from math import fsum

COMPLETED = "Completed"
CANCELLED = "Cancelled"
DELIVERABLE = "Project Deliverable"
OTHER = "Other"
DATE_FIELDS = ("planned_start_date", "planned_end_date", "expected_end_date", "actual_end_date")
PROJECTION_FIELDS = ("progress", *DATE_FIELDS, "plan_incomplete", "forecast_incomplete", "requires_recheck")


def canonical_json(value):
	return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def work_digest(value):
	return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def calculate(status, rows, accepted_on=None):
	rows = [(row, work) for row, work in rows if row["element_type"] != OTHER]
	if not rows:
		finished_on = accepted_on if status == COMPLETED else None
		return {
			"progress": 100.0 if status == COMPLETED else 0.0,
			"planned_start_date": None,
			"planned_end_date": None,
			"expected_end_date": finished_on,
			"actual_end_date": finished_on,
			"plan_incomplete": 0,
			"forecast_incomplete": 0,
			"zero_weight": False,
		}

	weights = []
	contributions = []
	planned_starts = []
	planned_ends = []
	forecasts = []
	actuals = []
	missing_plan = missing_forecast = missing_actual = False

	for row, work in rows:
		if row["is_optional"] and (not work or work["status"] == CANCELLED):
			continue

		weight = row["weight"]
		weights.append(weight)
		if work and work["status"] != CANCELLED:
			contributions.append(weight * min(100.0, max(0.0, work["progress"])))

		work = work or {}
		start = work.get("planned_start_date")
		end = work.get("planned_end_date")
		completed = work.get("status") == COMPLETED
		actual = work.get("actual_end_date") if completed else None
		if completed and row["element_type"] != DELIVERABLE:
			forecast = actual
		else:
			forecast = work.get("expected_end_date")

		if start:
			planned_starts.append(start)
		if end:
			planned_ends.append(end)
		if forecast:
			forecasts.append(forecast)
		if actual:
			actuals.append(actual)
		missing_plan |= not start or not end or bool(work.get("plan_incomplete"))
		missing_forecast |= not forecast or bool(work.get("forecast_incomplete"))
		missing_actual |= not actual

	weight_total = fsum(weights)
	return {
		"progress": round(fsum(contributions) / weight_total, 6) if weight_total else 0.0,
		"planned_start_date": min(planned_starts, default=None),
		"planned_end_date": max(planned_ends, default=None),
		"expected_end_date": max(forecasts, default=None),
		"actual_end_date": None if missing_actual else max(actuals, default=None),
		"plan_incomplete": int(bool(planned_starts or planned_ends) and missing_plan),
		"forecast_incomplete": int(missing_forecast),
		"zero_weight": not weight_total,
	}


def work_blockers(rows):
	blockers = []
	for row, work in rows:
		label = row["element_name"]
		if not row.get("element"):
			if not row["is_optional"]:
				blockers.append((label, "missing"))
		elif row["element_type"] == OTHER:
			continue
		elif not work or work["status"] != COMPLETED:
			blockers.append((label, "incomplete"))
		elif not row["is_optional"] and row["element_type"] == DELIVERABLE and work.get("requires_recheck"):
			blockers.append((label, "recheck"))
	return blockers
