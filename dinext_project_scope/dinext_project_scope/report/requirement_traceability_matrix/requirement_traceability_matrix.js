frappe.query_reports["Requirement Traceability Matrix"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			only_select: true,
			reqd: 1,
		},
		{
			fieldname: "requirement",
			label: __("Project Requirement"),
			fieldtype: "Link",
			options: "Project Requirement",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.access.project_target_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					current_scope: 1,
				},
			}),
		},
		{
			fieldname: "specification",
			label: __("Specification"),
			fieldtype: "Link",
			options: "Project Requirement Specification",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.access.project_target_query",
				filters: { project: frappe.query_report.get_filter_value("project") },
			}),
		},
		{
			fieldname: "kind",
			label: __("Requirement category"),
			fieldtype: "Link",
			options: "Requirement Kind",
			only_select: true,
		},
		{
			fieldname: "author",
			label: __("Author"),
			fieldtype: "Link",
			options: "Contact",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "requirement",
				},
			}),
		},
		{
			fieldname: "responsible",
			label: __("Responsible"),
			fieldtype: "Link",
			options: "User",
			only_select: true,
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "requirement",
				},
			}),
		},
		{
			fieldname: "priority",
			label: __("Priority"),
			fieldtype: "Select",
			options: ["", "Low", "Medium", "High", "Critical"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{
			fieldname: "requirement_importance",
			label: __("Importance"),
			fieldtype: "Select",
			options: ["", "Must Have", "Should Have", "Nice to Have"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "New", "Approved", "In Progress", "Done", "Cancelled"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{ fieldname: "without_results", label: __("Without deliverables"), fieldtype: "Check" },
		{ fieldname: "kind_missing", label: __("Without category"), fieldtype: "Check" },
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
