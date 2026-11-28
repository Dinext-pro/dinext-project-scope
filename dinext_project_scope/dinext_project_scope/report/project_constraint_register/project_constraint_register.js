frappe.query_reports["Project Constraint Register"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			only_select: true,
		},
		{
			fieldname: "record_type",
			label: __("Record type"),
			fieldtype: "Select",
			options: ["", "Constraint", "Assumption"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{
			fieldname: "category",
			label: __("Category"),
			fieldtype: "Link",
			options: "Project Deliverable Category",
			only_select: true,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "New", "Approved", "Cancelled"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{
			fieldname: "verification_status",
			label: __("Verification status"),
			fieldtype: "Select",
			options: ["", "Pending", "Confirmed", "Disproved"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},

		{
			fieldname: "responsible_type",
			label: __("Participant type"),
			fieldtype: "Select",
			options: ["", "User", "Contact"].map((value) => ({
				value,
				label: value ? __(value) : "",
			})),
		},
		{
			fieldname: "responsible",
			label: __("Responsible"),
			fieldtype: "Dynamic Link",
			options: "responsible_type",
			only_select: true,
			get_options: () => frappe.query_report.get_filter_value("responsible_type"),
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "constraint",
				},
			}),
		},
		{ fieldname: "review_due", label: __("Due for review"), fieldtype: "Check" },
		{ fieldname: "review_from", label: __("Review date from"), fieldtype: "Date" },
		{ fieldname: "review_to", label: __("Review date to"), fieldtype: "Date" },
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
