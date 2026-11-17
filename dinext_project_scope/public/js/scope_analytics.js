(() => {
	"use strict";

	const ASSET_ROOT = "/assets/dinext_project_scope";
	const API = "dinext_project_scope.analytics.data";
	const EMPTY = "__dinext_scope_no_value__";
	const DELIVERABLE = "Project Deliverable";
	const tones = ["red", "yellow", "green", "light-green", "cyan", "blue", "gray"];
	const surfaces = new Map();
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
				window.DinextCharts?.dispose(element);
				charts.delete(element);
			},
			dispose() {
				this.clearCharts();
				resize?.disconnect();
				theme.disconnect();
				this.table?.destroy();
				this.table = null;
				root.remove();
				if (surfaces.get(host) === surface) surfaces.delete(host);
			},
			registerChart(element, option, onClick) {
				charts.set(element, { option, onClick, instance: null });
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
			if (item.onClick) item.instance?.on("click", item.onClick);
		}

		const resize = window.ResizeObserver
			? new ResizeObserver((entries) => {
					for (const entry of entries) mount(entry.target);
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
			const item = badge(entry.code);
			item.title = entry.label;
			item.setAttribute("aria-label", `${entry.code} · ${entry.label}`);
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
		const status = row.status ? __(row.status) : "";
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

	function labelCell(row) {
		const holder = node("span", "dinext-scope-label");
		if (row.document) {
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
			holder.append(node("span", "", row.label || ""));
		}
		if (row.slot_label) holder.append(node("span", "dinext-scope-note", row.slot_label));
		return holder;
	}

	function cellRenderer(column) {
		return (params) => {
			const row = params.data || {};
			const value = params.value;
			switch (column.kind) {
				case "label":
					return labelCell(row);
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
				case "count":
					return node("span", "", value ?? "");
				default:
					return node("span", "", value ?? "");
			}
		};
	}

	function tableColumns(columns) {
		const groups = new Map();
		const result = [];
		for (const column of columns) {
			const item = {
				field: column.fieldname,
				headerName: column.label,
				width: column.width || 135,
				minWidth: 76,
				cellDataType: false,
			};
			if (column.kind === "label") item.render = cellRenderer(column);
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
		const generation = (surface.gridGeneration || 0) + 1;
		surface.gridGeneration = generation;
		surface.table?.destroy();
		surface.table = null;
		container.replaceChildren();
		const available = rows.length > 0;
		container.hidden = !available;
		setMessage(surface, available ? null : __("No records match the filters."));
		if (!available) return;
		const grid = node("div", "dinext-scope-grid-target");
		container.append(grid);
		const table = await window.DinextTable.create({
			container: grid,
			data: rows,
			columns: tableColumns(columns),
			expandedIds: expansionIds(rows, options.expand),
			filter: { enabled: false },
			edit: false,
			toolbar: {
				presets: ["tree", "fullscreen"],
				items: options.export
					? [
							{
								id: "scope-export",
								type: "custom",
								render: ({ host }) =>
									host.append(button(__("Download Excel"), options.export)),
							},
					  ]
					: [],
			},
			fullscreen: { target: "shell", shell: options.fullscreenShell || surface.root },
			layout: { height: "auto", minHeight: 76, maxHeight: "min(65vh, 660px)" },
			gridOptions: {
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
				onCellClicked({ data, event }) {
					if (!data || event.target.closest("a, button, .dinext-table-tree-toggle"))
						return;
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
					if (!data || event.target.closest("a, button")) return;
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
					if (event.key !== "Enter") return;
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
		else surface.table = table;
	}

	function chartColors() {
		const css = getComputedStyle(document.documentElement);
		return {
			text: css.getPropertyValue("--text-color").trim() || "#656f7b",
			muted: css.getPropertyValue("--text-muted").trim() || "#656f7b",
			border: css.getPropertyValue("--border-color").trim() || "#c1cddd",
		};
	}

	function donut(surface, container, title, items, onSelect = null, options = {}) {
		const card = node("section", "dinext-scope-chart-card");
		card.append(node("h4", "dinext-scope-heading", title));
		container.append(card);
		if (!items.length) {
			card.append(node("div", "dinext-scope-empty", __("No data")));
			return;
		}
		const chart = node("div", "dinext-scope-chart dinext-scope-chart--donut");
		chart.setAttribute("aria-hidden", String(Boolean(onSelect)));
		const labels = node("div", "dinext-scope-chart-legend");
		for (const [index, item] of items.entries()) {
			const label =
				item.label ||
				(item.name
					? options.translate
						? __(item.name)
						: item.name
					: __("Not specified"));
			const action = onSelect
				? button(
						`${label} · ${item.count}`,
						() => onSelect(item),
						"dinext-scope-legend-item"
				  )
				: node("span", "dinext-scope-legend-item", `${label} · ${item.count}`);
			const color = node("span", "dinext-scope-legend-dot");
			color.style.setProperty(
				"--scope-legend-color",
				chartPalette[index % chartPalette.length]
			);
			action.prepend(color);
			labels.append(action);
		}
		card.append(chart, labels);
		surface.registerChart(
			chart,
			() => ({
				color: chartPalette,
				backgroundColor: "transparent",
				animation: false,
				aria: { enabled: !onSelect },
				title: {
					text: String(items.reduce((sum, item) => sum + item.count, 0)),
					left: "center",
					top: "center",
					textStyle: { color: chartColors().text, fontWeight: 600, fontSize: 23 },
				},
				tooltip: { trigger: "item", renderMode: "richText" },
				series: [
					{
						type: "pie",
						radius: ["59%", "82%"],
						label: { show: false },
						data: items.map((item) => ({
							name:
								item.label ||
								(item.name
									? options.translate
										? __(item.name)
										: item.name
									: __("Not specified")),
							value: item.count,
						})),
					},
				],
			}),
			onSelect && ((event) => onSelect(items[event.dataIndex]))
		);
	}

	function timeline(surface, container, points, onSelect) {
		const card = node("section", "dinext-scope-chart-card");
		card.append(node("h4", "dinext-scope-heading", __("Change requests by date")));
		container.append(card);
		if (!points.length) {
			card.append(node("div", "dinext-scope-empty", __("No data")));
			return;
		}
		const chart = node("div", "dinext-scope-chart dinext-scope-chart--timeline");
		chart.setAttribute("aria-hidden", "true");
		const dates = node("div", "dinext-scope-chart-legend");
		for (const item of points) {
			dates.append(
				button(
					`${frappe.datetime.str_to_user(item.chart_name)} · ${item.count}`,
					() => onSelect(item),
					"dinext-scope-legend-item"
				)
			);
		}
		card.append(chart, dates);
		surface.registerChart(
			chart,
			() => {
				const colors = chartColors();
				return {
					backgroundColor: "transparent",
					color: chartPalette,
					animation: false,
					grid: { left: 34, right: 18, bottom: 31, top: 14 },
					tooltip: { trigger: "axis", renderMode: "richText" },
					xAxis: {
						type: "category",
						data: points.map((item) => frappe.datetime.str_to_user(item.chart_name)),
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
			(event) => onSelect(points[event.dataIndex])
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
					legend: { textStyle: { color: colors.text } },
					grid: { left: 49, right: 22, bottom: 33, top: 39 },
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

	function formHost(frm, fieldname) {
		return frm.fields_dict[fieldname]?.$wrapper?.get(0);
	}

	function statusLabel(name) {
		return name ? __(name) : __("Not specified");
	}

	function resultColumns() {
		return [
			["label", __("Deliverable / Work"), "label", 285],
			["status", __("Status"), "status", 155],
			["deliverable_type", __("Deliverable type"), null, 150],
			["category", __("Category"), null, 150],
			["progress", __("Progress"), "progress", 85],
			["accountable", __("Accountable"), "accountable", 188],
			["planned_end_date", __("Planned end"), "plan_date", 140],
			["expected_end_date", __("Expected end"), "date", 138],
			["actual_end_date", __("Actual end"), "date", 138],
		].map(([fieldname, label, kind, width]) => ({ fieldname, label, kind, width }));
	}

	async function renderResults(frm) {
		const host = formHost(frm, "custom_scope_results_html");
		if (!host || frm.is_new()) return;
		const project = frm.doc.name;
		const surface = createSurface(host, () => routeMatches("Form", "Project", project));
		await libraries();
		if (!surface.active()) return;
		const controls = node("div", "dinext-scope-filter-strip");
		const charts = node("div", "dinext-scope-charts");
		const table = node("div", "dinext-scope-table");
		surface.root.append(controls, charts, table);
		const profiles = [
			["category", __("Category"), __("Deliverables by category")],
			["deliverable_type", __("Deliverable type"), __("Deliverables by type")],
			["status", __("Status"), __("Deliverables by status")],
		];
		const selects = new Map();
		for (const [key, label] of profiles) {
			const control = node("label", "dinext-scope-control");
			control.append(node("span", "", label));
			const select = node("select", "form-control input-xs");
			select.addEventListener("change", refresh);
			selects.set(key, select);
			control.append(select);
			controls.append(control);
		}
		controls.append(
			button(__("Clear filters"), () => {
				for (const select of selects.values()) select.value = "";
				refresh();
			})
		);
		let revision = 0;

		async function refresh() {
			const request = ++revision;
			const filters = Object.fromEntries(
				Array.from(selects, ([key, control]) => [key, control.value])
			);
			let result;
			try {
				result = await call("project_results", {
					project,
					filters: JSON.stringify(filters),
				});
			} catch {
				if (surface.active() && request === revision) {
					surface.table?.destroy();
					surface.table = null;
					surface.clearCharts();
					charts.replaceChildren();
					table.replaceChildren();
					setMessage(surface, __("Could not load project results."));
				}
				return;
			}
			if (!surface.active() || request !== revision) return;
			surface.clearCharts();
			charts.replaceChildren();
			for (const [key, label, chartLabel] of profiles) {
				const select = selects.get(key);
				select.replaceChildren(new Option(__("All"), ""));
				for (const option of result.options[key]) {
					const label =
						key === "status"
							? statusLabel(option.name)
							: option.name || __("Not specified");
					select.add(new Option(label, option.name || EMPTY));
				}
				select.value = filters[key] || "";
				donut(
					surface,
					charts,
					chartLabel,
					result.counts[key],
					(item) => {
						select.value = item.name || EMPTY;
						refresh();
					},
					{ translate: key === "status" }
				);
			}
			await drawGrid(surface, table, resultColumns(), result.rows, { expand: "roots" });
		}

		setMessage(surface, __("Loading"));
		await window.DinextCharts.load();
		if (surface.active()) await refresh();
	}

	async function renderProjectProgress(frm) {
		const host = formHost(frm, "custom_scope_deliverables_progress_html");
		if (!host || frm.is_new()) return;
		const project = frm.doc.name;
		const surface = createSurface(host, () => routeMatches("Form", "Project", project));
		await libraries();
		if (!surface.active()) return;
		surface.root.append(node("h4", "dinext-scope-heading", __("Deliverables progress")));
		setMessage(surface, __("Loading"));
		try {
			const result = await call("project_progress", { project });
			if (!surface.active()) return;
			if (result.progress === null) {
				setMessage(surface, __("No deliverables"));
				return;
			}
			setMessage(surface, null);
			const progress = node("div", "dinext-scope-project-progress");
			const meter = node("progress");
			meter.max = 100;
			meter.value = result.progress;
			meter.setAttribute("aria-label", __("Deliverables progress"));
			progress.append(meter, node("strong", "", formatProgress(result.progress)));
			surface.root.append(progress);
		} catch {
			if (surface.active()) setMessage(surface, __("Could not load project results."));
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
		// Shared by the scope reports adapter.
		node,
		button,
		call,
		libraries,
		routeMatches,
		toReport,
		createSurface,
		drawGrid,
		setMessage,
		donut,
		timeline,
		drawProgress,
	};
})();
