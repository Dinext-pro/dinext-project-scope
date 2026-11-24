from collections import Counter, defaultdict
from datetime import date, timedelta
from json import JSONDecodeError, loads
from math import ceil

import frappe
from frappe.utils import cint, getdate

from dinext_project_scope.analytics import data

TREND_LOOKBACK = 14
TREND_HORIZON = 90


@frappe.whitelist(methods=["GET"])
def project_result_dynamics(project, filters=None, reporting_date=None, category="", responsible=""):
	projects = data.project_ids(project, required=True)
	today = getdate()
	reporting, _ = data.result_progress_dates(reporting_date, None, today)
	cutoff = min(reporting, today)
	eligible = {
		name: row
		for name, row in data.get_deliverables(projects).items()
		if row.get("status") not in {"Cancelled", "Template"}
	}
	matching = data.matching_results(eligible, data.normalize_result_filters(filters), today)
	structure = data.load_structure(eligible)
	children = {
		name: [
			slot.element
			for slot in slots
			if slot.element_type == data.DELIVERABLE and slot.element in eligible
		]
		for name, slots in structure.items()
	}

	categories = defaultdict(set)
	for name, row in matching.items():
		categories[row.get("category") or data.ONLY_EMPTY].add(name)
	members, labels = responsible_groups(matching)

	journal = defaultdict(list)
	for event in data.deliverable_log_events(matching, cutoff):
		journal[event.deliverable].append(event)
	expected_ends = expected_end_dates(matching, journal, cutoff, today)
	time_range = chart_range(matching, journal, expected_ends, reporting, cutoff, today)
	all_names = set(matching)
	result = {"cutoff": str(cutoff), "range": [str(day) for day in time_range]}
	for key, groups, selection, group_labels in (
		("category", categories, category, {}),
		("responsible", members, responsible, labels),
	):
		selection = selection if isinstance(selection, str) and selection in groups else ""
		roots = [matching[name] for name in slice_roots(groups.get(selection, all_names), children)]
		result[key] = {
			"selected": selection,
			"options": group_options(groups, group_labels),
			**series_for(roots, journal, expected_ends, reporting, cutoff, today, time_range),
		}
	return result


def responsible_groups(deliverables):
	codes = data.result_tree_responsibilities() if deliverables else []
	selected = (
		data.select_result_assignments(data.load_assignments(deliverables), set(codes)) if codes else {}
	)
	names = data.participant_names(selected)
	groups = defaultdict(set)
	labels = {}
	for name in deliverables:
		participants = {
			member
			for row in selected.get(name, ())
			if (member := data.participant(row))[0] in data.PARTICIPANT_IMAGE_FIELDS
		}
		if not participants:
			groups[data.ONLY_EMPTY].add(name)
		for doctype, member in participants:
			value = f"{doctype}:{member}"
			groups[value].add(name)
			labels[value] = names.get((doctype, member), member)

	duplicates = Counter(labels.values())
	for value, label in labels.items():
		if duplicates[label] > 1:
			labels[value] = f"{label} ({value})"
	return groups, labels


def group_options(groups, labels):
	options = [
		{"value": name, "label": labels.get(name, name) if name != data.ONLY_EMPTY else ""} for name in groups
	]
	return sorted(
		options, key=lambda option: (not option["label"], option["label"].casefold(), option["value"])
	)


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


def chart_range(rows, journal, expected_ends, reporting, cutoff, today):
	# Use the shared outer filter, so switching a chart's selector leaves the other axis stable.
	dates = {reporting, cutoff, *expected_ends.values()}
	recent_days = set()
	for row in rows.values():
		start, end, reason = data.plan_dates(row)
		if not reason and not cint(row.get("plan_incomplete")):
			dates.update((start, end))
			if start == end and start > date.min:
				dates.add(start - timedelta(days=1))
		events = journal.get(row.name, ())
		for event in events:
			if event.progress is not None:
				day = getdate(event.log_date)
				dates.add(day)
				if (cutoff - day).days < TREND_LOOKBACK:
					recent_days.add(day)
		if cutoff == today and row.get("progress") is not None:
			recent_days.add(today)
	if len(recent_days) > 1:
		dates.add(cutoff + timedelta(days=TREND_HORIZON))
	first, last = min(dates), max(dates)
	return (first, last) if first != last else (first, last + timedelta(days=1))


def series_for(roots, journal, expected_ends, reporting, cutoff, today, time_range):
	series = {key: [] for key in ("planned", "actual", "forecast", "trend")}
	result = {"count": len(roots), "forecast_missing": 0, "series": series}
	if not roots:
		return result

	planned = plan_series(roots, reporting, cutoff, time_range)
	actual, facts = actual_progress(roots, journal, cutoff, today)
	series.update(planned=planned, actual=actual)
	if actual[-1][1] is not None:
		series["forecast"], result["forecast_missing"] = forecast_series(
			facts, expected_ends, reporting, cutoff
		)
		series["trend"] = trend_series(actual, cutoff)
	if actual[-1][0] != str(cutoff):
		actual.append([str(cutoff), actual[-1][1]])
	return result


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
	since = date.fromordinal(max(date.min.toordinal(), cutoff.toordinal() - TREND_LOOKBACK + 1))
	recent = [
		(date.fromisoformat(day), value) for day, value in observed if day >= str(since) and value is not None
	]
	if len(recent) < 2:
		return []
	(first_day, first), (last_day, last) = recent[0], recent[-1]
	rate = (last - first) / (last_day - first_day).days
	horizon = TREND_HORIZON
	if rate:
		room = 100 - last if rate > 0 else last
		horizon = min(horizon, ceil(room / abs(rate)))
	points = [[str(cutoff), last]]
	if horizon:
		points.append([str(cutoff + timedelta(days=horizon)), data.numeric_progress(last + rate * horizon)])
	return points
