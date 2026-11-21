frappe.query_reports["Project Responsibility Matrix"] = {
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
		{
			fieldname: "responsibility",
			label: __("Responsibility"),
			fieldtype: "MultiSelectList",
			async get_data(txt) {
				const entries = await frappe.db.get_link_options(
					"Project Deliverable Responsibility",
					txt
				);
				return entries.map(({ value, label, description }) => ({
					value,
					label: frappe.utils.escape_html(label || value),
					description: frappe.utils.escape_html(description || ""),
				}));
			},
		},
		{
			fieldname: "project_role",
			label: __("Project Role"),
			fieldtype: "Link",
			options: "Project Role",
			only_select: true,
		},
		{
			fieldname: "responsible_type",
			label: __("Participant type"),
			fieldtype: "Select",
			options: ["", "User", "Contact"],
		},
		{
			fieldname: "responsible",
			label: __("Participant"),
			fieldtype: "Dynamic Link",
			options: "responsible_type",
			only_select: true,
			get_options: () => frappe.query_report.get_filter_value("responsible_type"),
			get_query: () => ({
				query: "dinext_project_scope.analytics.reports.reference_query",
				filters: {
					project: frappe.query_report.get_filter_value("project"),
					context: "assignment",
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
