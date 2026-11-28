// Copyright (c) 2026, Dinext and Contributors
// See license.txt

frappe.ui.form.on("Project Scope Settings", {
	setup(frm) {
		frm.set_query("result_tree_responsibilities", () => ({ filters: { enabled: 1 } }));
	},
});
