// Copyright (c) 2026, Dinext and Contributors
// See license.txt

(() => {
	const api = "dinext_project_scope.deliverable_templates.";
	const workQuery = "dinext_project_scope.deliverables.work_query";
	const participantQuery = "dinext_project_scope.deliverables.participant_query";

	function normalizeChoices(choices, getLabel) {
		return [
			{ label: __("Choose later"), value: "" },
			...choices.map((choice) => ({
				label: getLabel(choice),
				value: choice.key,
			})),
		];
	}

	function configureNesting(frm) {
		const items = new Map(frm.doc.deliverables.map((row) => [row.item_key, row]));
		const rows = frm.doc.elements.filter((row) => row.element_type === "Project Deliverable");
		const fields = rows.map((row, index) => ({
			fieldtype: "Select",
			fieldname: `slot_${index}`,
			default: row.nested_item_key || "",
			label: __("{0} · {1}", [items.get(row.owner_item_key).title, row.element_name]),
			options: normalizeChoices(
				Array.from(items.entries())
					.filter(
						([key, item]) =>
							key !== row.owner_item_key &&
							(!row.filter_type || row.filter_type === item.deliverable_type)
					)
					.map(([key, item]) => ({ key, title: item.title, index: item.idx })),
				(item) => `${item.title} (${item.index})`
			),
		}));
		if (!fields.length) {
			frappe.msgprint(__("The template has no elements that can link to another result."));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Configure nested results"),
			fields,
			primary_action_label: __("Apply to template"),
			async primary_action(values) {
				await Promise.all(
					rows.map((row, index) =>
						frappe.model.set_value(
							row.doctype,
							row.name,
							"nested_item_key",
							values[`slot_${index}`] || null
						)
					)
				);
				frm.refresh_field("elements");
				dialog.hide();
			},
		});
		dialog.show();
	}

	function previewProjectLinks(project, fieldname, label, doctype, current_scope = false) {
		return {
			fieldtype: "MultiSelectList",
			fieldname,
			label,
			options: doctype,
			async get_data(txt) {
				const { message } = await frappe.call({
					method: "frappe.desk.search.search_link",
					args: {
						doctype,
						txt,
						query: "dinext_project_scope.access.project_target_query",
						filters: { project, current_scope },
					},
				});
				return message || [];
			},
		};
	}

	function addManualAssignment(project, onAdd) {
		const dialog = new frappe.ui.Dialog({
			title: __("Assign responsibility"),
			fields: [
				{
					fieldtype: "Link",
					fieldname: "responsibility",
					label: __("Responsibility"),
					options: "Project Deliverable Responsibility",
					reqd: 1,
					get_query: () => ({ filters: { enabled: 1 } }),
				},
				{
					fieldtype: "Link",
					fieldname: "project_role",
					label: __("Project Role"),
					options: "Project Role",
					reqd: 1,
					get_query: () => ({ filters: { enabled: 1 } }),
					onchange: () => dialog.set_value("responsible", null),
				},
				{
					fieldtype: "Select",
					fieldname: "responsible_type",
					label: __("Participant Type"),
					options: ["User", "Contact"],
					default: "User",
					reqd: 1,
					onchange: () => dialog.set_value("responsible", null),
				},
				{
					fieldtype: "Dynamic Link",
					fieldname: "responsible",
					label: __("Participant"),
					options: "responsible_type",
					reqd: 1,
					get_query: () => ({
						query: participantQuery,
						filters: { project, project_role: dialog.get_value("project_role") },
					}),
				},
			],
			primary_action_label: __("Assign"),
			primary_action(values) {
				onAdd(values);
				dialog.hide();
			},
		});
		dialog.show();
	}

	function renderManualAssignments(dialog, group, project) {
		const wrapper = dialog.fields_dict[group.prefix + "assignments"].$wrapper;
		const rows = $("<ul>", { class: "mb-2" }).appendTo(wrapper);
		$("<button>", { type: "button", class: "btn btn-xs btn-default mb-3" })
			.text(__("Assign responsibility"))
			.on("click", () =>
				addManualAssignment(project, (value) => {
					const key = JSON.stringify(value);
					if (group.manual.has(key)) return;
					group.manual.set(key, value);
					const row = $("<li>", { class: "mb-2" }).appendTo(rows);
					$("<span>")
						.text(
							`${value.responsibility} · ${value.project_role} · ${__(
								value.responsible_type
							)} · ${value.responsible}`
						)
						.appendTo(row);
					$("<button>", { type: "button", class: "btn btn-xs btn-default ml-2" })
						.text(__("Remove"))
						.on("click", () => {
							group.manual.delete(key);
							row.remove();
						})
						.appendTo(row);
				})
			)
			.appendTo(wrapper);
	}

	function templateFields(preview, project) {
		const fields = [];
		const groups = [];
		const titles = new Map(preview.items.map((item) => [item.key, item.title]));
		preview.items.forEach((item, index) => {
			const prefix = `result_${index}_`;
			const group = {
				item,
				prefix,
				work: [],
				suggestions: [],
				internal: [],
				manual: new Map(),
			};
			groups.push(group);
			fields.push({
				fieldtype: "Section Break",
				fieldname: prefix + "section",
				label: frappe.utils.escape_html(item.title),
				collapsible: 1,
				collapsible_depends_on: index > 0 ? "eval:true" : undefined,
			});
			for (const [slotIndex, slot] of item.work.entries()) {
				const fieldname = prefix + `work_${slotIndex}`;
				if (slot.nested_item_key) {
					fields.push({ fieldtype: "HTML", fieldname });
					group.internal.push({
						fieldname,
						label: slot.element_name,
						title: titles.get(slot.nested_item_key),
					});
					continue;
				}
				fields.push({
					fieldtype: "Link",
					fieldname,
					label: frappe.utils.escape_html(slot.element_name),
					options: slot.element_type === "Other" ? slot.filter_type : slot.element_type,
					get_query: () => ({
						query: workQuery,
						filters: {
							project,
							element_type: slot.element_type,
							filter_type: slot.filter_type,
						},
					}),
				});
				group.work.push([fieldname, slot.source_element_key]);
			}

			fields.push(
				previewProjectLinks(
					project,
					prefix + "scope",
					__("Project Scope"),
					"Project Scope"
				),
				previewProjectLinks(
					project,
					prefix + "requirements",
					__("Project Requirements"),
					"Project Requirement",
					true
				),
				previewProjectLinks(
					project,
					prefix + "constraints",
					__("Constraints and assumptions"),
					"Project Constraint"
				)
			);
			for (const [suggestionIndex, suggestion] of item.responsibilities.entries()) {
				if (!suggestion.candidates.length) continue;
				const fieldname = prefix + `participant_${suggestionIndex}`;
				const defaultAssignment = item.defaults.find(
					(row) =>
						row.responsibility === suggestion.responsibility &&
						row.project_role === suggestion.project_role
				);
				const choices = suggestion.candidates.map((candidate, index) => ({
					...candidate,
					key: String(index),
				}));
				const chosen = choices.find(
					(choice) =>
						choice.doctype === defaultAssignment?.responsible_type &&
						choice.name === defaultAssignment?.responsible
				);
				fields.push({
					fieldtype: "Select",
					fieldname,
					label: __("{0} · {1}", [suggestion.responsibility, suggestion.project_role]),
					options: normalizeChoices(
						choices,
						(choice) => `${__(choice.doctype)} · ${choice.name}`
					),
					default: chosen?.key || "",
				});
				group.suggestions.push([fieldname, suggestion]);
			}
			fields.push({ fieldtype: "HTML", fieldname: prefix + "assignments" });
		});
		return { fields, groups };
	}

	function selectionFor(group, values) {
		const { prefix } = group;
		const assignments = [...group.manual.values()];
		for (const [fieldname, suggestion] of group.suggestions) {
			const selected = values[fieldname];
			if (selected === undefined || selected === "") continue;
			if (
				assignments.some(
					(row) =>
						row.responsibility === suggestion.responsibility &&
						row.project_role === suggestion.project_role
				)
			)
				continue;
			const participant = suggestion.candidates[Number(selected)];
			if (!participant) continue;
			assignments.push({
				responsibility: suggestion.responsibility,
				project_role: suggestion.project_role,
				responsible_type: participant.doctype,
				responsible: participant.name,
			});
		}
		return {
			work: Object.fromEntries(
				group.work.map(([fieldname, key]) => [key, values[fieldname] || null])
			),
			deliverable_scopes: values[prefix + "scope"] || [],
			deliverable_requirements: values[prefix + "requirements"] || [],
			deliverable_constraints: values[prefix + "constraints"] || [],
			assignments,
		};
	}

	function showTemplatePreview(frm, project, preview) {
		const { fields, groups } = templateFields(preview, project);
		const request_key = window.crypto.randomUUID();
		const dialog = new frappe.ui.Dialog({
			title: __("Preview project results"),
			size: "large",
			fields,
			primary_action_label: __("Create results"),
			async primary_action(values) {
				const selections = Object.fromEntries(
					groups.map((group) => [group.item.key, selectionFor(group, values)])
				);
				const { message } = await frappe.call({
					method: api + "apply_template",
					args: {
						project,
						template: frm.doc.name,
						token: preview.token,
						request_key,
						selections,
					},
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Project results created."), indicator: "green" });
				if (groups.length === 1 && message.created?.[groups[0].item.key]) {
					frappe.set_route(
						"Form",
						"Project Deliverable",
						message.created[groups[0].item.key]
					);
				} else {
					frappe.set_route("Form", "Project", project);
				}
			},
		});
		for (const group of groups) {
			for (const { fieldname, label, title } of group.internal) {
				$("<p>", { class: "text-muted" })
					.text(__("{0} will link to the new result {1}.", [label, title]))
					.appendTo(dialog.fields_dict[fieldname].$wrapper);
			}
			renderManualAssignments(dialog, group, project);
		}
		dialog.show();
	}

	frappe.ui.form.on("Project Deliverables Template", {
		setup(frm) {
			frm.set_query("deliverable_type", "deliverables", () => ({ filters: { enabled: 1 } }));
			frm.set_query("category", "deliverables", () => ({ filters: { enabled: 1 } }));
			const grid = frm.fields_dict.elements.grid;
			grid.df.cannot_add_rows = true;
			grid.df.cannot_delete_rows = true;
		},
		refresh(frm) {
			if (frm.is_new() || frm.doc.docstatus === 2) return;
			if (frm.doc.docstatus === 0 && frm.has_perm("write")) {
				frm.add_custom_button(__("Configure nested results"), () => {
					if (frm.is_dirty()) {
						frappe.msgprint(__("Save the template before configuring its work."));
						return;
					}
					configureNesting(frm);
				});
			}
			frm.add_custom_button(__("Apply to project"), () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save the template before applying it."));
					return;
				}
				frappe.prompt(
					{
						fieldtype: "Link",
						options: "Project",
						fieldname: "project",
						label: __("Project"),
						reqd: 1,
					},
					async ({ project }) => {
						const { message } = await frappe.call({
							method: api + "preview_template",
							args: { project, template: frm.doc.name },
						});
						showTemplatePreview(frm, project, message);
					},
					__("Apply result template"),
					__("Preview")
				);
			});
		},
	});

	frappe.ui.form.on("Project Deliverable Template Item", {
		deliverables_add(_frm, cdt, cdn) {
			if (!locals[cdt][cdn].item_key) {
				frappe.model.set_value(cdt, cdn, "item_key", window.crypto.randomUUID());
			}
		},
	});
})();
