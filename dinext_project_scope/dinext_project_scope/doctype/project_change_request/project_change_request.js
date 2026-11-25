(() => {
	const doctype = "Project Change Request";
	const projectQuery = "dinext_project_scope.access.project_target_query";
	const content = [
		"title",
		"project",
		"initiator",
		"description",
		"reason",
		"alternative",
		"change_relations",
	];

	function showHistory(frm) {
		frappe
			.call({
				method: "dinext_project_scope.changes.approval_history",
				args: { name: frm.doc.name },
			})
			.then(({ message }) => {
				const dialog = new frappe.ui.Dialog({
					title: __("Approval History"),
					fields: [{ fieldname: "history", fieldtype: "HTML" }],
				});
				const list = document.createElement("ul");
				for (const row of message || []) {
					const item = document.createElement("li");
					const date = row.decided_at || row.submitted_at;
					const details = document.createElement("details");
					const summary = document.createElement("summary");
					summary.textContent = [
						row.round_number,
						__(row.decision, null, "Project Scope Approval"),
						date && frappe.datetime.str_to_user(date),
						row.decision_reason,
					]
						.filter(Boolean)
						.join(" · ");
					details.append(summary);
					if (row.snapshot?.description) {
						const description = document.createElement("p");
						description.textContent = row.snapshot.description;
						details.append(description);
					}
					const impacts = document.createElement("ul");
					for (const relation of row.snapshot?.change_relations || []) {
						const impact = document.createElement("li");
						impact.textContent = [
							relation.type,
							__(relation.level),
							relation.estimation,
							relation.uom,
							relation.explanation,
							relation.link,
						]
							.filter(Boolean)
							.join(" · ");
						impacts.append(impact);
					}
					if (impacts.childElementCount) details.append(impacts);
					item.append(details);
					list.append(item);
				}
				if (!list.childElementCount) list.textContent = __("No approval rounds.");
				dialog.fields_dict.history.wrapper.append(list);
				dialog.show();
			});
	}

	frappe.ui.form.on(doctype, {
		setup(frm) {
			frm.set_query("link", "change_relations", (_doc, cdt, cdn) => ({
				query: projectQuery,
				filters: { project: frm.doc.project, current_scope: 1 },
			}));
			frm.set_query("reference_name", "implementation_items", () => ({
				query: projectQuery,
				filters: { project: frm.doc.project, current_scope: 1 },
			}));
			frm.set_query("implementation_responsible", () => ({
				query: "dinext_project_scope.changes.project_user_query",
				filters: { project: frm.doc.project },
			}));
		},
		refresh(frm) {
			const editable = frm.is_new() || ["Draft", "Rejected"].includes(frm.doc.status);
			for (const field of content)
				frm.toggle_enable(field, editable && (field !== "project" || frm.is_new()));
			frm.toggle_enable(
				["implementation_date", "implementation_note", "implementation_items"],
				frm.doc.status === "Approved" && !frm.doc.implemented_at
			);
			if (frm.is_new()) return;
			frm.add_custom_button(__("Approval History"), () => showHistory(frm));
			frm.add_custom_button(__("Project Change Impact Matrix"), () => {
				frappe.route_options = { project: frm.doc.project, request: frm.doc.name };
				frappe.set_route("query-report", "Project Change Impact Matrix");
			});
		},
	});

	frappe.ui.form.on("Change Relation", {
		async type(frm, cdt, cdn) {
			const row = frappe.get_doc(cdt, cdn);
			const type = row.type;
			const response = type
				? await frappe.db.get_value("Project Change Relation Type", type, [
						"link_doctype",
						"uom",
				  ])
				: null;
			if (row.type !== type) return;
			await frappe.model.set_value(cdt, cdn, {
				link_doctype: response?.message?.link_doctype || "",
				uom: response?.message?.uom || "",
				link: "",
			});
		},
		link_doctype(frm, cdt, cdn) {
			frappe.model.set_value(cdt, cdn, "link", "");
		},
	});
})();
