frappe.provide("dinext_project_scope.requirement_forms");

(() => {
	const requirement = "Project Requirement";
	const template = "Project Requirement Specification Template";
	const api = "dinext_project_scope.requirements";
	const approvalApi = "dinext_project_scope.requirement_approval";

	function element(tag, text = null, className = null) {
		const node = document.createElement(tag);
		if (text !== null) node.textContent = text;
		if (className) node.className = className;
		return node;
	}

	function button(label, action) {
		const control = element("button", label, "btn btn-default btn-xs");
		control.type = "button";
		control.addEventListener("click", action);
		return control;
	}

	function link(doctype, name, title = null) {
		const node = element("a", title || name);
		node.href = frappe.utils.get_form_link(doctype, name);
		return node;
	}

	function disclosure(label, body) {
		const details = element("details");
		details.append(element("summary", label), body);
		return details;
	}

	async function request(method, args) {
		const response = await frappe.call({ method, args });
		return response.message;
	}

	function placeholder(label) {
		return element("p", label, "text-muted");
	}

	function current(frm, name) {
		const [view, doctype, documentName] = frappe.get_route();
		return (
			view === "Form" &&
			doctype === frm.doctype &&
			documentName === name &&
			frm.doc.name === name
		);
	}

	function manyLinks(doctype, names) {
		const list = element("ul", null, "requirement-form-links");
		for (const name of names) {
			const item = element("li");
			item.append(link(doctype, name));
			list.append(item);
		}
		return list;
	}

	function itemTable(headings) {
		const region = element("div", null, "requirement-form-table");
		const table = element("table", null, "table table-bordered");
		region.tabIndex = 0;
		region.setAttribute("aria-label", __("Requirements"));
		const row = table.createTHead().insertRow();
		for (const heading of headings) {
			const cell = element("th", heading);
			cell.scope = "col";
			row.append(cell);
		}
		region.append(table);
		return { region, body: table.createTBody() };
	}

	function sourcesFor(doctype, paths) {
		const list = element("ul", null, "requirement-form-links");
		for (const path of paths) {
			const item = element("li");
			if (!path.length) item.textContent = __("Direct inclusion");
			for (const [index, name] of path.entries()) {
				if (index) item.append(" → ");
				item.append(link(doctype, name));
			}
			list.append(item);
		}
		return disclosure(__("Sources"), list);
	}

	function compositionTable(doctype, rows) {
		if (!rows.length) return placeholder(__("No requirements in this composition."));
		const table = itemTable([
			__("Requirement"),
			__("Status"),
			__("Content approval"),
			__("Sources"),
		]);
		const parents = new Set(rows.map((row) => row.parent).filter(Boolean));
		const depths = new Map();
		const hidden = new Map();
		const expanded = new Set(parents);
		const tableRows = new Map();
		function toggle() {
			for (const row of rows) {
				const shouldHide =
					row.parent && (hidden.get(row.parent) || !expanded.has(row.parent));
				hidden.set(row.name, Boolean(shouldHide));
				tableRows.get(row.name).hidden = Boolean(shouldHide);
			}
		}

		for (const row of rows) {
			const tr = table.body.insertRow();
			tableRows.set(row.name, tr);
			const group = element("span", null, "requirement-form-tree-label");
			const depth = row.parent ? (depths.get(row.parent) || 0) + 1 : 0;
			depths.set(row.name, depth);
			group.style.setProperty("--requirement-depth", depth);
			if (parents.has(row.name)) {
				const control = button("−", () => {
					if (expanded.has(row.name)) expanded.delete(row.name);
					else expanded.add(row.name);
					const visible = expanded.has(row.name);
					control.textContent = visible ? "−" : "+";
					control.setAttribute("aria-expanded", visible);
					toggle();
				});
				control.setAttribute("aria-label", __("Expand or collapse {0}", [row.title]));
				control.setAttribute("aria-expanded", "true");
				group.append(control);
			}
			group.append(link(requirement, row.name, row.title));
			tr.insertCell().append(group);
			tr.insertCell().textContent = __(row.status);
			tr.insertCell().textContent = __(row.approval_status);
			tr.insertCell().append(sourcesFor(doctype, row.paths));
		}
		return table.region;
	}

	function editComposition(frm, values) {
		const name = frm.doc.name;
		const project = frm.doc.project;
		const rows = values.items.slice();
		const render = () => {
			const wrapper = dialog.get_field("links").$wrapper.get(0);
			wrapper.replaceChildren();
			if (!rows.length)
				wrapper.append(placeholder(__("No direct links in this composition.")));
			const list = element("ol", null, "requirement-form-links");
			for (const [index, row] of rows.entries()) {
				const item = element("li", null, "requirement-form-editor-row");
				item.append(link(row.reference_doctype, row.reference_name, row.title));
				if (values.can_edit) {
					const moveUp = button(__("Move up"), () => move(index, -1));
					const moveDown = button(__("Move down"), () => move(index, 1));
					moveUp.disabled = index === 0;
					moveDown.disabled = index + 1 === rows.length;
					const remove = button(__("Remove"), () => {
						rows.splice(index, 1);
						render();
						dialog.get_field("target").$input.trigger("focus");
					});
					item.append(moveUp, moveDown, remove);
				}
				list.append(item);
			}
			wrapper.append(list);
		};
		const move = (index, delta) => {
			const destination = index + delta;
			const [entry] = rows.splice(index, 1);
			rows.splice(destination, 0, entry);
			render();
			const list = dialog.get_field("links").$wrapper.get(0).querySelector("ol");
			list.children[destination].querySelector("a").focus();
		};
		const fields = [{ fieldtype: "HTML", fieldname: "links" }];
		if (values.can_edit)
			fields.push(
				{
					fieldtype: "Select",
					fieldname: "target_type",
					label: __("Type"),
					options: [requirement, frm.doctype].map((value) => ({
						value,
						label: __(value),
					})),
					change() {
						dialog.set_value("target", "");
					},
				},
				{
					fieldtype: "Dynamic Link",
					fieldname: "target",
					label: __("Document"),
					options: "target_type",
					get_options: () => dialog.get_value("target_type"),
					get_query: () => {
						const type = dialog.get_value("target_type");
						if (frm.doctype === template)
							return {
								filters:
									type === requirement
										? { status: "Template", project: ["is", "not set"] }
										: { name: ["!=", name] },
							};
						return {
							filters:
								type === requirement
									? { project, status: ["!=", "Template"] }
									: { project, name: ["!=", name] },
						};
					},
				},
				{
					fieldtype: "Button",
					fieldname: "add_target",
					label: __("Add link"),
					click() {
						const targetType = dialog.get_value("target_type");
						const target = dialog.get_value("target");
						if (
							target &&
							!rows.some(
								(row) =>
									row.reference_doctype === targetType &&
									row.reference_name === target
							)
						) {
							rows.push({ reference_doctype: targetType, reference_name: target });
							render();
						}
						dialog.set_value("target", "");
					},
				}
			);
		const dialog = new frappe.ui.Dialog({
			title: __("Manage composition"),
			fields,
			size: "large",
			primary_action_label: values.can_edit ? __("Save composition") : __("Close"),
			async primary_action() {
				if (values.can_edit) {
					await request(`${api}.replace_composition`, {
						doctype: frm.doctype,
						name,
						modified: values.modified,
						items: rows,
					});
					if (current(frm, name)) frm.reload_doc();
				}
				dialog.hide();
			},
		});
		dialog.show();
		render();
	}

	function snapshotList(round, doctype) {
		const lists = element("div");
		for (const [type, nodes, label, titleKey] of [
			[doctype, round.snapshot.specifications, __("Specifications"), "title"],
			[requirement, round.snapshot.requirements, __("Requirements"), "requirement_title"],
		]) {
			if (!Object.keys(nodes).length) continue;
			const list = element("ul", null, "requirement-form-links");
			for (const [name, entry] of Object.entries(nodes)) {
				const row = element("li");
				const body = element("div");
				body.append(link(type, name));
				for (const [label, key] of [
					[__("Description"), "description"],
					[__("Reason / Justification"), "reason"],
					[__("Kind"), "kind"],
					[__("Priority"), "priority"],
					[__("Importance"), "requirement_importance"],
				]) {
					if (!entry.content[key]) continue;
					const detail = element("p", null, "requirement-form-snapshot-text");
					detail.append(element("strong", label), " · ", __(entry.content[key]));
					body.append(detail);
				}
				if (entry.parent) body.append(link(requirement, entry.parent));
				if (entry.content.goals?.length)
					body.append(manyLinks("Goal", entry.content.goals));
				if (entry.content.items?.length) {
					const references = element("ol", null, "requirement-form-links");
					for (const [targetType, target] of entry.content.items) {
						const reference = element("li");
						reference.append(link(targetType, target));
						references.append(reference);
					}
					body.append(references);
				}
				row.append(disclosure(entry.content[titleKey] || name, body));
				list.append(row);
			}
			lists.append(element("h6", label), list);
		}
		return lists;
	}

	async function showHistory(doctype, name) {
		const history = await request(`${approvalApi}.approval_history`, { doctype, name });
		const dialog = new frappe.ui.Dialog({
			title: __("Approval history"),
			size: "large",
			fields: [{ fieldname: "history", fieldtype: "HTML" }],
		});
		const content = dialog.get_field("history").$wrapper.get(0);
		if (!history.rounds.length) content.append(placeholder(__("No approval rounds yet.")));
		for (const round of history.rounds) {
			const body = snapshotList(round, round.reference_doctype);
			if (round.workflow_process)
				body.prepend(
					link("Workflow Process", round.workflow_process, __("Workflow process"))
				);
			if (round.reference_doctype !== doctype || round.reference_name !== name) {
				body.prepend(link(round.reference_doctype, round.reference_name));
			}
			if (round.participants?.length)
				body.append(disclosure(__("Reviewers"), manyLinks("User", round.participants)));
			if (round.decision_reason)
				body.prepend(
					element("p", round.decision_reason, "requirement-form-snapshot-text")
				);
			const decided = [
				round.decided_at && frappe.datetime.str_to_user(round.decided_at),
				round.decided_by,
			]
				.filter(Boolean)
				.join(" · ");
			if (decided) body.prepend(element("p", decided));
			const submitted = [frappe.datetime.str_to_user(round.submitted_at), round.submitted_by]
				.filter(Boolean)
				.join(" · ");
			body.prepend(element("p", submitted));
			const label = [__("Round {0}", [round.round_number]), __(round.decision)];
			if (round.status === "Reapproval Required") label.push(__(round.status));
			content.append(disclosure(label.join(" · "), body));
		}
		dialog.show();
	}

	function toolbar(frm, status, title) {
		const bar = element("div", null, "requirement-form-toolbar");
		const heading = element("h5", title);
		const state = element(
			"span",
			`${__("Content approval")} · ${__(status)}`,
			"requirement-form-status"
		);
		bar.append(
			heading,
			state,
			button(__("Approval history"), () => showHistory(frm.doctype, frm.doc.name))
		);
		return bar;
	}

	async function refreshSpecification(frm) {
		frm.toggle_display("items", false);
		if (frm.fields_dict.project) frm.set_df_property("project", "read_only", !frm.is_new());
		const wrapper = frm.fields_dict.composition_html.$wrapper.get(0);
		if (frm.is_new()) {
			wrapper.replaceChildren(
				placeholder(__("Save the specification to manage its composition."))
			);
			return;
		}
		const name = frm.doc.name;
		const args = { doctype: frm.doctype, name };
		wrapper.replaceChildren(placeholder(__("Loading requirements…")));
		try {
			const [rows, approval] = await Promise.all([
				request(`${api}.composition_rows`, args),
				request(`${approvalApi}.approval_summary`, args),
			]);
			if (!current(frm, name)) return;
			const bar = toolbar(frm, approval.status, __("Requirements"));
			const manage = button(__("Manage composition"), async () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save the form before editing the composition."));
					return;
				}
				const direct = await request(`${api}.direct_composition`, args);
				if (current(frm, name)) editComposition(frm, direct);
			});
			manage.dataset.action = "manage-composition";
			bar.append(manage);
			const section = element("div", null, "requirement-form");
			section.append(bar, compositionTable(frm.doctype, rows));
			if (approval.used_by?.length)
				section.append(
					disclosure(
						__("Used in specifications"),
						manyLinks(frm.doctype, approval.used_by)
					)
				);
			if (approval.covered_by?.length)
				section.append(
					disclosure(
						__("Covered by approval"),
						manyLinks(frm.doctype, approval.covered_by)
					)
				);
			if (approval.project)
				section.append(
					disclosure(__("Used in project"), manyLinks("Project", [approval.project]))
				);
			wrapper.replaceChildren(section);
		} catch {
			if (current(frm, name))
				wrapper.replaceChildren(
					placeholder(__("Could not load the requirement composition."))
				);
		}
	}

	function relatedList(doctype, label, rows) {
		const group = element("section");
		group.append(element("h6", label));
		if (!rows.length) group.append(placeholder(__("No linked records.")));
		const list = element("ul", null, "requirement-form-links");
		for (const row of rows) {
			const item = element("li");
			item.append(link(doctype, row.name, row.title));
			if (row.status) item.append(" · ", __(row.status));
			list.append(item);
		}
		group.append(list);
		return group;
	}

	async function refreshRequirement(frm) {
		const wrapper = frm.fields_dict.linked_documents_html.$wrapper.get(0);
		if (frm.is_new()) {
			wrapper.replaceChildren();
			return;
		}
		const name = frm.doc.name;
		const doctype = frm.doctype;
		wrapper.replaceChildren(placeholder(__("Loading linked documents…")));
		try {
			const [data, approval] = await Promise.all([
				request(`${api}.related_documents`, { name }),
				request(`${approvalApi}.approval_summary`, { doctype, name }),
			]);
			if (!current(frm, name)) return;
			const bar = toolbar(frm, approval.status, __("Linked documents"));
			if (frm.doc.project) {
				bar.append(
					button(__("Traceability matrix"), () => {
						frappe.route_options = { project: frm.doc.project, requirement: name };
						frappe.set_route("query-report", "Requirement Traceability Matrix");
					})
				);
			}
			const section = element("div", null, "requirement-form");
			section.append(bar);
			if (frm.doc.project && !data.in_scope)
				section.append(placeholder(__("Outside current project scope")));
			const related = element("div", null, "requirement-form-related");
			related.append(relatedList("Goal", __("Goals"), data.goals));
			if (frm.doc.project)
				related.append(
					relatedList(
						"Project Deliverable",
						__("Project Deliverables"),
						data.deliverables
					),
					relatedList(
						"Project Change Request",
						__("Project Change Requests"),
						data.changes
					)
				);
			section.append(related);
			wrapper.replaceChildren(section);
		} catch {
			if (current(frm, name))
				wrapper.replaceChildren(placeholder(__("Could not load linked documents.")));
		}
	}

	Object.assign(window.dinext_project_scope.requirement_forms, {
		refreshSpecification,
		refreshRequirement,
	});
})();
