from datetime import date, datetime
from io import BytesIO
from itertools import groupby
from numbers import Real

import frappe
from frappe import _
from frappe.desk.query_report import get_report_doc
from frappe.desk.utils import provide_binary_file
from frappe.utils import flt, get_datetime, getdate
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Font, PatternFill

from dinext_project_scope.analytics import data
from dinext_project_scope.analytics.reports import REPORTS, column, dataset, flatten_rows

HEADER_FILL = PatternFill("solid", fgColor="FFDCE8F2")
GROUP_FILL = PatternFill("solid", fgColor="FFEAF0F4")
DELTA_COLORS = {"up": "FF176C3F", "flat": "FF525A65", "down": "FFA32734"}
STATE_FILLS = {
	"red": "F8D3D3",
	"yellow": "FDECAC",
	"green": "CFEBD6",
	"light-green": "E5F2D9",
	"cyan": "D2EAF5",
	"blue": "D7E4FC",
	"gray": "DDE1E5",
}
BODY_ALIGNMENT = Alignment(vertical="top", wrap_text=True)


def rgb(color):
	value = str(color or "").removeprefix("#")
	if len(value) == 6 and all(char in "0123456789abcdefABCDEF" for char in value):
		return "FF" + value.upper()
	return None


def write_cell(cell, value):
	if value is None:
		return
	if isinstance(value, (date, datetime, Real, CellRichText)):
		cell.value = value
	else:
		cell.value = str(value)
		cell.data_type = "s"


def write_header(cell, value):
	write_cell(cell, value)
	cell.font = Font(bold=True)
	cell.fill = HEADER_FILL
	cell.alignment = Alignment(vertical="center", wrap_text=True)


def rich_codes(entries):
	segments = []
	for index, entry in enumerate(entries):
		if index:
			segments.append(" / ")
		color = rgb(entry.get("color"))
		segments.append(
			TextBlock(InlineFont(color=color, b=True), str(entry["code"])) if color else str(entry["code"])
		)
	return CellRichText(segments)


def write_table_header(sheet, columns):
	grouped = any(column.get("group_id") for column in columns)
	for group_id, iterator in groupby(enumerate(columns, start=1), key=lambda item: item[1].get("group_id")):
		items = list(iterator)
		if group_id:
			first, last = items[0][0], items[-1][0]
			if first != last:
				sheet.merge_cells(start_row=1, end_row=1, start_column=first, end_column=last)
			write_header(sheet.cell(1, first), items[0][1]["group"])
		for index, column in items:
			header_row = 2 if grouped and group_id else 1
			if grouped and not group_id:
				sheet.merge_cells(start_row=1, end_row=2, start_column=index, end_column=index)
			write_header(sheet.cell(header_row, index), column["label"])
			sheet.column_dimensions[sheet.cell(header_row, index).column_letter].width = min(
				58, column["width"] / 7
			)
	for number in range(1, 3 if grouped else 2):
		sheet.row_dimensions[number].height = 28
	return 3 if grouped else 2


def write_report_value(cell, row, column, legend):
	field = column["fieldname"]
	kind = column.get("kind")
	value = row.get(field)
	document_type = row.get("document_type")
	if kind in {"raci", "badges"}:
		entries = row.get("cells", {}).get(field, []) if kind == "raci" else value
		if entries:
			write_cell(cell, rich_codes(entries))
			legend.update({entry["code"]: entry for entry in entries})
		return
	if kind == "impact":
		impact = row.get("cells", {}).get(field)
		if impact and (color := rgb(impact.get("color"))):
			cell.fill = PatternFill("solid", fgColor=color)
			cell.font = Font(bold=True, color="FF161616" if impact["level"] == "Moderate" else "FFFFFFFF")
	elif kind == "trace_state":
		parts = [_(value, context=document_type)] if value else []
		if row.get("progress") is not None:
			parts.append(f"{flt(row['progress']):.2f}".rstrip("0").rstrip(".") + "%")
		if row.get("status_note"):
			parts.append(_(row["status_note"]))
		if row.get("approval_stale"):
			parts.append(_("Reapproval required"))
		value = " · ".join(parts)
	elif kind == "accountable":
		if document_type == data.DELIVERABLE:
			value = " / ".join(f"{member['label']} ({_(member['doctype'])})" for member in value or []) or _(
				"Responsible person not assigned"
			)
	elif kind == "status" and value:
		value = _(value, context=document_type)
	if kind in {"status", "trace_state"} and (color := STATE_FILLS.get(row.get("status_tone"))):
		cell.fill = PatternFill("solid", fgColor=rgb(color))
	if kind == "progress" and value is not None:
		value = flt(value) / 100
		cell.number_format = "0.##%"
	if kind == "delta" and value is not None:
		cell.number_format = "+0.##;-0.##;0"
		if color := DELTA_COLORS.get(row.get(f"{field}_direction")):
			cell.font = Font(color=color, bold=True)
	if kind == "assignment":
		value = " / ".join(member["label"] for member in value or ()) or None
	if kind in {"date", "plan_date"} and value:
		value = getdate(value)
		cell.number_format = "yyyy-mm-dd"
	elif kind == "plan_date" and document_type == data.DELIVERABLE:
		value = _("No planned date")
	elif kind == "datetime" and value:
		value = get_datetime(value)
		cell.number_format = "yyyy-mm-dd hh:mm:ss"
	write_cell(cell, value)


def add_impact_details(workbook, columns, rows):
	if not any(row.get("cells") for row in rows):
		return
	sheet = workbook.create_sheet(_("Impact details")[:31])
	fields = [
		("document", _("Request ID"), 21),
		("label", _("Change request"), 29),
		("impact_label", _("Impact type"), 20),
		("level", _("Level"), 20),
		("direction", _("Direction"), 17),
		("estimation", _("Estimate"), 20),
		("uom", _("Unit of measure"), 19),
		("explanation", _("Explanation"), 48),
		("link_doctype", _("Object type"), 22),
		("link", _("Related object"), 26),
		("matched", _("Matched filters"), 20),
	]
	for index, (_key, header, width) in enumerate(fields, start=1):
		cell = sheet.cell(1, index)
		write_header(cell, header)
		sheet.column_dimensions[cell.column_letter].width = width
	sheet.freeze_panes = "A2"
	next_row = 2
	for request in rows:
		for column in columns:
			field = column["fieldname"]
			for entry in request.get("cells", {}).get(field, {}).get("details", ()):
				record = {
					**entry,
					"document": request["document"],
					"label": request["label"],
					"impact_label": column["label"],
					"level": _(entry["level"]) if entry.get("level") else _("Level not specified"),
					"direction": _(entry["direction"]) if entry.get("direction") else None,
					"link": _("Related object unavailable")
					if entry.get("link_unavailable")
					else entry.get("link"),
					"matched": _("Yes") if entry.get("matched") else None,
				}
				for index, (key, _header, _width) in enumerate(fields, start=1):
					cell = sheet.cell(next_row, index)
					write_cell(cell, record.get(key))
					cell.alignment = BODY_ALIGNMENT
				next_row += 1
	sheet.auto_filter.ref = sheet.dimensions


def make_workbook(report_name, columns, rows):
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = _("Report")[:31]
	start_row = write_table_header(sheet, columns)
	sheet.freeze_panes = f"B{start_row}"
	legend = {}
	for index, row in enumerate(rows, start=start_row):
		depth = min(row.get("depth", 0), 7)
		if depth:
			sheet.row_dimensions[index].outlineLevel = depth
		for column_index, column in enumerate(columns, start=1):
			cell = sheet.cell(index, column_index)
			write_report_value(cell, row, column, legend)
			if row.get("is_group"):
				cell.fill = GROUP_FILL
				cell.font = Font(bold=True)
			cell.alignment = (
				Alignment(vertical="top", wrap_text=True, indent=depth)
				if column_index == 1 and depth
				else BODY_ALIGNMENT
			)
	if legend:
		legend_sheet = workbook.create_sheet(_("Legend")[:31])
		legend_sheet.column_dimensions["A"].width = 16
		legend_sheet.column_dimensions["B"].width = 42
		write_header(legend_sheet["A1"], _("Code"))
		write_header(legend_sheet["B1"], _("Responsibility"))
		for index, (code, entry) in enumerate(sorted(legend.items()), start=2):
			cell = legend_sheet.cell(index, 1)
			write_cell(cell, code)
			cell.font = Font(color=rgb(entry.get("color")), bold=True)
			cell.alignment = BODY_ALIGNMENT
			label = legend_sheet.cell(index, 2)
			write_cell(label, entry["label"])
			label.alignment = BODY_ALIGNMENT
	if report_name == "Project Change Impact Matrix":
		add_impact_details(workbook, columns, rows)
	buffer = BytesIO()
	workbook.save(buffer)
	return buffer.getvalue()


@frappe.whitelist(methods=["GET"])
def download(report_name, filters=None):
	if not isinstance(report_name, str) or report_name not in REPORTS:
		frappe.throw(_("This report is unavailable."))
	report = get_report_doc(report_name)
	frappe.has_permission(report.ref_doctype, "export", throw=True)
	columns, rows = dataset(report_name, filters)
	provide_binary_file(frappe.scrub(report_name), "xlsx", make_workbook(report_name, columns, rows))

@frappe.whitelist(methods=["GET"])
def download_project_results(project, filters=None, reporting_date=None, baseline_date=None, show_plan=0):
	frappe.has_permission(data.DELIVERABLE, "export", throw=True)
	view = data.project_results(project, filters, reporting_date, baseline_date, show_plan)
	comparison = view["comparison"]
	columns = [
		column("label", _("Deliverable / Work"), width=285),
		column("status", _("Status"), kind="status", width=155),
		column("deliverable_type", _("Type")),
		column("category", _("Category"), width=150),
		column("progress", _("Progress"), kind="progress", width=105),
	]
	if comparison["baseline_date"]:
		columns.extend(
			[
				column("baseline_progress", _("Baseline progress"), kind="progress"),
				column("baseline_delta", _("Δ from baseline"), kind="delta"),
			]
		)
	if comparison["show_plan"]:
		columns.extend(
			[
				column(
					"planned_progress", _("Planned progress", context="Dinext.ProjectScope.Comparison"),
					kind="progress",
				),
				column("plan_delta", _("Δ from plan"), kind="delta"),
			]
		)
	columns.extend(
		[
			column("assignment", _("Assignment"), kind="assignment", width=170),
			column("planned_end_date", _("Planned end", context="Dinext.ProjectScope.Dates"), kind="plan_date"),
			column("expected_end_date", _("Expected end", context="Dinext.ProjectScope.Dates"), kind="date"),
			column("actual_end_date", _("Actual end", context="Dinext.ProjectScope.Dates"), kind="date"),
		]
	)
	rows = list(flatten_rows(view["rows"]))
	provide_binary_file("project-results", "xlsx", make_workbook("Project Results", columns, rows))
