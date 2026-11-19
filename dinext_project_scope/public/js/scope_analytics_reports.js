(() => {
	"use strict";

	const overview = "Project Scope Overview";
	const scopeReports = new Set([
		"Requirement Traceability Matrix",
		"Project Responsibility Matrix",
		"Project Change Impact Matrix",
		overview,
		"Project Deliverable Register",
		"Project Constraint Register",
		"Project Change Request Register",
	]);
	const grids = new WeakMap();
	const controllers = new WeakSet();
	const linkFilters = new WeakSet();
	const targetQuery = "dinext_project_scope.access.project_target_query";
	const downloadMethod = "dinext_project_scope.analytics.export.download";

	function isActive(report) {
		const route = frappe.get_route();
		return (
			route[0] === "query-report" &&
			route[1] === report.report_name &&
			scopeReports.has(route[1])
		);
	}

	function canExport(report) {
		return Boolean(
			report.report_doc?.ref_doctype &&
				frappe.model.can_export(report.report_doc.ref_doctype)
		);
	}

	function keepLinkValuesDuringTitleLookup(report) {
		for (const field of report.filters) {
			if (!["Link", "Dynamic Link"].includes(field.df.fieldtype) || linkFilters.has(field))
				continue;
			linkFilters.add(field);
			const format = field.set_formatted_input;
			field.set_formatted_input = function (value) {
				format.call(this, value);
				if (value && !this.get_input_value()) this.set_input_value(value);
			};
			if (field.value && !field.get_input_value()) field.set_input_value(field.value);
		}
	}

	async function download(report) {
		if (!isActive(report) || !canExport(report)) return;
		const name = report.report_name;
		let filters;
		try {
			filters = report.get_filter_values(true);
		} catch {
			return;
		}
		const parameters = new URLSearchParams({
			report_name: name,
			filters: JSON.stringify(filters),
		});
		try {
			const response = await fetch(`/api/method/${downloadMethod}?${parameters}`, {
				credentials: "same-origin",
				cache: "no-store",
			});
			if (!response.ok) {
				frappe.msgprint(
					response.status === 403
						? __("You do not have access to this export.")
						: __("Could not download the report.")
				);
				return;
			}
			const url = URL.createObjectURL(await response.blob());
			const anchor = document.createElement("a");
			anchor.href = url;
			anchor.download = `${frappe.scrub(name)}.xlsx`;
			anchor.click();
			setTimeout(() => URL.revokeObjectURL(url), 2000);
		} catch {
			frappe.msgprint(__("Could not download the report."));
		}
	}

	function nestRows(rows) {
		const roots = [];
		const levels = [];
		for (const item of rows) {
			const depth = item.depth || 0;
			const row = { ...item, children: [] };
			if (depth && levels[depth - 1]) levels[depth - 1].children.push(row);
			else roots.push(row);
			levels[depth] = row;
			levels.length = depth + 1;
		}
		return roots;
	}

	function addOverviewCharts(surface, charts, rows) {
		const ui = window.DinextScopeAnalytics;
		const groups = new Map();
		for (const row of rows) {
			if (!row.chart) continue;
			if (!groups.has(row.chart)) groups.set(row.chart, []);
			groups.get(row.chart).push(row);
		}
		const route = (row) => ui.toReport(row.route_report, row.route_filters);
		for (const [key, heading] of [
			["requirement_status", __("Requirements by status")],
			["requirement_category", __("Requirements by category")],
			["deliverable_status", __("Deliverables by status")],
			["change_status", __("Change requests by stage")],
		]) {
			ui.donut(surface, charts, heading, groups.get(key) || [], route);
		}
		ui.timeline(surface, charts, groups.get("change_dates") || [], route);
	}

	function addProgressPicker(surface, host, project, initial) {
		const ui = window.DinextScopeAnalytics;
		const panel = ui.node("section", "dinext-scope-chart-card");
		panel.append(ui.node("h4", "dinext-scope-heading", __("Planned and recorded progress")));
		host.append(panel);
		if (!initial) {
			panel.append(ui.node("p", "dinext-scope-empty", __("No deliverables")));
			return;
		}
		const field = ui.node("div", "dinext-scope-progress-picker");
		const output = ui.node("div", "dinext-scope-progress-output");
		panel.append(field, output);
		let revision = 0;
		const picker = frappe.ui.form.make_control({
			parent: $(field),
			df: {
				fieldtype: "Link",
				fieldname: "deliverable",
				label: __("Project Deliverable"),
				options: "Project Deliverable",
				only_select: true,
				get_query: () => ({ query: targetQuery, filters: { project } }),
				onchange: showProgress,
			},
			render_input: true,
		});
		picker.refresh();
		picker.set_value(initial);

		async function showProgress() {
			const deliverable = picker.value;
			const request = ++revision;
			const old = output.querySelector(".dinext-scope-chart");
			if (old) surface.unregisterChart(old);
			output.replaceChildren();
			if (!deliverable) return;
			output.append(ui.node("p", "dinext-scope-empty", __("Loading")));
			try {
				const result = await ui.call("deliverable_progress", { deliverable });
				if (request === revision && surface.active())
					ui.drawProgress(surface, output, result);
			} catch {
				if (request === revision && surface.active()) {
					output.replaceChildren(
						ui.node(
							"p",
							"dinext-scope-empty",
							__("Could not load deliverable progress.")
						)
					);
				}
			}
		}
	}

	async function showReport(report, result) {
		const ui = window.DinextScopeAnalytics;
		const name = report.report_name;
		const container = report.$report.get(0);
		const surface = ui.createSurface(container, () => ui.routeMatches("query-report", name));
		grids.set(report, surface);
		const page = report.page.main.get(0);
		page.classList.add("dinext-scope-report-page");
		const table = ui.node("div", "dinext-scope-table");
		surface.root.append(table);

		if (name === overview) {
			const project = report.get_filter_value("project");
			const actions = ui.node("div", "dinext-scope-overview-actions");
			for (const target of [
				"Requirement Traceability Matrix",
				"Project Responsibility Matrix",
				"Project Change Impact Matrix",
				"Project Constraint Register",
			]) {
				actions.append(ui.button(__(target), () => ui.toReport(target, { project })));
			}
			surface.root.prepend(actions);
			const charts = ui.node("div", "dinext-scope-charts");
			const progress = ui.node("div", "dinext-scope-overview-progress");
			surface.root.append(charts, progress);
			window.DinextCharts.load()
				.then(() => {
					if (!surface.active()) return;
					addOverviewCharts(surface, charts, result.result);
					addProgressPicker(
						surface,
						progress,
						project,
						result.result[0]?.progress_deliverable
					);
				})
				.catch(() => {
					if (surface.active())
						charts.append(
							ui.node("p", "dinext-scope-empty", __("Could not load charts."))
						);
				});
		}
		const rows = name === overview ? result.result.filter((row) => !row.chart) : result.result;
		await ui.drawGrid(surface, table, result.columns, nestRows(rows), {
			expand:
				name === "Requirement Traceability Matrix"
					? "roots"
					: name === "Project Responsibility Matrix"
					? "all"
					: null,
			export: canExport(report) ? () => download(report) : null,
			fullscreenShell: page,
		});
	}

	function install(report) {
		if (controllers.has(report)) return;
		controllers.add(report);
		const render = report.render_datatable;
		const refresh = report.refresh;
		const toggle = report.toggle_report;
		const menu = report.get_menu_items;
		const footer = report.show_footer_message;
		const addChartButtons = report.add_chart_buttons_to_toolbar;
		const addCardButton = report.add_card_button_to_toolbar;

		report.refresh = function (...args) {
			if (
				isActive(this) &&
				this.filters.some(
					(field) => (field.df.reqd || field.df.mandatory) && !field.get_value()
				)
			) {
				this.hide_loading_screen();
				this.toggle_report(false);
				this.toggle_message(true, __("Please set filters"));
				return;
			}
			return refresh.apply(this, args);
		};
		report.render_datatable = function (...args) {
			const source = this.raw_data?.columns?.[0]?.scope_report;
			if (!isActive(this) && !source) return render.apply(this, args);
			if (!isActive(this) || source !== this.report_name) return;
			showReport(this, this.raw_data).catch(() => {
				const surface = grids.get(this);
				if (surface?.active())
					window.DinextScopeAnalytics.setMessage(
						surface,
						__("Could not display the report.")
					);
			});
		};
		report.toggle_report = function (visible, ...args) {
			if (isActive(this) && !visible) {
				grids.get(this)?.dispose();
				grids.delete(this);
			}
			return toggle.call(this, visible, ...args);
		};
		report.get_menu_items = function (...args) {
			const items = menu.apply(this, args);
			if (!isActive(this)) return items;
			const standard = new Set([__("Refresh"), __("Edit"), __("User Permissions")]);
			return [
				...items.filter((item) => standard.has(item.label)),
				{
					label: __("Download Excel"),
					action: () => download(this),
					condition: () => canExport(this),
					standard: true,
				},
			];
		};
		report.show_footer_message = function (...args) {
			if (!isActive(this)) return footer.apply(this, args);
			this.$report_footer?.remove();
		};
		report.add_chart_buttons_to_toolbar = function (...args) {
			if (!isActive(this)) return addChartButtons.apply(this, args);
		};
		report.add_card_button_to_toolbar = function (...args) {
			if (!isActive(this)) return addCardButton.apply(this, args);
		};
	}

	window.DinextScopeReports = {
		async bind(report) {
			const expectedReport = report.report_name;
			await window.DinextScopeAnalytics.libraries();
			if (expectedReport !== report.report_name || !isActive(report)) return;
			keepLinkValuesDuringTitleLookup(report);
			install(report);
			report.page.clear_menu();
			report.menu_items = report.get_menu_items();
			report.set_menu_items();
		},
	};
})();
