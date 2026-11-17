frappe.query_reports["Project Deliverable Register"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			only_select: true,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Not Started",
				"In Progress",
				"Acceptance",
				"Completed",
				"Cancelled",
			].map((value) => ({ value, label: value ? __(value) : "" })),
		},
		{
			fieldname: "deliverable_type",
			label: __("Deliverable type"),
			fieldtype: "Link",
			options: "Project Deliverable Type",
			only_select: true,
		},
		{
			fieldname: "category",
			label: __("Category"),
			fieldtype: "Link",
			options: "Project Deliverable Category",
			only_select: true,
		},
		{ fieldname: "overdue", label: __("Overdue only"), fieldtype: "Check" },
		{
			fieldname: "missing_responsibility",
			label: __("Missing required responsibility"),
			fieldtype: "Check",
		},
		{ fieldname: "status_missing", label: __("Without status"), fieldtype: "Check" },
	],
	onload(report) {
		return frappe
			.require([
				"/assets/dinext_project_scope/js/scope_analytics.js",
				"/assets/dinext_project_scope/js/scope_analytics_reports.js",
			])
			.then(() => window.DinextScopeReports.bind(report));
	},
};
