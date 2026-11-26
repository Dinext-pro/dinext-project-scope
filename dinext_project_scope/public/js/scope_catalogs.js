(() => {
	frappe.provide("dinext.project_scope");
	if (dinext.project_scope.catalogs_configured) return;
	dinext.project_scope.catalogs_configured = true;
	const descriptions = new WeakMap();

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

		frappe.ui.form.on(doctype, {
			setup(frm) {
				const field = frm.get_field("description");
				if (!field) return;
				const readOnly = field.df.read_only;
				const editLabel = __("Edit description");
				const edit = $('<button type="button" class="btn btn-default btn-xs ml-2">')
					.attr({ title: editLabel, "aria-label": editLabel })
					.html(frappe.utils.icon("edit", "xs"))
					.hide()
					.on("click", () => {
						frm.set_df_property("description", "read_only", readOnly);
						edit.hide();
						field.$input.trigger("focus");
					});
				field.$wrapper.find(".control-label").after(edit);
				field.df.formatter = (value) =>
					frappe.form.formatters.SmallText(frappe.utils.escape_html(translate(value)));
				descriptions.set(frm, { field, edit, readOnly });
			},
			refresh(frm) {
				if (!frm.is_new()) frm.page.set_title(translate(frm.doc[titleField]));

				const description = descriptions.get(frm);
				if (!description) return;
				const { field, edit, readOnly } = description;
				const original = frm.doc.description || "";
				const translated = !frm.is_new() && translate(original) !== original;
				const writable =
					frappe.perm.get_field_display_status({ ...field.df, read_only: readOnly }, frm.doc, frm.perm) ===
					"Write";
				frm.set_df_property("description", "read_only", translated ? 1 : readOnly);
				edit.toggle(translated && writable);
			},
		});
	}
})();
