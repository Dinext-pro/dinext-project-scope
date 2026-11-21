// Copyright (c) 2026, Dinext and contributors
// For license information, please see license.txt

frappe.ui.form.on("Project Requirement", {
	setup(frm) {
		frm.set_query("parent_project_requirement", () => ({
			filters:
				frm.doc.status === "Template"
					? {
							status: "Template",
							project: ["is", "not set"],
							is_group: 1,
							name: ["!=", frm.doc.name],
					  }
					: {
							project: frm.doc.project || "",
							status: ["!=", "Template"],
							is_group: 1,
							name: ["!=", frm.doc.name],
					  },
		}));
	},
	status(frm) {
		frm.toggle_reqd("project", frm.doc.status !== "Template");
		frm.toggle_display("project", frm.doc.status !== "Template");
		if (frm.is_new() && frm.doc.status === "Template" && frm.doc.project) {
			return frm.set_value({ project: null, parent_project_requirement: null });
		}
	},
	async refresh(frm) {
		frm.trigger("status");
		frm.set_df_property("project", "read_only", !frm.is_new());
		if (
			!frm.is_new() &&
			frm.perm[0]?.write &&
			frm.doc.responsible === frappe.session.user &&
			!["Done", "Template", "Cancelled"].includes(frm.doc.status)
		) {
			frm.add_custom_button(__("Mark Done", null, "Project Requirement"), async () => {
				await frm.set_value("status", "Done");
				await frm.save();
			});
		}
		await frappe.require([
			"/assets/dinext_project_scope/js/requirement_forms.js",
			"/assets/dinext_project_scope/css/requirement_forms.css",
		]);
		return window.dinext_project_scope.requirement_forms.refreshRequirement(frm);
	},
});
