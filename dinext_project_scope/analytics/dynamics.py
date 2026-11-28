from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from json import JSONDecodeError, loads
from math import ceil

import frappe
from frappe.utils import cint, getdate

from dinext_project_scope.analytics import data
from dinext_project_scope.analytics.contracts import (
	CategoryDynamics,
	DynamicsSeries,
	FilterValue,
	ProjectResultDynamicsResponse,
	ResponsibleItem,
)

TREND_HORIZON = 90


@frappe.whitelist(methods=["GET"])
def project_result_dynamics(
	project: str,
	filters: dict[str, FilterValue] | str | None = None,
	reporting_date: str | None = None,
	baseline_date: str | None = None,
) -> ProjectResultDynamicsResponse:
	"""Return deliverable progress series and assignment counts for the selected slice."""
	projects = data.project_ids(project, required=True)
	today = getdate()
	reporting, baseline = data.result_progress_dates(reporting_date, baseline_date, today)
	cutoff = min(reporting, today)
	filters = data.normalize_result_filters(filters)
	deliverables = data.get_deliverables(projects)
	matching = data.matching_results(deliverables, filters, today)
	groups, labels = responsible_groups(matching)
	responsible = filters.get("responsible") or ""

	eligible = {name for name, row in deliverables.items() if row.get("status") != "Cancelled"}
	structure = data.load_structure(eligible)
	children = {
		name: [
			slot.element
			for slot in slots
			if slot.element_type == data.DELIVERABLE and slot.element in eligible
		]
		for name, slots in structure.items()
	}
	selection = groups.get(responsible, set()) if responsible else matching.keys()
	roots = {name: matching[name] for name in slice_roots(eligible & selection, children)}
	journal = defaultdict(list)
	for event in data.deliverable_log_events(roots, cutoff):
		journal[event.deliverable].append(event)

	expected_ends = expected_end_dates(roots, journal, cutoff, today)
	category, time_range = series_for(
		roots.values(), journal, expected_ends, reporting, baseline, cutoff, today
	)
	return {
		"cutoff": str(cutoff),
		"reporting_date": str(reporting),
		"baseline_date": str(baseline) if baseline else None,
		"range": [str(day) for day in time_range],
		"category": category,
		"responsible": {"selected": responsible, "items": group_items(groups, labels)},
	}


def responsible_groups(deliverables):
	codes = data.result_tree_responsibilities() if deliverables else []
	selected = (
		data.select_result_assignments(data.load_assignments(deliverables), set(codes)) if codes else {}
	)
	names = data.participant_names(selected)
	groups = defaultdict(set)
	labels = {}
	for name in deliverables:
		for key in data.result_participant_keys(data.participant(row) for row in selected.get(name, ())):
			groups[key].add(name)
			if key != data.ONLY_EMPTY:
				doctype, member = key.split(":", 1)
				labels[key] = names.get((doctype, member), member)

	duplicates = Counter(labels.values())
	for value, label in labels.items():
		if duplicates[label] > 1:
			labels[value] = f"{label} ({value})"
	return groups, labels


def group_items(groups, labels) -> list[ResponsibleItem]:
	items = [
		{"value": name, "label": labels.get(name, ""), "count": len(documents)}
		for name, documents in groups.items()
	]
	return sorted(items, key=lambda item: (not item["label"], item["label"].casefold(), item["value"]))


def slice_roots(selected, children):
	# Walk through all readable eligible ancestors, including ones outside the slice.
	pending = [child for name in selected for child in children.get(name, ())]
	nested = set()
	while pending:
		name = pending.pop()
		if name not in nested:
			nested.add(name)
			pending.extend(children.get(name, ()))
	return sorted(selected - nested)


def expected_end_dates(rows, journal, cutoff, today):
	if cutoff == today:
		return {
			name: end
			for name, row in rows.items()
			if not cint(row.get("forecast_incomplete"))
			and row.get("expected_end_date")
			and (end := getdate(row.expected_end_date)) > cutoff
		}

	latest = {name: events[-1] for name, events in journal.items()}
	candidates = {
		name: (event.name, end)
		for name, event in latest.items()
		if event.expected_end_date and (end := getdate(event.expected_end_date)) > cutoff
	}
	if not candidates:
		return {}
	# Read calculation snapshots only for the latest eligible journal rows with a future end.
	incomplete = {
		row.name
		for row in frappe.get_all(
			"Project Deliverable Log",
			filters={"name": ["in", [name for name, _end in candidates.values()]]},
			fields=["name", "work_snapshot"],
		)
		if snapshot_forecast_is_incomplete(row.work_snapshot)
	}
	return {name: end for name, (event, end) in candidates.items() if event not in incomplete}


def snapshot_forecast_is_incomplete(snapshot):
	try:
		calculation = loads(snapshot).get("calculation", {}) if snapshot else {}
		return bool(cint(calculation.get("forecast_incomplete")))
	except (JSONDecodeError, AttributeError, TypeError):
		# Older journal records can contain a date without a calculation snapshot.
		return False


def chart_range(roots, series, reporting, baseline, cutoff):
	dates = {reporting, cutoff}
	if baseline:
		dates.add(baseline)
	for row in roots:
		start, end, reason = data.plan_dates(row)
		if not reason and not cint(row.get("plan_incomplete")):
			dates.update((start, end))
			if start == end and start > date.min:
				dates.add(start - timedelta(days=1))
	for points in series.values():
		dates.update(date.fromisoformat(day) for day, _value in points)
	first, last = min(dates), max(dates)
	return (first, last) if first != last else (first, last + timedelta(days=1))


def series_for(roots, journal, expected_ends, reporting, baseline, cutoff, today) -> tuple[CategoryDynamics, tuple[date, date]]:
	series: DynamicsSeries = {"planned": [], "actual": [], "forecast": [], "trend": []}
	result: CategoryDynamics = {"count": len(roots), "forecast_missing": 0, "series": series}
	if roots:
		actual, facts = actual_progress(roots, journal, cutoff, today)
		series["actual"] = actual
		if actual[-1][1] is not None:
			series["forecast"], result["forecast_missing"] = forecast_series(
				facts, expected_ends, reporting, cutoff
			)
			series["trend"] = trend_series(actual, cutoff)
		if actual[-1][0] != str(cutoff):
			actual.append([str(cutoff), actual[-1][1]])
	time_range = chart_range(roots, series, reporting, baseline, cutoff)
	series["planned"] = plan_series(roots, reporting, cutoff, time_range) if roots else []
	return result, time_range


def plan_series(roots, reporting, cutoff, time_range):
	boundaries = {*time_range, reporting, cutoff}
	for row in roots:
		start, end, reason = data.plan_dates(row)
		if reason or cint(row.get("plan_incomplete")):
			return []
		boundaries.update((start, end))
		if start == end and start > date.min:
			boundaries.add(start - timedelta(days=1))
	return [[str(day), data.average_planned_progress(roots, day)] for day in sorted(boundaries)]


def actual_progress(roots, journal, cutoff, today):
	updates = defaultdict(dict)
	for row in roots:
		for event in journal.get(row.name, ()):
			if event.progress is not None:
				updates[getdate(event.log_date)][row.name] = data.numeric_progress(event.progress)
		if cutoff == today:
			progress = row.get("progress")
			updates[today][row.name] = data.numeric_progress(progress) if progress is not None else None

	facts = {}
	points = []
	for day, values in sorted(updates.items()):
		facts.update(values)
		average = None
		if len(facts) == len(roots) and None not in facts.values():
			average = sum(facts.values()) / len(roots)
		points.append([str(day), average])
	return points or [[str(cutoff), None]], facts


def forecast_series(facts, expected_ends, reporting, cutoff):
	unfinished = {name for name, progress in facts.items() if progress < 100}
	durations = {name: (expected_ends[name] - cutoff).days for name in unfinished & expected_ends.keys()}
	missing = len(unfinished) - len(durations)
	if unfinished and not durations:
		return [], missing

	days = {0, (reporting - cutoff).days, *durations.values()}
	points = []
	for elapsed in sorted(days):
		values = [
			progress + (100 - progress) * min(1, elapsed / durations[name]) if name in durations else progress
			for name, progress in facts.items()
		]
		points.append([str(cutoff + timedelta(days=elapsed)), sum(values) / len(values)])
	return points, missing


def trend_series(observed, cutoff):
	recorded = [(day, value) for day, value in observed if value is not None]
	if len(recorded) < 2:
		return []
	first_day, first = recorded[0]
	last = recorded[-1][1]
	rate = (last - first) / (cutoff - date.fromisoformat(first_day)).days
	horizon = TREND_HORIZON
	if rate:
		room = 100 - last if rate > 0 else last
		horizon = min(horizon, ceil(room / abs(rate)))
	points = [[first_day, first], [str(cutoff), last]]
	if horizon:
		points.append([str(cutoff + timedelta(days=horizon)), data.numeric_progress(last + rate * horizon)])
	return points
