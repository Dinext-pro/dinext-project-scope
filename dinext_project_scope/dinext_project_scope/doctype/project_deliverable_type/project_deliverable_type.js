// Copyright (c) 2026, Dinext and Contributors
// See license.txt

frappe.ui.form.on("Project Deliverable Type", {
	setup(frm) {
		frm.set_query("filter_type", "elements", (_doc, cdt, cdn) =>
			locals[cdt][cdn].element_type === "Other"
				? { filters: { istable: 0, issingle: 0, is_virtual: 0 } }
				: {}
		);
	},
});

frappe.ui.form.on("Project Deliverable Type Element", {
	element_type(_frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		return frappe.model.set_value(cdt, cdn, {
			filter_doctype: {
				Task: "Task Type",
				"Project Deliverable": "Project Deliverable Type",
				Other: "DocType",
			}[row.element_type],
			filter_type: null,
		});
	},
});
