// Copyright (c) 2026, Dinext and Contributors
// See license.txt

(() => {
	const api = "dinext_project_scope.deliverables.";
	const workingStatuses = [
		"Not Started",
		"In Progress",
		"Acceptance",
		"Completed",
		"Cancelled",
		"Template",
	];
	const projectLinks = {
		deliverable_scopes: false,
		deliverable_requirements: true,
		deliverable_constraints: false,
	};

	function afterResponse(frm, name, callback) {
		if (frm.doc.name === name) callback();
	}

	function setupQueries(frm) {
		frm.set_query("category", () => ({ filters: { enabled: 1 } }));
		frm.set_query("deliverable_type", () => ({ filters: { enabled: 1 } }));
		frm.set_query("responsibility", "deliverable_responsibles", () => ({
			filters: { enabled: 1 },
		}));
		frm.set_query("project_role", "deliverable_responsibles", () => ({
			filters: { enabled: 1 },
		}));
		frm.set_query("element", "table_xuct", (_doc, cdt, cdn) => ({
			query: api + "work_query",
			filters: {
				project: frm.doc.project,
				deliverable: frm.is_new() ? null : frm.doc.name,
				filter_type: locals[cdt][cdn].filter_type,
			},
		}));
		frm.set_query("responsible", "deliverable_responsibles", (_doc, cdt, cdn) => ({
			query: api + "participant_query",
			filters: { project: frm.doc.project, project_role: locals[cdt][cdn].project_role },
		}));
		for (const [field, current_scope] of Object.entries(projectLinks)) {
			frm.set_query(field, () => ({
				query: "dinext_project_scope.access.project_target_query",
				filters: { project: frm.doc.project, current_scope },
			}));
		}
		const grid = frm.fields_dict.table_xuct.grid;
		grid.cannot_add_rows = true;
		grid.is_sortable = () => false;
	}

	async function loadDefaults(frm, { work = false, assignments = false } = {}) {
		if (!frm.is_new() || !frm.doc.project || frm.doc.status === "Template") return;
		const { name, project, deliverable_type, category } = frm.doc;
		const { message } = await frappe.call({
			method: api + "new_result_defaults",
			args: { project, deliverable_type, category },
		});
		if (!frm.is_new() || frm.doc.name !== name || frm.doc.project !== project) return;

		if (work && frm.doc.deliverable_type === deliverable_type) {
			frm.clear_table("table_xuct");
			for (const row of message.work) frm.add_child("table_xuct", row);
			frm.refresh_field("table_xuct");
		}
		if (assignments && frm.doc.category === category) {
			if (!frm.doc.deliverable_responsibles?.length) {
				for (const row of message.defaults) frm.add_child("deliverable_responsibles", row);
				frm.refresh_field("deliverable_responsibles");
			}
			renderSuggestions(
				frm,
				message.responsibilities,
				frm.doc.deliverable_responsibles || []
			);
		}
	}

	function renderSuggestions(frm, suggestions, defaults) {
		const wrapper = frm.fields_dict.acceptance_html?.$wrapper;
		if (!wrapper) return;
		wrapper.empty();
		const pending = suggestions.filter(
			(suggestion) =>
				!defaults.some(
					(row) =>
						row.responsibility === suggestion.responsibility &&
						row.project_role === suggestion.project_role
				)
		);
		if (!pending.length) return;
		$("<p>", { class: "text-muted" }).text(__("Suggested responsibilities")).appendTo(wrapper);
		for (const suggestion of pending) {
			const label = __("{0} · {1}", [suggestion.responsibility, suggestion.project_role]);
			if (!suggestion.candidates.length) {
				$("<p>", { class: "text-muted" })
					.text(__("No current participants for {0}", [label]))
					.appendTo(wrapper);
				continue;
			}
			const choices = suggestion.candidates.map((candidate, index) => ({
				label: `${__(candidate.doctype)} · ${candidate.name}`,
				value: String(index),
			}));
			$("<button>", { type: "button", class: "btn btn-default btn-xs mr-2 mb-2" })
				.text(label)
				.on("click", () =>
					frappe.prompt(
						{
							fieldtype: "Select",
							fieldname: "candidate",
							label: __("Participant"),
							options: choices,
							reqd: 1,
						},
						({ candidate }) => {
							const selected = suggestion.candidates[Number(candidate)];
							if (!selected) return;
							const row =
								frm.doc.deliverable_responsibles?.find(
									(existing) =>
										existing.responsibility === suggestion.responsibility &&
										existing.project_role === suggestion.project_role
								) || frm.add_child("deliverable_responsibles");
							Object.assign(row, {
								responsibility: suggestion.responsibility,
								project_role: suggestion.project_role,
								responsible_type: selected.doctype,
								responsible: selected.name,
							});
							frm.dirty();
							frm.refresh_field("deliverable_responsibles");
						},
						label,
						__("Assign")
					)
				)
				.appendTo(wrapper);
		}
	}

	function renderReadiness(frm, result) {
		const wrapper = frm.fields_dict.acceptance_html?.$wrapper;
		if (!wrapper) return;
		wrapper.empty();
		if (!Array.isArray(result.blocked_work)) return;

		const notes = [];
		if (frm.doc.requires_recheck) notes.push(__("Requires recheck"));
		if (!frm.doc.planned_start_date && !frm.doc.planned_end_date)
			notes.push(__("No planned dates"));
		else if (frm.doc.plan_incomplete) notes.push(__("Plan dates are incomplete"));
		if (frm.doc.forecast_incomplete) notes.push(__("Forecast dates are incomplete"));
		if (result.zero_weight) notes.push(__("No work weights count towards progress"));
		if (result.missing_approver)
			notes.push(
				__(
					"Assign one active user to the project manager role before submitting for approval."
				)
			);
		if (result.accepted_at) {
			const date = frappe.datetime.str_to_user(String(result.accepted_at).split(" ")[0]);
			notes.push(__("Acceptance decision on {0}", [date]));
		}

		const issues = {
			missing: __("Link the required work for {0}."),
			incomplete: __("Complete the linked work for {0}."),
			recheck: __("Confirm the changed result linked to {0} again."),
		};
		const blockers = result.blocked_work.map(([label, reason]) => __(issues[reason], [label]));
		if (result.missing_responsibilities.length) {
			blockers.push(
				__("Assign participants for required responsibilities ({0}).", [
					result.missing_responsibilities.join(", "),
				])
			);
		}
		if (result.stale_assignments.length) {
			const rows = frm.doc.deliverable_responsibles.filter((row) =>
				result.stale_assignments.includes(row.name)
			);
			blockers.push(
				__("Check past assignments for {0}.", [
					rows.map((row) => row.responsible).join(", "),
				])
			);
		}

		if (notes.length) {
			$("<p>", { class: frm.doc.requires_recheck ? "text-warning" : "text-muted" })
				.text(notes.join(" · "))
				.appendTo(wrapper);
		}
		if (blockers.length) {
			const list = $("<ul>", { class: "mb-2" }).appendTo(wrapper);
			for (const blocker of blockers) $("<li>").text(blocker).appendTo(list);
		} else if (!result.missing_approver && frm.doc.status === "Acceptance") {
			$("<p>").text(__("Work is ready for acceptance.")).appendTo(wrapper);
		}
		renderLinkedWork(frm, wrapper, result.work);
	}

	function renderLinkedWork(frm, wrapper, work) {
		if (!work.length) return;
		const slots = new Map(frm.doc.table_xuct.map((row) => [row.source_element_key, row]));
		const details = $("<details>", { class: "mb-2" }).appendTo(wrapper);
		$("<summary>").text(__("Linked work")).appendTo(details);
		const list = $("<ul>", { class: "mt-2 mb-2" }).appendTo(details);
		for (const item of work) {
			const slot = slots.get(item.key);
			if (!slot) continue;
			const row = $("<li>").appendTo(list);
			$("<a>", { href: frappe.utils.get_form_link(slot.element_type, slot.element) })
				.text(slot.element_name)
				.appendTo(row);
			const state = [
				__(item.status, null, slot.element_type),
				format_number(item.progress || 0) + "%",
			];
			if (item.planned_end_date)
				state.push(
					__("Plan to {0}", [frappe.datetime.str_to_user(item.planned_end_date)])
				);
			if (item.expected_end_date)
				state.push(
					__("Expected on {0}", [frappe.datetime.str_to_user(item.expected_end_date)])
				);
			if (item.actual_end_date)
				state.push(
					__("Finished on {0}", [frappe.datetime.str_to_user(item.actual_end_date)])
				);
			$("<span>", { class: "text-muted" })
				.text(" · " + state.join(" · "))
				.appendTo(row);
		}
	}

	function confirmStructure(frm, preview) {
		if (!preview.changes.length && preview.deliverable_type === frm.doc.deliverable_type) {
			frappe.show_alert({
				message: __("The saved structure matches the result type."),
				indicator: "green",
			});
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Review result structure"),
			fields: [{ fieldname: "changes", fieldtype: "HTML" }],
			primary_action_label: __("Update structure"),
			async primary_action() {
				await frappe.call({
					method: api + "apply_structure",
					args: {
						deliverable: frm.doc.name,
						deliverable_type: preview.deliverable_type,
						token: preview.token,
					},
					freeze: true,
				});
				dialog.hide();
				await frm.reload_doc();
			},
		});
		const content = dialog.fields_dict.changes.$wrapper;
		const list = $("<ul>").appendTo(content);
		const workType = (row) =>
			row.filter_type
				? `${__(row.element_type)} · ${row.filter_type}`
				: __(row.element_type);
		const describe = (row) =>
			[
				row.element_name,
				workType(row),
				row.is_optional
					? __("Optional", null, "Project Deliverable")
					: __("Required", null, "Project Deliverable"),
				row.element,
			]
				.filter(Boolean)
				.join(" · ");
		for (const { action, before, after, previous_position, position } of preview.changes) {
			const detail =
				before && after
					? `${describe(before)} → ${describe(after)}`
					: describe(before || after);
			const movement =
				previous_position && previous_position !== position
					? ` (${previous_position} → ${position})`
					: "";
			$("<li>")
				.text(`${__(action)} · ${detail}${movement}`)
				.appendTo(list);
		}
		dialog.show();
	}

	frappe.ui.form.on("Project Deliverable", {
		setup: setupQueries,
		async refresh(frm) {
			frm.set_df_property("table_xuct", "cannot_delete_rows", true);
			frm.toggle_enable("deliverable_type", frm.is_new());
			frm.toggle_enable("project", frm.is_new());
			frm.set_df_property(
				"status",
				"options",
				(frm.is_new() ? ["Not Started", "Template"] : workingStatuses).join("\n")
			);
			frm.toggle_enable("status", frm.is_new());
			if (frm.is_new() || frm.doc.status === "Template") return;
			const name = frm.doc.name;
			if (frm.has_perm("write")) {
				frm.add_custom_button(__("Review result structure"), () => {
					if (frm.is_dirty()) {
						frappe.msgprint(__("Save the result before reviewing its structure."));
						return;
					}
					frappe.prompt(
						{
							fieldtype: "Link",
							fieldname: "deliverable_type",
							options: "Project Deliverable Type",
							label: __("Result Type"),
							default: frm.doc.deliverable_type,
							reqd: 1,
							get_query: () => ({ filters: { enabled: 1 } }),
						},
						async ({ deliverable_type }) => {
							const { message } = await frappe.call({
								method: api + "preview_structure",
								args: { deliverable: name, deliverable_type },
							});
							afterResponse(frm, name, () => confirmStructure(frm, message));
						},
						__("Review result structure"),
						__("Preview")
					);
				});
			}
			if (frm.fields_dict.progress_html) {
				frappe
					.require("/assets/dinext_project_scope/js/scope_analytics.js")
					.then(() =>
						afterResponse(frm, name, () =>
							window.DinextScopeAnalytics.renderDeliverableProgress(frm)
						)
					);
			}
			const { message } = await frappe.call({
				method: api + "get_deliverable_details",
				args: { deliverable: name },
			});
			afterResponse(frm, name, () => renderReadiness(frm, message));
		},
		project(frm) {
			if (!frm.is_new()) return;
			for (const field of [
				"table_xuct",
				"deliverable_responsibles",
				...Object.keys(projectLinks),
			]) {
				frm.clear_table(field);
				frm.refresh_field(field);
			}
			return loadDefaults(frm, { work: true, assignments: true });
		},
		deliverable_type(frm) {
			return loadDefaults(frm, { work: true });
		},
		category(frm) {
			return loadDefaults(frm, { assignments: true });
		},
		status(frm) {
			if (frm.is_new() && frm.doc.status === "Template")
				return frm.set_value("project", null);
		},
	});

	frappe.ui.form.on("Project Deliverable Responsible", {
		responsible_type(_frm, cdt, cdn) {
			return frappe.model.set_value(cdt, cdn, "responsible", null);
		},
		project_role(_frm, cdt, cdn) {
			return frappe.model.set_value(cdt, cdn, "responsible", null);
		},
	});
})();
