// Copyright (c) 2026, Dinext and Contributors
// See license.txt

frappe.ui.form.on("Project Deliverable Type Element", {
	element_type(_frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		return frappe.model.set_value(cdt, cdn, {
			filter_doctype: {
				Task: "Task Type",
				"Project Deliverable": "Project Deliverable Type",
			}[row.element_type],
			filter_type: null,
		});
	},
});
