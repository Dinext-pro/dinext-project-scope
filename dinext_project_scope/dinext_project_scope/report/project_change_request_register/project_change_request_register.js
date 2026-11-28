frappe.query_reports["Project Change Request Register"] = {
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
				"Draft",
				"In Review",
				"Approved",
				"Rejected",
				"Implemented",
				"Cancelled",
			].map((value) => ({ value, label: value ? __(value) : "" })),
		},
		{
			fieldname: "initiator",
			label: __("Initiator"),
			fieldtype: "Link",
			options: "Contact",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "change",
				},
			}),
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{
			fieldname: "implementation_responsible",
			label: __("Implementation responsible"),
			fieldtype: "Link",
			options: "User",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "change",
				},
			}),
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
