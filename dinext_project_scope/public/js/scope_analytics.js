(() => {
	"use strict";

	const ASSET_ROOT = "/assets/dinext_project_scope";
	const API = "dinext_project_scope.analytics.data";
	const EMPTY = "__dinext_scope_no_value__";
	const xlsxIcon =
		'<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M8 2v8m-3-3 3 3 3-3M3 11v3h10v-3"/></svg>';
	const DELIVERABLE = "Project Deliverable";
	const RESULT_FILTER_FIELDS = new Set(["status", "deliverable_type", "category"]);
	const tones = ["red", "yellow", "green", "light-green", "cyan", "blue", "gray"];
	const surfaces = new Map();
	let projectProgressView = null;
	const chartPalette = [
		"#3976b7",
		"#22877c",
		"#9b65b4",
		"#b96836",
		"#a87b22",
		"#587b53",
		"#c05f72",
		"#5d73a5",
	];
	const resultLightPalette = [
		"#2868eb",
		"#088e72",
		"#914be6",
		"#d65a1c",
		"#bc8708",
		"#468936",
		"#d94372",
		"#4e66df",
	];
	let libraryRequest = null;

	function node(tag, className, text) {
		const item = document.createElement(tag);
		if (className) item.className = className;
		if (text !== undefined && text !== null) item.textContent = text;
		return item;
	}

	function button(label, handler, className = "btn btn-default btn-xs") {
		const item = node("button", className, label);
		item.type = "button";
		item.addEventListener("click", handler);
		return item;
	}

	function call(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method: method.includes(".") ? method : `${API}.${method}`,
				args,
				type: "GET",
				callback: (response) => resolve(response.message),
				error: reject,
			});
		});
	}

	function libraries() {
		if (!libraryRequest) {
			libraryRequest = frappe.require([
				"dinext-table.bundle.js",
				"/assets/dinext_common/js/charts/dinext-charts-core.js",
				`${ASSET_ROOT}/css/scope_analytics.css`,
			]);
		}
		return libraryRequest;
	}

	function routeMatches(kind, name, docname) {
		const route = frappe.get_route();
		return (
			route[0] === kind &&
			route[1] === name &&
			(docname === undefined || route[2] === docname)
		);
	}

	function childRoute(field) {
		return {
			project_constraints: "scope_constraint",
			project_scopes: "scope_volume",
			custom_project_risks: "scope_risk",
		}[field];
	}

	function openDocument(doctype, name, childField, childName) {
		const option = childRoute(childField);
		if (option && childName) frappe.route_options = { [option]: childName };
		return frappe.set_route("Form", doctype, name);
	}

	function toReport(name, filters) {
		frappe.route_options = { ...filters };
		return frappe.set_route("query-report", name);
	}

	function documentLink(label, doctype, name, childField, childName) {
		const item = node("a", "dinext-scope-link", label);
		item.href = frappe.utils.get_form_link(doctype, name);
		item.addEventListener("click", (event) => {
			if (
				childRoute(childField) ||
				!(event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
			) {
				event.preventDefault();
				event.stopPropagation();
				openDocument(doctype, name, childField, childName);
			}
		});
		return item;
	}

	function createSurface(host, isActive) {
		surfaces.get(host)?.dispose();
		const root = node("section", "dinext-scope-analytics");
		host.replaceChildren(root);
		const charts = new Map();
		const pendingResize = new Set();
		let resizeFrame = null;
		const surface = {
			root,
			table: null,
			messages: null,
			active: () => surfaces.get(host) === surface && host.isConnected && isActive(),
			clearCharts() {
				for (const element of charts.keys()) this.unregisterChart(element);
			},
			unregisterChart(element) {
				resize?.unobserve(element);
				pendingResize.delete(element);
				window.DinextCharts?.dispose(element);
				charts.delete(element);
			},
			dispose() {
				this.clearCharts();
				resize?.disconnect();
				if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
				theme.disconnect();
				this.disposeControls?.();
				this.table?.destroy();
				this.table = null;
				root.remove();
				if (surfaces.get(host) === surface) surfaces.delete(host);
			},
			registerChart(element, option, onMount) {
				charts.set(element, { option, onMount, instance: null });
				resize?.observe(element);
				mount(element);
			},
		};

		function mount(element, remount = false) {
			const item = charts.get(element);
			if (
				!item ||
				!surface.active() ||
				!element.clientWidth ||
				!element.clientHeight ||
				!window.echarts
			)
				return;
			if (item.instance && !remount) {
				item.instance.resize();
				return;
			}
			item.instance = window.DinextCharts.mount(element, item.option());
			if (item.instance) item.onMount?.(item.instance);
		}

		const resize = window.ResizeObserver
			? new ResizeObserver((entries) => {
					for (const entry of entries) pendingResize.add(entry.target);
					if (resizeFrame !== null) return;
					resizeFrame = requestAnimationFrame(() => {
						resizeFrame = null;
						for (const element of pendingResize) mount(element);
						pendingResize.clear();
					});
			  })
			: null;
		const theme = new MutationObserver(() => {
			for (const element of charts.keys()) mount(element, true);
		});
		theme.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme", "data-theme-mode"],
		});
		surfaces.set(host, surface);
		return surface;
	}

	frappe.router.on("change", () => {
		if (projectProgressView && !routeMatches("Form", "Project", projectProgressView.project)) {
			disposeProjectProgress();
		}
		for (const surface of surfaces.values()) {
			if (!surface.active()) surface.dispose();
		}
	});

	function setMessage(surface, text) {
		if (!surface.messages) {
			surface.messages = node("p", "dinext-scope-empty");
			surface.messages.setAttribute("role", "status");
			surface.root.append(surface.messages);
		}
		surface.messages.hidden = !text;
		surface.messages.textContent = text || "";
	}

	function formatProgress(value) {
		return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
			Number(value)
		)}%`;
	}

	function badge(text, tone) {
		return node(
			"span",
			`dinext-scope-badge${tone ? ` dinext-scope-badge--${tone}` : ""}`,
			text
		);
	}

	function roleBadges(entries) {
		const holder = node("span", "dinext-scope-badges");
		for (const entry of entries || []) {
			const abbreviation = entry.abbreviation ?? entry.code;
			const item = badge(abbreviation);
			item.title = entry.label;
			item.setAttribute("aria-label", `${abbreviation} · ${entry.label}`);
			if (/^#[0-9a-f]{6}$/i.test(entry.color || "")) {
				const components = [1, 3, 5].map(
					(index) => parseInt(entry.color.slice(index, index + 2), 16) / 255
				);
				const linear = components.map((component) =>
					component <= 0.04045 ? component / 12.92 : ((component + 0.055) / 1.055) ** 2.4
				);
				const luminance = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
				item.style.setProperty("--scope-badge-bg", entry.color);
				item.style.setProperty("--scope-badge-fg", luminance > 0.179 ? "#161616" : "#fff");
			}
			holder.append(item);
		}
		return holder;
	}

	function impactDetails(row, column) {
		const impact = row.cells?.[column.fieldname];
		if (!impact) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Impact details"),
			fields: [{ fieldtype: "HTML", fieldname: "scope_impact_details" }],
			size: "large",
		});
		// The dialog title is rendered as HTML by Frappe.
		dialog.$wrapper.find(".modal-title").text(`${row.label} · ${column.label}`);
		const records = node("div", "dinext-scope-analytics dinext-scope-impact-details");
		for (const detail of impact.details) {
			const card = node("article", "dinext-scope-impact-detail");
			const heading = node("div", "dinext-scope-impact-detail-heading");
			heading.append(
				badge(
					detail.level ? __(detail.level) : __("Level not specified"),
					{ Weak: "green", Moderate: "yellow", Strong: "red" }[detail.level]
				)
			);
			if (detail.matched) heading.append(badge(__("Matched filters"), "blue"));
			card.append(heading);
			if (detail.direction) card.append(node("p", "text-muted", __(detail.direction)));
			if (detail.estimation) {
				card.append(
					node(
						"p",
						"",
						[detail.estimation, detail.uom && __(detail.uom)].filter(Boolean).join(" ")
					)
				);
			}
			if (detail.explanation)
				card.append(node("p", "dinext-scope-impact-detail-note", detail.explanation));
			if (detail.link_project && detail.link) {
				card.append(
					documentLink(
						detail.link,
						"Project",
						detail.link_project,
						detail.link_parentfield,
						detail.link
					)
				);
			} else if (detail.link_doctype && detail.link) {
				card.append(documentLink(detail.link, detail.link_doctype, detail.link));
			} else if (detail.link_unavailable) {
				card.append(node("p", "text-muted", __("Related object unavailable")));
			}
			records.append(card);
		}
		dialog.get_field("scope_impact_details").$wrapper.get(0).append(records);
		// Keep the details visible when opened from the full-screen matrix.
		window.DinextTable?.adoptOverlay(dialog.$wrapper.get(0));
		dialog.show();
	}

	function stateCell(row, summary) {
		const holder = node("span", "dinext-scope-state");
		const status = row.status ? __(row.status, null, row.document_type) : "";
		const tone = summary ? null : row.status_tone;
		if (summary && row.progress !== null && row.progress !== undefined) {
			holder.append(
				badge([status, formatProgress(row.progress)].filter(Boolean).join(" · "), tone)
			);
		} else if (status) {
			holder.append(badge(status, tone));
		}
		if (row.status_note) holder.append(node("span", "dinext-scope-note", __(row.status_note)));
		if (row.approval_stale || row.requires_recheck) {
			holder.append(
				node(
					"span",
					"dinext-scope-note",
					row.approval_stale ? __("Reapproval required") : __("Acceptance needs review")
				)
			);
		}
		holder.title = Array.from(holder.children, (item) => item.textContent).join(" · ");
		return holder;
	}

	function isResultRow(row) {
		return row?.document_type === DELIVERABLE && !row.is_other;
	}

	function opensOnDoubleClick(row, resultTree) {
		return resultTree && (row?.document_type === "Task" || isResultRow(row));
	}

	function labelCell(row, resultTree) {
		const holder = node("span", "dinext-scope-label");
		if (row.document && !opensOnDoubleClick(row, resultTree)) {
			holder.append(
				documentLink(
					row.label || row.document,
					row.document_type,
					row.document,
					row.child_field,
					row.child_document
				)
			);
		} else if (row.route_report) {
			holder.append(
				button(
					row.label,
					() => toReport(row.route_report, row.route_filters),
					"dinext-scope-link dinext-scope-link-button"
				)
			);
		} else {
			holder.append(
				node(
					"span",
					isResultRow(row) && resultTree ? "dinext-scope-link" : "",
					row.label || ""
				)
			);
		}
		if (row.slot_label) holder.append(node("span", "dinext-scope-note", row.slot_label));
		return holder;
	}

	function imageWithFallback(source, fallback) {
		if (typeof source !== "string" || !source.trim()) return fallback;
		let url;
		try {
			url = new URL(source, window.location.origin);
		} catch {
			return fallback;
		}
		if (url.protocol !== "https:" && url.protocol !== "http:") return fallback;
		const image = node("img");
		image.alt = "";
		image.addEventListener("error", () => image.replaceWith(fallback), { once: true });
		image.src = url.href;
		return image;
	}

	function resultType(row, value) {
		if (!value || row.document_type !== DELIVERABLE || row.is_other)
			return node("span", "", value);
		const holder = node("span", "dinext-scope-result-type");
		holder.title = value;
		holder.setAttribute("role", "img");
		holder.setAttribute("aria-label", value);
		const icon = node("span");
		icon.innerHTML = frappe.utils.icon("file", "sm");
		holder.append(imageWithFallback(row.deliverable_type_icon, icon));
		return holder;
	}

	function participantAvatar(member) {
		const avatar = node("span", "avatar avatar-small");
		avatar.title = member.label;
		avatar.setAttribute("role", "img");
		avatar.setAttribute("aria-label", member.label);
		const initials = node(
			"span",
			"avatar-frame standard-image",
			frappe.get_abbr(member.label, 1)
		);
		const [background, text] = frappe.get_palette(member.label);
		initials.style.backgroundColor = `var(${background})`;
		initials.style.color = `var(${text})`;
		avatar.append(imageWithFallback(member.image, initials));
		return avatar;
	}

	class ParticipantHeader {
		init({ assignee }) {
			this.element = participantAvatar(assignee);
		}

		getGui() {
			return this.element;
		}
	}

	function resultAvatars(row, members) {
		if (!members?.length) {
			if (row.document_type !== DELIVERABLE || row.is_other) return node("span");
			const placeholder = node("span", "text-muted", "—");
			placeholder.title = __("Responsible person not assigned");
			placeholder.setAttribute("aria-label", placeholder.title);
			return placeholder;
		}
		const holder = node("span", "dinext-scope-result-avatars");
		holder.append(...members.map(participantAvatar));
		return holder;
	}

	function resultProgress(value, label) {
		if (value === null || value === undefined || !Number.isFinite(Number(value)))
			return node("span");
		const percent = Math.max(0, Math.min(100, Number(value)));
		const progress = node("div", "progress dinext-scope-result-progress");
		progress.title = formatProgress(percent);
		progress.setAttribute("role", "progressbar");
		progress.setAttribute("aria-label", label);
		progress.setAttribute("aria-valuemin", "0");
		progress.setAttribute("aria-valuemax", "100");
		progress.setAttribute("aria-valuenow", String(percent));
		const bar = node("div", "progress-bar progress-bar-success");
		bar.style.width = `${percent}%`;
		progress.append(bar);
		return progress;
	}

	function resultDelta(row, field, label) {
		const value = row[field];
		const direction = row[`${field}_direction`];
		if (value == null || !direction) return node("span");
		const locale = frappe.boot.user?.language?.replaceAll("_", "-");
		const format = new Intl.NumberFormat(locale || undefined, { maximumFractionDigits: 2 });
		const amount = format.format(Math.abs(value));
		const marker = node(
			"span",
			`dinext-scope-result-delta dinext-scope-result-delta--${direction}`
		);
		marker.dataset.direction = direction;
		const arrow = node("span", "", { up: "↑", flat: "→", down: "↓" }[direction]);
		arrow.setAttribute("aria-hidden", "true");
		const sign = value > 0 ? "+" : value < 0 ? "−" : "";
		marker.title = `${label} ${sign}${amount} ${__("pp")}`;
		marker.setAttribute("aria-label", marker.title);
		marker.append(arrow, document.createTextNode(` ${amount} ${__("pp")}`));
		return marker;
	}

	function resultRowStyle({ data }) {
		const color = data?.deliverable_type_color;
		if (data?.document_type !== DELIVERABLE || !/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(color))
			return undefined;
		return {
			"--scope-result-type-color": color,
			backgroundColor:
				"color-mix(in srgb, var(--scope-result-type-color) var(--scope-result-type-tint), var(--ag-background-color))",
		};
	}

	function cellRenderer(column, resultTree) {
		return (params) => {
			const row = params.data || {};
			const value = params.value;
			switch (column.kind) {
				case "label":
					return labelCell(row, resultTree);
				case "raci":
					return roleBadges(row.cells?.[column.fieldname]);
				case "badges":
					return roleBadges(value);
				case "impact": {
					const item = row.cells?.[column.fieldname];
					if (!item) return node("span", "text-muted", "—");
					const action = button(
						value,
						(event) => {
							event.stopPropagation();
							impactDetails(row, column);
						},
						"dinext-scope-impact-button"
					);
					action.append(node("span", "sr-only", ` · ${column.label}`));
					if (item.tone)
						action.classList.add(
							"dinext-scope-badge",
							`dinext-scope-badge--${item.tone}`
						);
					return action;
				}
				case "trace_state":
					return stateCell(row, true);
				case "status":
					return column.fieldname === "status"
						? stateCell(row, false)
						: node("span", "", value ? __(value) : "");
				case "progress":
					return node(
						"span",
						"",
						value === null || value === undefined ? "" : formatProgress(value)
					);
				case "result_progress":
					return resultProgress(value, column.label);
				case "result_delta":
					return resultDelta(row, column.fieldname, column.label);
				case "result_type":
					return resultType(
						row,
						catalogLabel(column.fieldname, value, row.document_type)
					);
				case "result_assignment":
					return resultAvatars(row, value);
				case "project":
					return value ? documentLink(value, "Project", value) : node("span");
				case "accountable": {
					const holder = node("span", "dinext-scope-accountable");
					if (row.document_type !== DELIVERABLE) return holder;
					if (!value?.length)
						return node(
							"span",
							"dinext-scope-note",
							__("Responsible person not assigned")
						);
					for (const member of value) {
						if (holder.childNodes.length)
							holder.append(document.createTextNode(" / "));
						holder.append(node("span", "", `${member.label} (${__(member.doctype)})`));
					}
					return holder;
				}
				case "plan_date": {
					const holder = node("span", "dinext-scope-state");
					if (value) holder.append(node("span", "", frappe.datetime.str_to_user(value)));
					else if (row.document_type === DELIVERABLE)
						holder.append(node("span", "dinext-scope-note", __("No planned date")));
					if (row.plan_incomplete)
						holder.append(node("span", "dinext-scope-note", __("Plan is incomplete")));
					return holder;
				}
				case "date":
					return node("span", "", value ? frappe.datetime.str_to_user(value) : "");
				case "datetime":
					return node("span", "", value ? frappe.datetime.str_to_user(value) : "");
				case "note": {
					const text = node("span", "", value);
					if (value) text.title = value;
					return text;
				}
				case "count":
					return node("span", "", value ?? "");
				default:
					return node(
						"span",
						"",
						catalogLabel(column.fieldname, value, row.document_type)
					);
			}
		};
	}

	function tableColumns(columns, resultTree) {
		const groups = new Map();
		const result = [];
		for (const column of columns) {
			const item = {
				field: column.fieldname,
				headerName: column.label,
				width: column.width || 135,
				minWidth: column.kind === "result_type" ? 66 : 76,
				cellDataType: false,
			};
			if (column.assignee) {
				const width = 104;
				Object.assign(item, {
					width,
					minWidth: width,
					maxWidth: width,
					resizable: false,
					autoHeight: true,
				});
				item.headerComponentParams = {
					innerHeaderComponent: ParticipantHeader,
					innerHeaderComponentParams: { assignee: column.assignee },
				};
			}
			if (column.pinned) {
				item.pinned = column.pinned;
				item.lockPinned = true;
			}
			if (column.kind === "result_progress" || column.kind === "result_delta") {
				Object.assign(item, {
					minWidth: column.width,
					maxWidth: column.width,
					resizable: false,
					wrapHeaderText: true,
					autoHeaderHeight: true,
				});
			}
			if (column.kind === "result_assignment") item.autoHeight = true;
			if (resultTree && RESULT_FILTER_FIELDS.has(column.fieldname)) {
				item.cellClassRules = {
					"dinext-scope-result-filter-cell": ({ data }) => isResultRow(data),
				};
			}
			if (column.kind === "label") item.render = cellRenderer(column, resultTree);
			else item.cellRenderer = cellRenderer(column);
			if (column.kind === "trace_state") {
				item.cellClassRules = Object.fromEntries(
					tones.map((tone) => [
						`dinext-scope-state-cell--${tone}`,
						({ data }) => data?.status_tone === tone,
					])
				);
			}
			if (!column.group_id) {
				result.push(item);
			} else {
				if (!groups.has(column.group_id)) {
					const group = {
						groupId: column.group_id,
						headerName: column.group,
						...(column.assignee && {
							headerTooltip: column.group,
							marryChildren: true,
						}),
						children: [],
					};
					groups.set(column.group_id, group);
					result.push(group);
				}
				groups.get(column.group_id).children.push(item);
			}
		}
		return result;
	}

	function expansionIds(rows, mode) {
		const ids = [];
		function collect(siblings, parent = "") {
			for (const row of siblings) {
				if (!row.children?.length) continue;
				const id = parent ? `${parent}:${row.id}` : String(row.id);
				if (mode === "all" || !parent || row.context_only) ids.push(id);
				if (mode === "all" || row.context_only) collect(row.children, id);
			}
		}
		if (mode) collect(rows);
		return ids;
	}

	async function drawGrid(surface, container, columns, rows, options = {}) {
		if (!surface.active()) return;
		const definitions = tableColumns(columns, options.resultTree);
		const columnKey = options.resultTree && columns.map((column) => column.fieldname).join();
		if ((options.resultTree || options.responsibilityMatrix) && surface.table) {
			const table = surface.table;
			if (options.resultTree) {
				table.clearRowCheck();
				if (surface.resultColumnKey !== columnKey) {
					table.setOption("columns", definitions);
					surface.resultColumnKey = columnKey;
				}
				const type = columns.find((column) => column.kind === "result_type");
				table.api.setColumnWidths([{ key: type.fieldname, newWidth: type.width }]);
			} else {
				table.setOption("columns", definitions);
				table.expandedIds.clear();
			}
			for (const id of expansionIds(rows, options.expand)) table.expandedIds.add(id);
			table.refresh(rows);
			table.refreshToolbar();
			setMessage(
				surface,
				rows.length ? null : options.emptyMessage || __("No records match the filters.")
			);
			return;
		}
		const generation = (surface.gridGeneration || 0) + 1;
		surface.gridGeneration = generation;
		surface.table?.destroy();
		surface.table = null;
		container.replaceChildren();
		const available = rows.length > 0;
		const toolbarItems = [...(options.toolbarItems || [])];
		container.hidden = !available && !toolbarItems.length;
		setMessage(surface, available ? null : __("No records match the filters."));
		if (container.hidden) return;
		if (options.export) {
			toolbarItems.push({
				id: "scope-export",
				type: "custom",
				render: () => {
					if (!options.responsibilityMatrix)
						return button(__("Download Excel"), options.export);
					const excel = button(
						__("Excel"),
						options.export,
						"btn btn-default btn-xs dinext-scope-excel"
					);
					const icon = node("span");
					icon.setAttribute("aria-hidden", "true");
					icon.innerHTML = frappe.utils.icon("es-line-download", "sm");
					excel.prepend(icon);
					return excel;
				},
			});
		}
		const grid = node("div", "dinext-scope-grid-target");
		container.append(grid);
		const pendingFilters = new Map();
		const filterKey = (row, field) => JSON.stringify([row._rowId, field]);
		const layout = { height: "auto", minHeight: 76, maxHeight: "min(65vh, 660px)" };
		const table = await window.DinextTable.create({
			container: grid,
			data: rows,
			columns: definitions,
			expandedIds: expansionIds(rows, options.expand),
			filter: { enabled: false },
			edit: false,
			...(options.resultTree && {
				rowCheck: { enabled: true, selectAll: false },
				canCheckRow: options.canCheckRow,
			}),
			toolbar: {
				presets: ["tree", "fullscreen"],
				items: toolbarItems,
			},
			fullscreen: {
				target: "shell",
				shell: options.fullscreenShell || surface.root,
				...((options.resultTree || options.responsibilityMatrix) && {
					onEnter: ({ table }) => table.setOption("layout", { height: "host" }),
					onExit: ({ table }) => table.setOption("layout", layout),
				}),
			},
			layout,
			gridOptions: {
				...(options.resultTree && { getRowStyle: resultRowStyle }),
				suppressNoRowsOverlay: Boolean(options.resultTree || options.responsibilityMatrix),
				rowHeight: 35,
				headerHeight: 32,
				groupHeaderHeight: 29,
				suppressCellFocus: false,
				getRowClass: ({ data }) =>
					data?.is_group
						? "dinext-scope-group-row"
						: data?.context_only
						? "dinext-scope-context-row"
						: "",
				onCellDoubleClicked({ data, event, colDef }) {
					if (
						!opensOnDoubleClick(data, options.resultTree) ||
						!data.document ||
						event.target.closest("a, button, input, .dinext-table-tree-toggle")
					)
						return;
					const key = filterKey(data, colDef.field);
					clearTimeout(pendingFilters.get(key));
					pendingFilters.delete(key);
					openDocument(data.document_type, data.document);
				},
				onCellClicked({ data, event, colDef }) {
					if (
						!data ||
						event.target.closest("a, button, input, .dinext-table-tree-toggle")
					)
						return;
					if (opensOnDoubleClick(data, options.resultTree)) {
						const field = colDef.field;
						if (
							isResultRow(data) &&
							RESULT_FILTER_FIELDS.has(field) &&
							event.detail < 2
						) {
							const key = filterKey(data, field);
							clearTimeout(pendingFilters.get(key));
							// Give a double click priority over the filter on the same cell.
							pendingFilters.set(
								key,
								setTimeout(() => {
									pendingFilters.delete(key);
									if (surface.active())
										options.toggleResultFilter(field, data[field]);
								}, 300)
							);
						}
						return;
					}
					if (data.document)
						openDocument(
							data.document_type,
							data.document,
							data.child_field,
							data.child_document
						);
					else if (data.route_report) toReport(data.route_report, data.route_filters);
				},
				onCellKeyDown(params) {
					const { data, event, colDef } = params;
					if (!data || event.target.closest("a, button, input")) return;
					if (
						colDef.field === "label" &&
						data._hasChildren &&
						[" ", "ArrowLeft", "ArrowRight"].includes(event.key)
					) {
						const gridTable = params.context?.dinextTable;
						const expanded = gridTable?.isRowExpanded(data._rowId);
						if (
							event.key === " " ||
							(event.key === "ArrowLeft" && expanded) ||
							(event.key === "ArrowRight" && !expanded)
						) {
							event.preventDefault();
							gridTable?.toggleRow(data._rowId);
						}
						return;
					}
					if (event.key !== "Enter" || opensOnDoubleClick(data, options.resultTree))
						return;
					if (data.cells?.[colDef.field]?.details) {
						impactDetails(
							data,
							columns.find((column) => column.fieldname === colDef.field)
						);
					} else if (data.document) {
						openDocument(
							data.document_type,
							data.document,
							data.child_field,
							data.child_document
						);
					} else if (data.route_report) {
						toReport(data.route_report, data.route_filters);
					}
				},
			},
		});
		if (!surface.active() || surface.gridGeneration !== generation) table.destroy();
		else {
			surface.table = table;
			surface.resultColumnKey = columnKey;
		}
	}

	function chartColors() {
		const css = getComputedStyle(document.documentElement);
		return {
			text: css.getPropertyValue("--text-color").trim() || "#656f7b",
			muted: css.getPropertyValue("--text-muted").trim() || "#656f7b",
			border: css.getPropertyValue("--border-color").trim() || "#c1cddd",
		};
	}

	function anchorLinkOptions(field) {
		const list = field.awesomplete?.ul;
		const host = field.input?.closest(".link-field");
		if (!list || !host) return null;
		if (list.parentElement !== host) {
			// Keep the native options with their input when DinextTable moves fullscreen overlays.
			list.classList.add("dropdown-menu", "dinext-scope-link-options");
			host.append(list);
		}
		return list;
	}

	function chartFilter(
		surface,
		container,
		{ key, label, title, formatLabel, chartType },
		onChange
	) {
		const horizontal = chartType === "horizontal-bar";
		const card = node("section", "dinext-scope-chart-card");
		const chart = node("div");
		card.append(node("h4", "dinext-scope-heading", title), chart);
		container.append(card);
		const all = {
			value: "",
			label: frappe.utils.escape_html(__("All", null, "Dinext.ProjectScope.Filters")),
		};
		let control;
		let selection = "";
		if (!horizontal) {
			const filter = node("div", "dinext-scope-result-filter");
			card.append(filter);
			control = frappe.ui.form.make_control({
				parent: filter,
				only_input: true,
				render_input: true,
				df: {
					fieldtype: "Select",
					fieldname: key,
					label,
					options: [all],
					onchange: onChange,
				},
			});
			control.$input.attr("aria-label", label);
		}
		const optionValue = (name) => name || EMPTY;
		const display = (name) => formatLabel(name) || __("Not specified");
		const panel = {
			key,
			getValue() {
				return control ? control.get_value() : selection;
			},
			setValue(value) {
				if (control) control.set_input(value);
				else selection = value;
			},
			clear() {
				const element = chart.querySelector(".dinext-scope-chart");
				if (element) surface.unregisterChart(element);
				chart.replaceChildren();
			},
			matches(value) {
				const selected = panel.getValue();
				return !selected || selected === optionValue(value);
			},
			toggle(name) {
				const option = optionValue(name);
				panel.setValue(panel.getValue() === option ? "" : option);
				return onChange();
			},
			draw(options, counts, selected = panel.getValue() || "") {
				if (control) {
					control.df.options = [
						all,
						...options.map(({ name }) => ({
							value: optionValue(name),
							label: frappe.utils.escape_html(display(name)),
						})),
					];
				}
				panel.setValue(selected);
				panel.clear();
				const onSelect = ({ name }) => panel.toggle(name);
				if (horizontal) {
					drawHorizontalBars(surface, chart, options, {
						formatLabel: display,
						onSelect,
						isHighlighted: (name) => !selected || selected === optionValue(name),
					});
				} else if (chartType === "timeline") {
					drawTimeline(surface, chart, counts, onSelect);
				} else {
					drawDonut(surface, chart, counts, onSelect, {
						legend: false,
						formatLabel: display,
						palette: () =>
							document.documentElement.dataset.theme === "dark"
								? chartPalette
								: resultLightPalette,
					});
				}
			},
		};
		return panel;
	}

	function drawDonut(
		surface,
		container,
		items,
		onSelect,
		{ legend = true, formatLabel = (name) => name, palette = () => chartPalette } = {}
	) {
		if (!items.length) {
			container.append(node("div", "dinext-scope-empty", __("No data")));
			return;
		}
		const chart = node("div", "dinext-scope-chart dinext-scope-chart--donut");
		const describeChart = !onSelect || !legend;
		chart.setAttribute("aria-hidden", String(!describeChart));
		const data = items.map((item) => ({
			name: item.label || formatLabel(item.name) || __("Not specified"),
			value: item.count,
		}));
		const total = String(data.reduce((sum, item) => sum + item.value, 0));
		const count = node("span", "dinext-scope-donut-count", total);
		count.setAttribute("aria-hidden", "true");
		const plot = node("div", "dinext-scope-donut-plot");
		plot.append(chart, count);
		container.append(plot);
		if (legend) {
			const colors = palette();
			const labels = node("div", "dinext-scope-chart-legend");
			for (const [index, item] of data.entries()) {
				const label = `${item.name} · ${item.value}`;
				const action = onSelect
					? button(label, () => onSelect(items[index]), "dinext-scope-legend-item")
					: node("span", "dinext-scope-legend-item", label);
				const color = node("span", "dinext-scope-legend-dot");
				color.style.setProperty("--scope-legend-color", colors[index % colors.length]);
				action.prepend(color);
				labels.append(action);
			}
			container.append(labels);
		}
		surface.registerChart(
			chart,
			() => ({
				color: palette(),
				backgroundColor: "transparent",
				animation: false,
				aria: { enabled: describeChart },
				tooltip: {
					trigger: "item",
					renderMode: "html",
					enterable: false,
					className: "dinext-scope-donut-tooltip",
					position: (_point, _item, _element, _sector, { viewSize, contentSize }) => [
						Math.max(0, (viewSize[0] - contentSize[0]) / 2),
						0,
					],
				},
				series: [
					{
						type: "pie",
						radius: ["59%", "82%"],
						label: { show: false },
						data,
					},
				],
			}),
			(instance) => {
				const showTotal = () => {
					count.textContent = total;
				};
				showTotal();
				instance.on("mouseover", "series.pie", ({ value }) => {
					count.textContent = String(value);
				});
				instance.on("mouseout", "series.pie", showTotal);
				instance.on("globalout", showTotal);
				if (onSelect) {
					instance.on("click", "series.pie", ({ dataIndex }) =>
						onSelect(items[dataIndex])
					);
				}
			}
		);
	}

	function drawHorizontalBars(
		surface,
		container,
		items,
		{ formatLabel, onSelect, isHighlighted }
	) {
		if (!items.length) {
			container.append(node("div", "dinext-scope-empty", __("No data")));
			return;
		}
		const ordered = [...items].sort(
			(a, b) => b.count - a.count || formatLabel(a.name).localeCompare(formatLabel(b.name))
		);
		const chart = node("div", "dinext-scope-chart dinext-scope-chart--horizontal");
		chart.style.setProperty("--scope-bar-rows", ordered.length);
		container.append(chart);
		surface.registerChart(
			chart,
			() => {
				const { text } = chartColors();
				const palette =
					document.documentElement.dataset.theme === "dark"
						? chartPalette
						: resultLightPalette;
				return {
					backgroundColor: "transparent",
					color: [palette[0]],
					animation: false,
					aria: { enabled: true },
					grid: { left: 156, right: 38, top: 4, bottom: 4 },
					tooltip: { trigger: "item", renderMode: "richText" },
					xAxis: { type: "value", min: 0, max: "dataMax", show: false },
					yAxis: {
						type: "category",
						inverse: true,
						data: ordered.map(({ name }) => name),
						axisLine: { show: false },
						axisTick: { show: false },
						axisLabel: {
							color: text,
							formatter: formatLabel,
							interval: 0,
							margin: 12,
							width: 136,
							overflow: "truncate",
						},
					},
					series: [
						{
							type: "bar",
							barMaxWidth: 16,
							itemStyle: { borderRadius: [0, 3, 3, 0] },
							label: {
								show: true,
								position: "right",
								formatter: "{c}",
								color: text,
							},
							data: ordered.map(({ name, count }) => ({
								name: formatLabel(name),
								value: count,
								itemStyle: { opacity: isHighlighted(name) ? 1 : 0.32 },
							})),
						},
					],
				};
			},
			(instance) =>
				instance.on("click", "series.bar", ({ dataIndex }) => onSelect(ordered[dataIndex]))
		);
	}

	function drawTimeline(surface, container, points, onSelect) {
		if (!points.length) {
			container.append(node("div", "dinext-scope-empty", __("No data")));
			return;
		}
		const chart = node("div", "dinext-scope-chart dinext-scope-chart--timeline");
		container.append(chart);
		surface.registerChart(
			chart,
			() => {
				const colors = chartColors();
				return {
					backgroundColor: "transparent",
					color: chartPalette,
					animation: false,
					aria: { enabled: true },
					grid: { left: 34, right: 18, bottom: 31, top: 14 },
					tooltip: { trigger: "axis", renderMode: "richText" },
					xAxis: {
						type: "category",
						data: points.map((item) => frappe.datetime.str_to_user(item.name)),
						axisLabel: { color: colors.muted },
					},
					yAxis: {
						type: "value",
						minInterval: 1,
						axisLabel: { color: colors.muted },
						splitLine: { lineStyle: { color: colors.border } },
					},
					series: [
						{ type: "bar", data: points.map((item) => item.count), barMaxWidth: 45 },
					],
				};
			},
			(instance) => instance.on("click", (event) => onSelect(points[event.dataIndex]))
		);
	}

	function wallTime(value) {
		return new Date(value.length === 10 ? `${value}T00:00:00Z` : `${value}Z`).getTime();
	}

	function drawProgress(surface, container, payload) {
		if (!surface.active() || !container.isConnected) return;
		const old = container.querySelector(".dinext-scope-chart");
		// Overview can switch the selected result without rebuilding its other charts.
		if (old) surface.unregisterChart(old);
		container.replaceChildren();
		const note = node("div", "dinext-scope-chart-notes text-muted");
		if (payload.plan_reason === "missing")
			note.append(node("p", "", __("Set both planned dates to show the plan.")));
		if (payload.plan_reason === "invalid")
			note.append(node("p", "", __("The planned end is before the planned start.")));
		if (payload.plan_incomplete) note.append(node("p", "", __("Plan is incomplete")));
		if (payload.actual.length) {
			const start = frappe.datetime.str_to_user(payload.actual[0][0].replace("T", " "));
			note.append(node("p", "", __("No actual progress was recorded before {0}.", [start])));
		} else {
			note.append(node("p", "", __("No actual progress has been recorded.")));
		}
		if (payload.planned.length || payload.actual.length) {
			const chart = node("div", "dinext-scope-chart dinext-scope-chart--progress");
			container.append(chart);
			surface.registerChart(chart, () => {
				const colors = chartColors();
				const planned = payload.planned.map(([value, progress]) => [
					wallTime(value),
					progress,
				]);
				const actual = payload.actual.map(([value, progress]) => [
					wallTime(value),
					progress,
				]);
				const first = Math.min(planned[0]?.[0] ?? Infinity, actual[0]?.[0] ?? Infinity);
				const startsLater = actual.length && actual[0][0] > first;
				const series = [];
				if (planned.length)
					series.push({
						type: "line",
						step: payload.plan_step ? "end" : false,
						name: __("Current plan"),
						showSymbol: false,
						lineStyle: { type: "dashed", width: 2 },
						data: planned,
					});
				if (actual.length)
					series.push({
						type: "line",
						name: __("Recorded progress"),
						data: actual,
						step: "end",
						symbol: "circle",
						showSymbol: true,
						symbolSize: 6,
						markArea: startsLater
							? {
									silent: true,
									itemStyle: { color: "rgba(127, 135, 147, 0.12)" },
									data: [[{ xAxis: first }, { xAxis: actual[0][0] }]],
							  }
							: undefined,
					});
				return {
					useUTC: true,
					backgroundColor: "transparent",
					color: ["#3976b7", "#22877c"],
					animation: false,
					aria: { enabled: true },
					legend: { type: "scroll", bottom: 3, textStyle: { color: colors.text } },
					grid: { left: 49, right: 22, bottom: 52, top: 22 },
					tooltip: {
						trigger: "axis",
						renderMode: "richText",
						valueFormatter: formatProgress,
					},
					xAxis: { type: "time", axisLabel: { color: colors.muted } },
					yAxis: {
						type: "value",
						min: 0,
						max: 100,
						axisLabel: { color: colors.muted, formatter: "{value}%" },
						splitLine: { lineStyle: { color: colors.border } },
					},
					series,
				};
			});
		}
		container.append(note);
	}

	function resultChartToolbox(element, filename, colors) {
		return {
			top: 0,
			right: 6,
			iconStyle: { borderColor: colors.text },
			feature: {
				saveAsImage: {
					type: "png",
					title: __("Download PNG"),
					name: filename,
					pixelRatio: 2,
					backgroundColor: getComputedStyle(element)
						.getPropertyValue("--card-bg")
						.trim(),
				},
			},
		};
	}

	function resultDateMarkers(data, colors) {
		const reporting = __("Reporting date");
		const baseline = __("Baseline date");
		const markers = [
			{
				name:
					data.baseline_date === data.reporting_date
						? `${reporting} / ${baseline}`
						: reporting,
				xAxis: wallTime(data.reporting_date),
			},
		];
		if (data.baseline_date && data.baseline_date !== data.reporting_date) {
			markers.push({
				name: baseline,
				xAxis: wallTime(data.baseline_date),
				lineStyle: { type: "dotted" },
				label: { position: "insideStartTop" },
			});
		}
		return {
			data: markers,
			silent: true,
			symbol: "none",
			lineStyle: { type: "dashed", width: 1, color: colors.muted },
			label: {
				position: "insideEndTop",
				formatter: "{b}",
				rotate: 0,
				color: colors.text,
				fontSize: 11,
			},
		};
	}

	function resultDynamicsOption(element, group, data, filename) {
		const context = "Dinext.ProjectScope.Dynamics";
		const colors = chartColors();
		const css = getComputedStyle(element);
		const lines = [
			["planned", __("Plan"), "dashed"],
			["forecast", __("Forecast", null, context), "solid"],
			["actual", __("Actual", null, context), "solid", "end"],
			["trend", __("Trend", null, context), "dotted"],
		];
		return {
			useUTC: true,
			backgroundColor: "transparent",
			animation: false,
			aria: { enabled: true },
			color: lines.map(([key]) => css.getPropertyValue(`--scope-dynamics-${key}`).trim()),
			grid: { left: 45, right: 22, top: 36, bottom: 54 },
			legend: { type: "scroll", bottom: 2, textStyle: { color: colors.text } },
			tooltip: {
				trigger: "axis",
				renderMode: "richText",
				confine: true,
				valueFormatter: (value) =>
					value == null || value === "-" ? "" : formatProgress(value),
			},
			toolbox: resultChartToolbox(element, filename, colors),
			xAxis: {
				type: "time",
				min: wallTime(data.range[0]),
				max: wallTime(data.range[1]),
				minInterval: 86400000,
				axisLabel: {
					color: colors.muted,
					hideOverlap: true,
					formatter(value) {
						return frappe.datetime.str_to_user(
							new Date(value).toISOString().slice(0, 10)
						);
					},
				},
			},
			yAxis: {
				type: "value",
				min: 0,
				max: 100,
				interval: 25,
				axisLabel: { color: colors.muted, formatter: "{value}%" },
				splitLine: { lineStyle: { color: colors.border } },
			},
			series: lines.map(([key, name, type, step]) => ({
				type: "line",
				name,
				step,
				connectNulls: false,
				showSymbol: group.series[key].filter(([, value]) => value != null).length === 1,
				symbol: "circle",
				symbolSize: 5,
				lineStyle: { type, width: 2 },
				data: group.series[key].map(([day, value]) => [wallTime(day), value]),
				...(key === "actual" && {
					areaStyle: { opacity: 0.2 },
					markLine: resultDateMarkers(data, colors),
				}),
			})),
		};
	}

	function resultTreemapOption(chart, group, filename) {
		const colors = chartColors();
		const background = getComputedStyle(chart).getPropertyValue("--card-bg").trim();
		return {
			backgroundColor: "transparent",
			animation: false,
			aria: { enabled: true },
			color: [
				"#255ca8",
				"#167262",
				"#794dab",
				"#9c4a28",
				"#806212",
				"#4f7149",
				"#a24560",
				"#525f93",
			],
			tooltip: { trigger: "item", renderMode: "richText", confine: true },
			toolbox: resultChartToolbox(chart, filename, colors),
			series: [
				{
					type: "treemap",
					top: 30,
					bottom: 4,
					left: 0,
					right: 0,
					roam: false,
					nodeClick: false,
					breadcrumb: { show: false },
					itemStyle: { borderColor: background, borderWidth: 1, gapWidth: 3 },
					label: {
						formatter: "{participant|{b}}\n{count|{c}}",
						color: "#fff",
						overflow: "truncate",
						rich: {
							participant: { fontSize: 12, lineHeight: 19 },
							count: { fontSize: 19, fontWeight: 600, lineHeight: 24 },
						},
					},
					data: group.items.map(({ value, label, count }) => ({
						id: value,
						name: label || __("Unassigned"),
						value: count,
						...(value === group.selected && {
							itemStyle: { borderColor: colors.text, borderWidth: 3 },
							label: { fontWeight: "bold" },
						}),
					})),
				},
			],
		};
	}

	function resultDynamics(surface, project, getQuery, onSelectResponsible) {
		const element = node("div", "dinext-scope-dynamics");
		element.hidden = true;
		element.setAttribute("role", "region");
		element.setAttribute("aria-label", __("Result dynamics"));

		const panels = [
			["category", __("Result dynamics")],
			["responsible", __("By responsible person")],
		].map(([key, title]) => {
			const card = node("section", "dinext-scope-dynamics-card");
			card.dataset.dynamicsGroup = key;
			const chart = node("div", "dinext-scope-chart dinext-scope-dynamics-chart");
			const note = node("p", "dinext-scope-dynamics-note text-muted", __("Loading"));
			note.setAttribute("role", "status");
			card.append(node("h4", "dinext-scope-heading", title), chart, note);
			element.append(card);
			return { key, chart, note, rendered: null };
		});
		let revision = 0;
		let requested = null;
		return {
			element,
			refresh,
			invalidate() {
				requested = null;
			},
			toggle() {
				element.hidden = !element.hidden;
				requested = null;
				if (element.hidden) revision++;
				else refresh();
			},
		};

		async function refresh(query = getQuery()) {
			if (element.hidden || !surface.active()) return;
			if (query.baseline_date && query.baseline_date > query.reporting_date) return;
			const key = JSON.stringify(query);
			if (requested === key) return;
			requested = key;
			const request = ++revision;
			element.setAttribute("aria-busy", "true");
			try {
				const data = await call(
					"dinext_project_scope.analytics.dynamics.project_result_dynamics",
					query
				);
				if (!surface.active() || request !== revision) return;
				for (const panel of panels) render(panel, data);
			} catch {
				if (!surface.active() || request !== revision) return;
				requested = null;
				for (const panel of panels) {
					surface.unregisterChart(panel.chart);
					panel.rendered = null;
					panel.note.textContent = __("Could not load result dynamics.");
				}
			} finally {
				if (request === revision) element.removeAttribute("aria-busy");
			}
		}

		function render(panel, data) {
			const { key, note, chart } = panel;
			const group = data[key];
			const dateRange =
				key === "category" ? [data.range, data.reporting_date, data.baseline_date] : null;
			const renderKey = JSON.stringify([group, dateRange]);
			if (panel.rendered === renderKey) return;
			panel.rendered = renderKey;
			surface.unregisterChart(chart);
			const fileKey = key === "category" ? `${key}-${data.reporting_date}` : key;
			const filename = `${project}-result-dynamics-${fileKey}`.replace(/[<>:"/\\|?*]/g, "-");
			if (key === "responsible") {
				note.textContent = group.items.length ? "" : __("No records match the filters.");
				if (group.items.length) {
					surface.registerChart(
						chart,
						() => resultTreemapOption(chart, group, filename),
						(instance) => {
							instance.on("click", "series.treemap", ({ data }) => {
								if (data?.id) onSelectResponsible(data.id);
							});
						}
					);
				}
				return;
			}

			const hasActual = group.series.actual.some(([, value]) => value != null);
			const notes = [];
			if (!group.count) {
				notes.push(__("No records match the filters."));
			} else {
				if (!group.series.planned.length) notes.push(__("Plan is incomplete"));
				if (!hasActual) notes.push(__("No actual progress has been recorded."));
			}
			note.textContent = notes.join(" · ");
			if (group.series.planned.length || hasActual) {
				surface.registerChart(chart, () =>
					resultDynamicsOption(chart, group, data, filename)
				);
			}
		}
	}

	function formHost(frm, fieldname) {
		return frm.fields_dict[fieldname]?.$wrapper?.get(0);
	}

	function catalogLabel(field, value, documentType) {
		if (!value) return value;
		if (field === "category")
			return __(
				value,
				null,
				documentType === "Project Requirement"
					? "Requirement Kind"
					: "Project Deliverable Category"
			);
		if (field === "deliverable_type" && documentType === DELIVERABLE)
			return __(value, null, "Project Deliverable Type");
		return value;
	}

	function resultFilterLabel(field, value) {
		if (!value) return __("Not specified");
		return field === "status"
			? __(value, null, DELIVERABLE)
			: catalogLabel(field, value, DELIVERABLE);
	}

	function resultTypeWidth(container, heading, rows) {
		const measure = document.createElement("canvas").getContext("2d");
		if (!measure) return 76;
		const style = getComputedStyle(container);
		measure.font = `600 ${style.fontSize} ${style.fontFamily}`;
		let width = measure.measureText(heading).width;
		measure.font = `${style.fontSize} ${style.fontFamily}`;
		function visit(items) {
			for (const row of items) {
				if (!isResultRow(row) && row.deliverable_type) {
					width = Math.max(width, measure.measureText(row.deliverable_type).width);
				}
				if (row.children?.length) visit(row.children);
			}
		}
		visit(rows);
		return Math.max(66, Math.min(240, Math.ceil(width + 34)));
	}

	function resultColumns(container, rows, comparison) {
		const type = __("Type");
		const progressWidth = 116;
		const deltaWidth = 100;
		return [
			["label", __("Deliverable / Work"), "label", 285, "left"],
			["status", __("Status"), "status", 155],
			["deliverable_type", type, "result_type", resultTypeWidth(container, type, rows)],
			["category", __("Category"), null, 150],
			...(comparison.baseline_date
				? [
						[
							"baseline_progress",
							__("Baseline progress"),
							"result_progress",
							progressWidth,
						],
						["baseline_delta", __("Δ from baseline"), "result_delta", deltaWidth],
				  ]
				: []),
			["progress", __("Progress"), "result_progress", progressWidth],
			...(comparison.show_plan
				? [
						[
							"planned_progress",
							__("Planned progress", null, "Dinext.ProjectScope.Comparison"),
							"result_progress",
							progressWidth,
						],
						["plan_delta", __("Δ from plan"), "result_delta", deltaWidth],
				  ]
				: []),
			["assignment", __("Assignment"), "result_assignment", 155],
			[
				"planned_end_date",
				__("Planned end", null, "Dinext.ProjectScope.Dates"),
				"plan_date",
				140,
			],
			[
				"expected_end_date",
				__("Expected end", null, "Dinext.ProjectScope.Dates"),
				"date",
				138,
			],
			["actual_end_date", __("Actual end", null, "Dinext.ProjectScope.Dates"), "date", 138],
		].map(([fieldname, label, kind, width, pinned]) => ({
			fieldname,
			label,
			kind,
			width,
			pinned,
		}));
	}

	function progressControls(surface, onChange) {
		const element = node("div", "dinext-scope-progress-controls");
		const controls = {};
		const values = {};
		for (const [fieldname, fieldtype, label, initial, icon] of [
			["show_plan", "Check", __("Plan"), 0],
			["reporting_date", "Date", __("Reporting date"), "", "today"],
			["baseline_date", "Date", __("Baseline date"), "", "calendar"],
		]) {
			const parent = icon ? node("div", "dinext-scope-progress-date") : element;
			if (icon) {
				const glyph = node("span", "dinext-scope-progress-date-icon");
				glyph.innerHTML = frappe.utils.icon(icon, "sm");
				glyph.title = label;
				glyph.setAttribute("aria-hidden", "true");
				parent.append(glyph);
				element.append(parent);
			}
			values[fieldname] = initial;
			const control = frappe.ui.form.make_control({
				parent,
				doc: values,
				df: { fieldname, fieldtype, label, placeholder: icon ? label : undefined },
				only_input: Boolean(icon),
				render_input: true,
			});
			control.set_input(initial);
			control.$input.attr("aria-label", label);
			if (icon) control.$input.attr("title", label);
			control.df.onchange = onChange;
			controls[fieldname] = control;
		}
		surface.disposeControls = () => {
			for (const control of Object.values(controls)) control.datepicker?.destroy();
		};
		return { element, controls };
	}

	function downloadResultTree(query, surface) {
		return downloadWorkbook(
			"dinext_project_scope.analytics.export.download_project_results",
			query,
			"project-results.xlsx",
			surface
		);
	}

	async function downloadWorkbook(method, query, filename, surface, post = false) {
		if (!query || !surface.active()) return;
		try {
			const data = new URLSearchParams(query);
			const endpoint = `/api/method/${method}`;
			const options = { credentials: "same-origin", cache: "no-store" };
			if (post) {
				options.method = "POST";
				options.headers = { "X-Frappe-CSRF-Token": frappe.csrf_token };
				options.body = data;
			}
			const response = await fetch(post ? endpoint : `${endpoint}?${data}`, options);
			if (!response.ok) throw new Error("Export failed");
			const workbook = await response.blob();
			if (!surface.active()) return;
			const url = URL.createObjectURL(workbook);
			const link = node("a");
			link.href = url;
			link.download = filename;
			link.click();
			setTimeout(() => URL.revokeObjectURL(url), 2000);
		} catch {
			if (surface.active()) frappe.msgprint(__("Could not download the report."));
		}
	}

	function resultToolbar(
		frm,
		surface,
		{ refresh, clearFilters, dynamics, canDelete, comparison, exportResults, overdueFilter }
	) {
		const project = frm.doc.name;
		let deleting = false;
		return [
			{
				id: "scope-add-result",
				type: "button",
				title: __("Add Project Deliverable"),
				iconSvg: frappe.utils.icon("add", "sm"),
				disabled: !frm.has_perm("write") || !frappe.model.can_create(DELIVERABLE),
				onClick: () => frappe.new_doc(DELIVERABLE, { project }),
			},
			{
				id: "scope-delete-results",
				type: "button",
				title: __("Delete selected results"),
				iconSvg: frappe.utils.icon("delete", "sm"),
				disabled: ({ table }) => !canDelete || deleting || !table.getCheckedRows().length,
				onClick({ table }) {
					const names = [...new Set(table.getCheckedRows().map((row) => row.document))];
					if (!names.length || deleting) return;
					frappe.confirm(
						__("Delete selected project results ({0})?", [names.length]),
						async () => {
							deleting = true;
							table.refreshToolbar();
							try {
								await frappe.xcall(
									"dinext_project_scope.deliverables.delete_project_results",
									{
										project,
										results: names,
									}
								);
								if (surface.active()) {
									await Promise.all([refresh(), renderProjectProgress(frm)]);
								}
							} catch {
								// Frappe displays the server's permission or link error.
							} finally {
								deleting = false;
								if (surface.active()) table.refreshToolbar();
							}
						}
					);
				},
			},
			{
				id: "scope-overdue-results",
				type: "button",
				title: __("Overdue deliverables"),
				iconSvg: frappe.utils.icon("es-line-alert-triangle", "sm"),
				active: () => overdueFilter.active,
				onClick({ table }) {
					const pending = overdueFilter.toggle();
					table.refreshToolbar();
					return pending;
				},
			},
			{
				id: "scope-clear-result-filters",
				type: "button",
				title: __("Clear filters"),
				iconSvg: frappe.utils.icon("filter-x", "sm"),
				onClick: clearFilters,
			},
			{
				id: "scope-result-dynamics",
				type: "button",
				title: __("Result dynamics"),
				iconSvg: frappe.utils.icon("chart", "sm"),
				active: () => !dynamics.element.hidden,
				onClick({ table }) {
					dynamics.toggle();
					table.refreshToolbar();
				},
			},
			{
				id: "scope-responsibility-matrix",
				type: "button",
				label: "RACI",
				title: __("Responsibility Matrix"),
				iconSvg: frappe.utils.icon("dashboard-list", "sm"),
				onClick: () => toReport("Project Responsibility Matrix", { project }),
			},
			{ id: "scope-progress-comparison", type: "custom", element: comparison },
			{
				id: "scope-download-results",
				type: "button",
				align: "end",
				title: __("Export XLSX"),
				iconSvg: xlsxIcon,
				hidden: !frappe.model.can_export(DELIVERABLE),
				onClick: exportResults,
			},
		];
	}

	async function renderResults(frm) {
		const host = formHost(frm, "custom_scope_results_html");
		if (!host || frm.is_new()) return;
		const project = frm.doc.name;
		const surface = createSurface(host, () => routeMatches("Form", "Project", project));
		surface.root.classList.add("dinext-scope-results");
		surface.root.setAttribute("aria-busy", "true");
		const loader = node("div", "dinext-scope-results-loader");
		const spinner = node("span", "dinext-scope-results-spinner");
		spinner.setAttribute("role", "status");
		spinner.setAttribute("aria-label", __("Loading"));
		loader.append(spinner);
		surface.root.append(loader);
		try {
			await libraries();
			await window.DinextCharts.load();
			if (surface.active()) await mountResults(frm, surface);
		} catch {
			if (surface.active()) setMessage(surface, __("Could not load project results."));
		} finally {
			loader.remove();
			surface.root.removeAttribute("aria-busy");
		}
	}

	async function mountResults(frm, surface) {
		const project = frm.doc.name;
		const canDelete = frm.has_perm("write") && frappe.model.can_delete(DELIVERABLE);
		const charts = node("div", "dinext-scope-charts");
		const table = node("div", "dinext-scope-table dinext-scope-results-table");
		const profiles = [
			["category", __("Category"), __("Deliverables by category")],
			["deliverable_type", __("Deliverable type"), __("Deliverables by type")],
			["status", __("Status"), __("Deliverables by status")],
		];
		const panels = profiles.map(([key, label, title]) =>
			chartFilter(
				surface,
				charts,
				{ key, label, title, formatLabel: (name) => resultFilterLabel(key, name) },
				refresh
			)
		);
		let revision = 0;
		let appliedQuery = null;
		let responsible = "";
		let overdue = false;
		const comparison = progressControls(surface, refresh);
		const dynamics = resultDynamics(surface, project, dynamicsQuery, (value) => {
			responsible = responsible === value ? "" : value;
			return refresh();
		});
		surface.root.append(charts, dynamics.element, table);
		const tableOptions = {
			expand: "roots",
			resultTree: true,
			canCheckRow: ({ row }) => canDelete && isResultRow(row),
			toggleResultFilter,
			toolbarItems: resultToolbar(frm, surface, {
				refresh: () => {
					dynamics.invalidate();
					return refresh();
				},
				clearFilters,
				dynamics,
				canDelete,
				comparison: comparison.element,
				exportResults: () => downloadResultTree(appliedQuery, surface),
				overdueFilter: {
					get active() {
						return overdue;
					},
					toggle() {
						overdue = !overdue;
						return refresh();
					},
				},
			}),
		};

		function toggleResultFilter(field, value) {
			return panels.find(({ key }) => key === field).toggle(value);
		}

		function clearFilters() {
			responsible = "";
			overdue = false;
			for (const panel of panels) panel.setValue("");
			return refresh();
		}

		function dynamicsQuery() {
			const filters = Object.fromEntries(
				panels.map((panel) => [panel.key, panel.getValue() || ""])
			);
			if (responsible) filters.responsible = responsible;
			if (overdue) filters.overdue = 1;
			const { reporting_date, baseline_date } = comparison.controls;
			return {
				project,
				filters: JSON.stringify(filters),
				reporting_date: reporting_date.get_value() || frappe.datetime.get_today(),
				baseline_date: baseline_date.get_value() || "",
			};
		}

		function clearDonuts() {
			for (const panel of panels) panel.clear();
		}

		async function refresh() {
			const request = ++revision;
			const outerQuery = dynamicsQuery();
			appliedQuery = null;
			const { reporting_date: reporting, baseline_date: baseline } = outerQuery;
			if (baseline && baseline > reporting) {
				setMessage(
					surface,
					__("The baseline date must be on or before the reporting date.")
				);
				return;
			}
			dynamics.refresh(outerQuery);
			const query = {
				...outerQuery,
				show_plan: comparison.controls.show_plan.get_value() ? 1 : 0,
			};
			let result;
			try {
				result = await call("project_results", query);
			} catch {
				if (surface.active() && request === revision) {
					surface.table?.clearRowCheck();
					surface.table?.refresh([]);
					clearDonuts();
					setMessage(surface, __("Could not load project results."));
				}
				return;
			}
			if (!surface.active() || request !== revision) return;
			const filters = JSON.parse(outerQuery.filters);
			for (const panel of panels) {
				const { key } = panel;
				panel.draw(result.options[key], result.counts[key], filters[key]);
			}
			await drawGrid(
				surface,
				table,
				resultColumns(table, result.rows, result.comparison),
				result.rows,
				tableOptions
			);
			if (surface.active() && request === revision) appliedQuery = query;
		}

		await refresh();
	}

	function disposeProjectProgress() {
		projectProgressView?.observer?.disconnect();
		projectProgressView?.card?.remove();
		projectProgressView = null;
	}

	async function renderProjectProgress(frm) {
		const host = frm.dashboard?.chart_area?.wrapper?.[0];
		if (!host || frm.is_new()) return;
		const project = frm.doc.name;
		if (!routeMatches("Form", "Project", project)) return;
		disposeProjectProgress();
		const view = { project };
		projectProgressView = view;
		try {
			const [result] = await Promise.all([
				call("project_progress", { project }),
				libraries(),
			]);
			if (view !== projectProgressView || !host.isConnected || result.progress === null)
				return;

			const label = __("Deliverables");
			const fact = formatProgress(result.progress);
			const plan =
				result.planned_progress == null
					? __("Plan is incomplete")
					: formatProgress(result.planned_progress);
			const tooltip = node("div", "custom-tooltip");
			tooltip.id = "scope-deliverables-progress-tooltip";
			tooltip.setAttribute("role", "tooltip");
			tooltip.append(
				node("div", "", __("Plan: {0}", [plan])),
				node("div", "", __("Fact: {0}", [fact]))
			);

			const meter = node("div", "progress-bar-container");
			meter.tabIndex = 0;
			meter.setAttribute("role", "progressbar");
			meter.setAttribute("aria-valuemin", "0");
			meter.setAttribute("aria-valuemax", "100");
			meter.setAttribute("aria-valuenow", String(result.progress));
			meter.setAttribute("aria-label", label);
			meter.setAttribute("aria-describedby", tooltip.id);
			meter.setAttribute(
				"aria-description",
				__(
					"Average progress of unique root deliverables with equal weight for each. Cancelled deliverables are excluded."
				)
			);
			const fill = node("div", "progress-bar-fill");
			fill.style.width = `${result.progress}%`;
			fill.style.backgroundColor = "var(--percent-line, var(--blue-600))";
			meter.append(node("div", "progress-bar-bg"), fill);
			if (result.progress < 100) {
				const tail = node("div", "progress-bar-tail");
				tail.style.left = fill.style.width;
				meter.append(tail);
			}

			const header = node("div", "chart-header");
			header.append(node("span", "chart-title", label), node("span", "chart-percent", fact));
			const card = node("div", "chart-card linear-card dinext-scope-project-progress");
			card.dataset.pwaBar = "deliverables";
			card.append(header, meter, tooltip);
			view.card = card;

			function mount() {
				const row = host.querySelector(".custom-dashboard-grid .dashboard-percents");
				const target = row || host;
				if (card.parentNode === target) return;
				card.classList.toggle("dinext-scope-project-progress--standalone", !row);
				if (row) {
					row.append(card);
				} else {
					host.prepend(card);
					frm.dashboard.show();
					frm.dashboard.chart_area.show();
				}
			}
			view.observer = new MutationObserver(mount);
			view.observer.observe(host, { childList: true, subtree: true });
			mount();
		} catch {
			// Frappe displays the request error.
		}
	}

	async function renderDeliverableProgress(frm) {
		const host = formHost(frm, "progress_html");
		if (!host || frm.is_new()) return;
		const deliverable = frm.doc.name;
		const surface = createSurface(host, () => routeMatches("Form", DELIVERABLE, deliverable));
		await libraries();
		if (!surface.active()) return;
		surface.root.append(
			node("h4", "dinext-scope-heading", __("Planned and recorded progress"))
		);
		const chart = node("div");
		surface.root.append(chart);
		setMessage(surface, __("Loading"));
		try {
			const [result] = await Promise.all([
				call("deliverable_progress", { deliverable }),
				window.DinextCharts.load(),
			]);
			if (!surface.active()) return;
			setMessage(surface, null);
			drawProgress(surface, chart, result);
		} catch {
			if (surface.active()) setMessage(surface, __("Could not load deliverable progress."));
		}
	}

	window.DinextScopeAnalytics = {
		renderResults,
		renderProjectProgress,
		renderDeliverableProgress,
		// Shared by the project form and scope reports.
		node,
		button,
		call,
		libraries,
		routeMatches,
		toReport,
		createSurface,
		expansionIds,
		drawGrid,
		setMessage,
		chartFilter,
		anchorLinkOptions,
		participantAvatar,
		downloadWorkbook,
		xlsxIcon,
	};
})();
