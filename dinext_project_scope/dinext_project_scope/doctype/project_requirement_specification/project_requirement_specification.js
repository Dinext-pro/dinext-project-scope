frappe.ui.form.on("Project Requirement Specification", {
	async refresh(frm) {
		await frappe.require([
			"/assets/dinext_project_scope/js/requirement_forms.js",
			"/assets/dinext_project_scope/css/requirement_forms.css",
		]);
		return window.dinext_project_scope.requirement_forms.refreshSpecification(frm);
	},
});
