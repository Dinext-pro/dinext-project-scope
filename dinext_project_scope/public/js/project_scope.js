(() => {
	const REQ = "Project Requirement";
	const SPEC = "Project Requirement Specification";
	const TEMPLATE = "Project Requirement Specification Template";
	const CONSTRAINT_TEMPLATE = "Project Constraints Template";
	const PATH = "dinext_project_scope.";
	const reports = [
		"Project Scope Overview",
		"Requirement Traceability Matrix",
		"Project Responsibility Matrix",
		"Project Change Impact Matrix",
	];
	const baseAPI = "dinext_project_scope.requirements.";
	const FIELD = {
		requirements: "custom_scope_requirements_html",
		specs: "custom_project_requirement_specifications",
		direct: "custom_project_requirements",
		changes: "custom_scope_changes_html",
	};
	const calls = new WeakMap();

	const rpc = async (method, args) => (await frappe.call({ method, args })).message;
	const writable = (frm) => !frm.is_new() && frm.has_perm("write");
	const wrapper = (frm, field) => frm.get_field(field)?.wrapper;

	function node(tag, text, classes) {
		const element = document.createElement(tag);
		if (text != null) element.textContent = text;
		if (classes) element.className = classes;
		return element;
	}

	function button(label, action, className = "btn btn-default btn-xs") {
		const element = node("button", label, className);
		element.type = "button";
		element.addEventListener("click", () => action());
		return element;
	}

	function formLink(label, doctype, name) {
		return button(
			label,
			() => frappe.set_route("Form", doctype, name),
			"btn btn-link scope-link"
		);
	}

	function report(frm, name, filters = {}) {
		frappe.route_options = { project: frm.doc.name, ...filters };
		frappe.set_route("query-report", name);
	}

	function table(labels) {
		const host = node("div", null, "scope-table-scroll");
		const tableElement = node("table", null, "table table-sm scope-table");
		const row = tableElement.createTHead().insertRow();
		for (const label of labels) {
			const th = node("th", label);
			th.scope = "col";
			row.append(th);
		}
		host.append(tableElement);
		return { host, body: tableElement.createTBody() };
	}

	function disclosure(label, contents) {
		const details = node("details");
		details.append(node("summary", label), contents);
		return details;
	}

	function requirementSources(row) {
		const container = node("div", null, "scope-source-list");
		const names = [...new Set(row.paths.flat())];
		if (!names.length) return node("span", "—");
		container.append(...names.map((name) => formLink(name, SPEC, name)));
		return container;
	}

	function requirementDetails(row) {
		const content = node("div");
		const details = node("dl", null, "scope-row-details");
		for (const [label, value] of [
			[__("Category"), row.kind],
			[__("Priority"), row.priority],
			[__("Importance"), row.requirement_importance],
			[__("Author"), row.author],
			[__("Responsible"), row.responsible],
		]) {
			if (!value) continue;
			const field = node("div");
			field.append(node("dt", label), node("dd", __(value)));
			details.append(field);
		}
		content.append(details);
		for (const path of row.paths) {
			const paragraph = node(
				"div",
				path.length ? null : __("Included directly"),
				"scope-source-path"
			);
			for (const name of path) {
				if (paragraph.childNodes.length) paragraph.append(document.createTextNode(" › "));
				paragraph.append(formLink(name, SPEC, name));
			}
			content.append(paragraph);
		}
		return disclosure(__("Details"), content);
	}

	function requirementsTable(rows) {
		const { host, body } = table([__("Requirement"), __("Status"), __("Specifications")]);
		if (!rows.length) {
			const cell = body.insertRow().insertCell();
			cell.colSpan = 3;
			cell.textContent = __("No requirements in the selected scope.");
			return host;
		}
		const children = new Map();
		for (const row of rows) {
			const parent = row.parent || null;
			if (!children.has(parent)) children.set(parent, []);
			children.get(parent).push(row);
		}
		const collapsed = new Set();
		function draw(parent, depth) {
			for (const row of children.get(parent) || []) {
				const entry = body.insertRow();
				entry.dataset.requirement = row.name;
				const holder = node("div", null, "scope-tree-label");
				holder.style.setProperty("--scope-depth", Math.min(depth, 6));
				const title = node("div");
				title.append(
					formLink(row.title || row.name, REQ, row.name),
					node("small", row.name, "text-muted")
				);
				if (children.has(row.name)) {
					const control = button(
						collapsed.has(row.name) ? "▸" : "▾",
						() => {
							if (collapsed.has(row.name)) collapsed.delete(row.name);
							else collapsed.add(row.name);
							body.replaceChildren();
							draw(null, 0);
							[...body.querySelectorAll("button[data-fold]")]
								.find((item) => item.dataset.fold === row.name)
								?.focus();
						},
						"btn btn-link scope-fold"
					);
					control.dataset.fold = row.name;
					control.setAttribute(
						"aria-label",
						__("Toggle requirement branch") + " " + row.name
					);
					control.setAttribute("aria-expanded", !collapsed.has(row.name));
					holder.append(control);
				} else holder.append(node("span", null, "scope-fold"));
				holder.append(title);
				entry.insertCell().append(holder);
				const status = entry.insertCell();
				status.append(node("span", __(row.status, null, REQ), "indicator-pill"));
				if (row.approval_stale)
					status.append(node("small", __("Reapproval Required"), "text-warning"));
				const source = entry.insertCell();
				source.append(requirementSources(row), requirementDetails(row));
				if (!collapsed.has(row.name)) draw(row.name, depth + 1);
			}
		}
		draw(null, 0);
		return host;
	}

	function choose(label, doctype, query, perform) {
		const dialog = new frappe.ui.Dialog({
			title: label,
			fields: [
				{
					fieldname: "item",
					fieldtype: "Link",
					label,
					options: doctype,
					reqd: 1,
					get_query: query,
				},
			],
			primary_action_label: __("Continue"),
			primary_action: async ({ item }) => {
				await perform(item);
				dialog.hide();
			},
		});
		dialog.show();
	}

	function ensureSaved(frm) {
		if (frm.is_dirty()) {
			frappe.throw(__("Save the project before changing its requirements."));
		}
	}

	async function updateConnections(frm, field, key, names) {
		ensureSaved(frm);
		const current = new Set((frm.doc[field] || []).map((row) => row[key]));
		for (const name of names) {
			if (!current.has(name)) frm.add_child(field, { [key]: name });
		}
		await frm.save();
	}

	function includeRequirement(frm, branch = false) {
		choose(
			branch ? __("Add Requirement Branch") : __("Add Requirement"),
			REQ,
			() => ({ filters: { project: frm.doc.name, status: ["!=", "Template"] } }),
			async (name) => {
				if (!branch)
					return updateConnections(frm, FIELD.direct, "project_requirement", [name]);
				const rows = await rpc(baseAPI + "linkable_requirement_branch", {
					project: frm.doc.name,
					requirement: name,
				});
				const list = node("ul");
				for (const row of rows) {
					const item = node("li");
					const label = node("label", null, "scope-branch-option");
					const input = node("input");
					input.type = "checkbox";
					input.checked = true;
					input.value = row.name;
					label.append(input, node("span", row.title || row.name));
					item.append(label);
					list.append(item);
				}
				const preview = new frappe.ui.Dialog({
					title: __("Add Requirement Branch"),
					fields: [{ fieldname: "selection", fieldtype: "HTML" }],
					primary_action_label: __("Add Selected"),
					primary_action: async () => {
						await updateConnections(
							frm,
							FIELD.direct,
							"project_requirement",
							[...list.querySelectorAll("input:checked")].map((item) => item.value)
						);
						preview.hide();
					},
				});
				preview.fields_dict.selection.wrapper.append(list);
				preview.show();
			}
		);
	}

	function createRequirement(frm) {
		ensureSaved(frm);
		const dialog = new frappe.ui.Dialog({
			title: __("New Requirement"),
			fields: [
				{ fieldname: "title", fieldtype: "Data", label: __("Requirement"), reqd: 1 },
				{
					fieldname: "category",
					fieldtype: "Link",
					options: "Requirement Kind",
					label: __("Category"),
					reqd: 1,
				},
				{
					fieldname: "author",
					fieldtype: "Link",
					options: "Contact",
					label: __("Author"),
					reqd: 1,
				},
				{
					fieldname: "responsible",
					fieldtype: "Link",
					options: "User",
					label: __("Responsible"),
				},
			],
			primary_action_label: __("Create"),
			primary_action: async (values) => {
				const name = await rpc(`${PATH}project_scope.create_project_requirement`, {
					...values,
					project: frm.doc.name,
				});
				dialog.hide();
				await frm.reload_doc();
				frappe.set_route("Form", REQ, name);
			},
		});
		dialog.show();
	}

	function placeScopeGrids(frm) {
		const reference = frm.get_field(FIELD.requirements);
		if (!reference?.$wrapper?.length) return;
		for (const [fieldname, side] of [
			["project_scopes", "before"],
			["project_constraints", "after"],
		]) {
			const field = frm.get_field(fieldname);
			if (!field?.$wrapper?.length || field.tab === reference.tab) continue;
			if (side === "before") field.$wrapper.insertBefore(reference.$wrapper);
			else field.$wrapper.insertAfter(reference.$wrapper);
			field.tab = reference.tab;
			field.section = reference.section;
		}
	}

	function specificationConnections(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Manage Requirement Connections"),
			fields: [{ fieldname: "list", fieldtype: "HTML" }],
		});
		const content = node("div", null, "scope-connection-list");
		for (const [field, key, doctype, heading] of [
			[FIELD.specs, "specification", SPEC, __("Connected Specifications")],
			[FIELD.direct, "project_requirement", REQ, __("Direct Requirements")],
		]) {
			content.append(node("h5", heading));
			for (const row of frm.doc[field] || []) {
				const line = node("div", null, "scope-connection-row");
				line.append(formLink(row[key], doctype, row[key]));
				if (writable(frm))
					line.append(
						button(__("Disconnect"), () =>
							frappe.confirm(
								__("Remove this source from the project scope?"),
								async () => {
									ensureSaved(frm);
									frappe.model.clear_doc(row.doctype, row.name);
									frm.dirty();
									await frm.save();
									dialog.hide();
								}
							)
						)
					);
				content.append(line);
			}
			if (!frm.doc[field]?.length)
				content.append(node("p", __("No connections"), "text-muted"));
		}
		dialog.fields_dict.list.wrapper.append(content);
		dialog.show();
	}

	function showSpecificationPreview(frm, template) {
		ensureSaved(frm);
		previewAndApply(
			frm,
			template,
			`${baseAPI}preview_specification_template`,
			`${baseAPI}apply_specification_template`,
			(data) => [
				...(data.specifications || []).map((row) => ({
					...row,
					source: row.name,
					scope_type: __("Specification"),
				})),
				...(data.requirements || []).map((row) => ({
					...row,
					source: row.name,
					scope_type: __("Requirement"),
				})),
			],
			(data) => (data.assignees || []).map((user) => ({ type: "User", name: user })),
			true
		);
	}

	function showConstraintPreview(frm, template) {
		ensureSaved(frm);
		previewAndApply(
			frm,
			template,
			`${PATH}project_scope.preview_constraints_template`,
			`${PATH}project_scope.apply_constraints_template`,
			(data) =>
				data.rows.map((row) => ({
					...row,
					title: row.subject,
					scope_type: __(row.record_type),
				})),
			(data) => data.participants.map(([type, name]) => ({ type, name })),
			false
		);
	}

	async function previewAndApply(
		frm,
		template,
		previewMethod,
		applyMethod,
		toRows,
		users,
		userOnly
	) {
		const args = { project: frm.doc.name, template };
		const data = await rpc(previewMethod, args);
		const rows = toRows(data);
		const options = users(data);
		const edits = new Map();
		const { host, body } = table([__("Type"), __("Name"), __("Responsible")]);
		for (const row of rows) {
			const entry = body.insertRow();
			entry.insertCell().textContent = row.scope_type;
			entry.insertCell().textContent = row.title || row.source;
			const select = node("select", null, "form-control input-sm");
			select.setAttribute("aria-label", __("Responsible") + " " + (row.title || row.source));
			select.append(new Option(row.responsible || __("Choose Responsible"), ""));
			options.forEach(({ type, name }, index) =>
				select.append(new Option(name + ` · ${__(type)}`, String(index)))
			);
			select.addEventListener("change", () => {
				if (!select.value) edits.delete(row.source);
				else {
					const selected = options[Number(select.value)];
					edits.set(
						row.source,
						userOnly ? selected.name : { doctype: selected.type, name: selected.name }
					);
				}
			});
			entry.insertCell().append(select);
		}
		const requestKey = crypto.randomUUID();
		const dialog = new frappe.ui.Dialog({
			title: __("Preview Template Application"),
			fields: [{ fieldname: "preview", fieldtype: "HTML" }],
			primary_action_label: __("Apply Template"),
			primary_action: async () => {
				const assignments = Object.fromEntries(edits);
				const confirmed = Object.keys(assignments).length
					? await rpc(previewMethod, { ...args, assignments })
					: data;
				await rpc(applyMethod, {
					...args,
					assignments,
					preview_digest: confirmed.digest,
					request_key: requestKey,
				});
				dialog.hide();
				await frm.reload_doc();
			},
		});
		dialog.fields_dict.preview.wrapper.append(host);
		dialog.show();
	}

	function filterAndActions(frm, selected, refresh) {
		const toolbar = node("div", null, "scope-toolbar");
		const actions = node("div", null, "scope-toolbar");
		if (writable(frm)) {
			actions.append(button(__("Add Requirement"), () => includeRequirement(frm)));
			const secondary = node("div", null, "scope-actions-menu");
			secondary.append(
				button(__("New Requirement"), () => createRequirement(frm)),
				button(__("Add Requirement Branch"), () => includeRequirement(frm, true)),
				button(__("Connect Specification"), () =>
					choose(
						__("Connect Specification"),
						SPEC,
						() => ({ filters: { project: frm.doc.name } }),
						async (name) => {
							const rows = await rpc(baseAPI + "composition_rows", {
								doctype: SPEC,
								name,
							});
							frappe.confirm(
								__("Connect specification {0} with {1} requirements?", [
									name,
									rows.length,
								]),
								() => updateConnections(frm, FIELD.specs, "specification", [name])
							);
						}
					)
				),
				button(__("New Specification"), () =>
					frappe.new_doc(SPEC, { project: frm.doc.name })
				),
				button(__("Apply Specification Template"), () =>
					choose(__("Apply Specification Template"), TEMPLATE, undefined, (name) =>
						showSpecificationPreview(frm, name)
					)
				),
				button(__("Manage Requirement Connections"), () => specificationConnections(frm))
			);
			actions.append(disclosure(__("More Actions"), secondary));
		}
		actions.append(
			button(__("Requirement Traceability Matrix"), () =>
				report(frm, "Requirement Traceability Matrix", {
					specification: selected || undefined,
				})
			)
		);
		toolbar.append(actions);
		const filterHost = node("div", null, "scope-compact-filter");
		toolbar.append(filterHost);
		const field = frappe.ui.form.make_control({
			parent: filterHost,
			render_input: true,
			df: {
				fieldtype: "Link",
				fieldname: "scope_specification_filter",
				label: __("Specification"),
				options: SPEC,
				get_query: () => ({ filters: { project: frm.doc.name } }),
				change() {
					if (this.get_value() !== selected) refresh(this.get_value());
				},
			},
		});
		if (selected) field.set_value(selected);
		return toolbar;
	}

	async function showRequirements(frm, specification = "") {
		const target = wrapper(frm, FIELD.requirements);
		if (!target) return;
		const request = Symbol();
		calls.set(frm, request);
		if (frm.is_new()) {
			target.replaceChildren(
				node("p", __("Save the project to manage scope."), "text-muted")
			);
			return;
		}
		const rows = await rpc(baseAPI + "project_rows", { project: frm.doc.name, specification });
		if (calls.get(frm) !== request) return;
		const pane = node("section", null, "dinext-project-scope");
		pane.append(
			node("h5", __("Requirements")),
			filterAndActions(frm, specification, (value) => showRequirements(frm, value)),
			requirementsTable(rows)
		);
		target.replaceChildren(pane);
	}

	async function showChanges(frm) {
		const target = wrapper(frm, FIELD.changes);
		if (!target || frm.is_new()) return;
		const project = frm.doc.name;
		const rows = frappe.model.can_read("Project Change Request")
			? await rpc(`${PATH}project_scope.project_change_rows`, { project })
			: [];
		if (project !== frm.doc.name) return;
		const pane = node("section", null, "dinext-project-scope");
		const toolbar = node("div", null, "scope-toolbar");
		toolbar.append(node("h5", __("Change Requests")));
		if (writable(frm) && frappe.model.can_create("Project Change Request")) {
			toolbar.append(
				button(__("New Change Request"), () =>
					frappe.new_doc("Project Change Request", { project })
				)
			);
		}
		toolbar.append(
			button(__("Project Change Request Register"), () =>
				report(frm, "Project Change Request Register")
			)
		);
		pane.append(toolbar);
		const { host, body } = table([__("Change Request"), __("Status"), __("Responsible")]);
		for (const row of rows) {
			const entry = body.insertRow();
			entry
				.insertCell()
				.append(formLink(row.title || row.name, "Project Change Request", row.name));
			entry.insertCell().textContent = __(row.status);
			entry.insertCell().textContent = row.implementation_responsible || "—";
		}
		if (!rows.length) {
			const cell = body.insertRow().insertCell();
			cell.colSpan = 3;
			cell.textContent = __("No change requests.");
		}
		pane.append(host);
		target.replaceChildren(pane);
	}

	function gridRowRoute(frm) {
		const options = frappe.route_options || {};
		const target = [
			["scope_constraint", "project_constraints"],
			["scope_volume", "project_scopes"],
			["scope_risk", "custom_project_risks"],
		].find(([key]) => options[key]);
		if (!target) return;
		const [key, field] = target;
		const name = options[key];
		delete options[key];
		const grid = frm.get_field(field)?.grid;
		if (grid) {
			frm.scroll_to_field(field);
			grid.grid_rows_by_docname[name]?.toggle_view(true);
		}
	}

	frappe.ui.form.on("Project", {
		setup(frm) {
			frm.set_query("verification_evidence", "project_constraints", () => ({
				filters: { attached_to_doctype: "Project", attached_to_name: frm.doc.name },
			}));
		},
		async refresh(frm) {
			await frappe.require("/assets/dinext_project_scope/css/project_scope.css");
			placeScopeGrids(frm);
			await Promise.all([showRequirements(frm), showChanges(frm)]);
			gridRowRoute(frm);
			if (frm.is_new()) return;
			if (writable(frm) && frappe.route_options?.scope_constraint_template) {
				const template = frappe.route_options.scope_constraint_template;
				delete frappe.route_options.scope_constraint_template;
				showConstraintPreview(frm, template);
			}
			for (const name of reports)
				frm.add_custom_button(__(name), () => report(frm, name), __("Scope Reports"));
			if (writable(frm))
				frm.add_custom_button(
					__("Apply Constraints Template"),
					() =>
						choose(
							__("Apply Constraints Template"),
							CONSTRAINT_TEMPLATE,
							undefined,
							(name) => showConstraintPreview(frm, name)
						),
					__("Scope")
				);
			await frappe.require("/assets/dinext_project_scope/js/scope_analytics.js");
			window.DinextScopeAnalytics?.renderResults(frm);
			window.DinextScopeAnalytics?.renderProjectProgress(frm);
		},
	});

	frappe.ui.form.on("Project Scope", {
		async scope_type(frm, cdt, cdn) {
			const row = frappe.get_doc(cdt, cdn);
			const response = row.scope_type
				? await frappe.db.get_value("Project Scope Type", row.scope_type, "object_doctype")
				: null;
			frappe.model.set_value(cdt, cdn, {
				linked_doctype: response?.message?.object_doctype || "",
				object_ref: "",
			});
		},
	});
})();
