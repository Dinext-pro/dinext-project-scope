(() => {
	frappe.provide("dinext.project_scope");
	if (dinext.project_scope.catalogs_configured) return;
	dinext.project_scope.catalogs_configured = true;

	for (const doctype of [
		"Project Change Relation Type",
		"Project Deliverable Category",
		"Project Deliverable Responsibility",
		"Project Deliverable Type",
		"Project Scope Type",
		"Requirement Kind",
	]) {
		const translate = (value) => (value ? __(value, null, doctype) : "");
		const titleField = doctype === "Project Deliverable Responsibility" ? "responsibility" : "name";
		const settings = (frappe.listview_settings[doctype] ||= {});
		settings.formatters = { ...settings.formatters, [titleField]: translate };

		function describe(frm) {
			const field = frm.get_field("description");
			if (!field) return;
			const original = frm.doc.description || "";
			const localized = translate(original);
			field.set_new_description(
				localized !== original && field.get_status() === "Write"
					? frappe.utils.escape_html(localized)
					: frappe.utils.escape_html(field.df.description || "")
			);
		}

		frappe.ui.form.on(doctype, {
			setup(frm) {
				const field = frm.get_field("description");
				if (field) {
					field.df.formatter = (value) =>
						frappe.form.formatters.SmallText(translate(value), field.df);
				}
			},
			refresh(frm) {
				if (!frm.is_new()) frm.page.set_title(translate(frm.doc[titleField]));
				describe(frm);
			},
			description: describe,
		});
	}
})();
