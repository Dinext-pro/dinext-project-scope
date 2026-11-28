"""Request filters and response shapes used by the project scope analytics UI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, TypedDict

from typing_extensions import NotRequired

ProgressPoint = list[str | float | None]
FilterValue = str | int | float | bool | None
ReportFilterValue = FilterValue | list[str]


class ResultFiltersFormInput(TypedDict, total=False):
	status: str
	status_missing: int
	deliverable_type: str
	deliverable_type_missing: int
	category: str
	category_missing: int
	responsible: str
	overdue: int


class ReportFiltersFormInput(ResultFiltersFormInput, total=False):
	project: str
	requirement: str
	specification: str
	kind: str
	kind_missing: int
	author: str
	priority: str
	requirement_importance: str
	without_results: int
	responsibility: str | list[str]
	project_role: str
	responsible_type: str
	impact_type: str
	impact_level: str
	link_doctype: str
	link: str
	from_date: str
	to_date: str
	review_from: str
	review_to: str
	review_due: int
	record_type: str
	verification_status: str
	missing_responsibility: int
	initiator: str
	implementation_responsible: str


class Participant(TypedDict):
	doctype: str
	name: str
	label: str
	image: NotRequired[str | None]


class ResultRow(TypedDict):
	id: str
	label: str
	document: NotRequired[str]
	document_type: NotRequired[str]
	project: NotRequired[str]
	status: NotRequired[str | None]
	status_tone: NotRequired[str | None]
	status_note: NotRequired[str | None]
	deliverable_type: NotRequired[str | None]
	deliverable_type_icon: NotRequired[str | None]
	deliverable_type_color: NotRequired[str | None]
	category: NotRequired[str | None]
	assignment: NotRequired[list[Participant]]
	accountable: NotRequired[list[Participant]]
	children: NotRequired[list[ResultRow]]
	context_only: NotRequired[bool]
	is_other: NotRequired[bool]
	slot_label: NotRequired[str | None]
	requires_recheck: NotRequired[int | bool]
	plan_incomplete: NotRequired[int | bool]
	forecast_incomplete: NotRequired[int | bool]
	planned_start_date: NotRequired[date | str | None]
	planned_end_date: NotRequired[date | str | None]
	expected_end_date: NotRequired[date | str | None]
	actual_end_date: NotRequired[date | datetime | str | None]
	progress: NotRequired[float | None]
	planned_progress: NotRequired[float | None]
	baseline_progress: NotRequired[float | None]
	baseline_delta: NotRequired[float | None]
	baseline_delta_direction: NotRequired[str | None]
	plan_delta: NotRequired[float | None]
	plan_delta_direction: NotRequired[str | None]


class DistributionItem(TypedDict):
	name: str
	count: int


class ResultComparison(TypedDict):
	reporting_date: str
	baseline_date: str | None
	show_plan: bool


class RootProgressResponse(TypedDict):
	count: int
	progress: float | None
	planned_progress: NotRequired[float | None]


class ProjectResultsResponse(TypedDict):
	rows: list[ResultRow]
	comparison: ResultComparison
	counts: dict[str, list[DistributionItem]]
	options: dict[str, list[DistributionItem]]
	progress: RootProgressResponse


class DeliverableProgressResponse(TypedDict):
	planned: list[ProgressPoint]
	actual: list[ProgressPoint]
	plan_step: bool
	plan_reason: str | None
	plan_incomplete: bool


class DynamicsSeries(TypedDict):
	planned: list[ProgressPoint]
	actual: list[ProgressPoint]
	forecast: list[ProgressPoint]
	trend: list[ProgressPoint]


class CategoryDynamics(TypedDict):
	count: int
	forecast_missing: int
	series: DynamicsSeries


class ResponsibleItem(TypedDict):
	value: str
	label: str
	count: int


class ResponsibleDynamics(TypedDict):
	selected: str
	items: list[ResponsibleItem]


class ProjectResultDynamicsResponse(TypedDict):
	cutoff: str
	reporting_date: str
	baseline_date: str | None
	range: list[str]
	category: CategoryDynamics
	responsible: ResponsibleDynamics


class ResponsibilityBadge(TypedDict):
	code: str
	abbreviation: str
	label: str
	color: str | None


class ReportColumn(TypedDict):
	fieldname: str
	label: str
	fieldtype: str
	width: int
	kind: str | None
	group: str | None
	group_id: str | None
	pinned: NotRequired[str]
	assignee: NotRequired[Participant]
	scope_report: NotRequired[str]


# Matrix rows add dynamic keys whose names are generated from the columns.
ReportRows = list[dict[str, Any]]
ReportResponse = tuple[list[ReportColumn], ReportRows]
ScriptReportResponse = tuple[list[ReportColumn], ReportRows, None, None, None, bool]
