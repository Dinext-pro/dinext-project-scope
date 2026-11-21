frappe.ui.form.on("Project Constraints Template", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		frm.add_custom_button(__("Apply Constraints Template"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Apply Constraints Template"),
				fields: [
					{
						fieldname: "project",
						fieldtype: "Link",
						options: "Project",
						label: __("Project"),
						reqd: 1,
					},
				],
				primary_action_label: __("Preview Template Application"),
				primary_action: ({ project }) => {
					dialog.hide();
					frappe.route_options = { scope_constraint_template: frm.doc.name };
					frappe.set_route("Form", "Project", project);
				},
			});
			dialog.show();
		});
	},
});

frappe.ui.form.on("Project Constraint", {
	project_constraints_add(frm, cdt, cdn) {
		if (frm.doctype === "Project Constraints Template")
			frappe.model.set_value(cdt, cdn, "status", "Template");
	},
});
