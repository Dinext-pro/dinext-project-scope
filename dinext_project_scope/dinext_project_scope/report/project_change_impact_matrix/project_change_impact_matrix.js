frappe.query_reports["Project Change Impact Matrix"] = {
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
			fieldname: "impact_type",
			label: __("Impact type"),
			fieldtype: "Link",
			options: "Project Change Relation Type",
			only_select: true,
		},
		{
			fieldname: "impact_level",
			label: __("Level"),
			fieldtype: "Select",
			options: [
				...["", "Strong", "Moderate", "Weak"].map((value) => ({
					value,
					label: value ? __(value) : "",
				})),
				{ value: "__dinext_scope_no_value__", label: __("Level not specified") },
			],
		},
		{
			fieldname: "link_doctype",
			label: __("Object type"),
			fieldtype: "Select",
			options: [
				"",
				"Project Scope",
				"Project Deliverable",
				"Project Risk",
				"Project Requirement",
				"Project Constraint",
				"Account",
				"Project Role",
				"Task",
			].map((value) => ({ value, label: value ? __(value) : "" })),
		},
		{
			fieldname: "link",
			label: __("Related object"),
			fieldtype: "Dynamic Link",
			options: "link_doctype",
			only_select: true,
			get_options: () => frappe.query_report.get_filter_value("link_doctype"),
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "impact",
				},
			}),
		},
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
