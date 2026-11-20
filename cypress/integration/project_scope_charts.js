import {
	downloadExcel,
	exact,
	openReport,
	reportShown,
	rowLink,
	table,
	useReportFixture,
} from "../support/scope_reports";

const resultHost = '[data-fieldname="custom_scope_results_html"]';
const chartCard = ".dinext-scope-chart-card";
const overview = "Project Scope Overview";
const changes = "Project Change Request Register";
const traceability = "Requirement Traceability Matrix";
const responsibility = "Project Responsibility Matrix";
const progressPicker = '.dinext-scope-progress-picker input[data-fieldname="deliverable"]';

function chart(title) {
	return cy.contains(chartCard, title).find(".dinext-scope-chart");
}

function chartOption(subject, assertion) {
	return subject.should(($host) => {
		const target = $host[0];
		const instance = target.ownerDocument.defaultView.echarts?.getInstanceByDom(target);
		expect(instance, "mounted chart").to.exist;
		assertion(instance.getOption(), instance);
	});
}

function clickChartPoint(title, locate) {
	chart(title)
		.find("canvas")
		.first()
		.then(($canvas) => {
			const canvas = $canvas[0];
			canvas.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
			const target = canvas.closest(".dinext-scope-chart");
			const instance = target.ownerDocument.defaultView.echarts.getInstanceByDom(target);
			const [x, y] = locate(instance);
			cy.wrap($canvas)
				.should(() => {
					const rect = canvas.getBoundingClientRect();
					expect(
						canvas.ownerDocument.elementFromPoint(rect.left + x, rect.top + y)
					).to.eq(canvas);
				})
				.click(Math.round(x), Math.round(y), { scrollBehavior: false });
		});
}

function clickPieSegment(title, label) {
	clickChartPoint(title, (instance) => {
		const series = instance.getModel().getSeriesByIndex(0).getData();
		const index = instance.getOption().series[0].data.findIndex((item) => item.name === label);
		expect(index, "segment for the selected category").to.be.at.least(0);
		const { cx, cy: centerY, startAngle, endAngle, r, r0 } = series.getItemLayout(index);
		const angle = (startAngle + endAngle) / 2;
		const radius = (r0 + r) / 2;
		return [cx + radius * Math.cos(angle), centerY + radius * Math.sin(angle)];
	});
}

function showResults(project) {
	cy.visit(`/app/project/${project}`);
	cy.get('button[data-fieldname="custom_результаты"]').click();
	cy.get(resultHost).should("be.visible");
}

function resultFilter(title, fieldname) {
	return cy
		.contains(`${resultHost} ${chartCard}`, title)
		.find(`.frappe-control[data-fieldtype="Select"][data-fieldname="${fieldname}"] select`);
}

function resultCells(label) {
	return rowLink(label)
		.closest(".ag-row")
		.invoke("attr", "row-id")
		.then((id) => cy.get(`${resultHost} .ag-center-cols-container [row-id="${id}"]`));
}

describe("Project scope charts", () => {
	const fixture = useReportFixture();

	it("shows the configured type, accountable avatar and progress in the results tree", () => {
		showResults(fixture.project);
		const visibleHeaders = `${resultHost} .ag-header-cell[col-id] .ag-header-cell-label`;
		cy.get(visibleHeaders).should(($headers) => {
			expect($headers.length).to.be.greaterThan(1);
			for (const header of $headers) {
				const win = header.ownerDocument.defaultView;
				expect(win.getComputedStyle(header).justifyContent).to.eq("center");
			}
		});
		rowLink(`${fixture.title} result`)
			.closest('[col-id="label"]')
			.should("not.have.css", "text-align", "center");

		resultCells(`${fixture.title} result`).within(() => {
			cy.get(".ag-cell").should(($cells) => {
				for (const cell of $cells) {
					const win = cell.ownerDocument.defaultView;
					expect(win.getComputedStyle(cell).textAlign).to.eq("center");
				}
			});
			cy.get('[col-id="deliverable_type"]')
				.should("not.contain.text", fixture.title)
				.find(`[title="${fixture.title}"] img`)
				.should(([icon]) => {
					expect(new URL(icon.src).pathname).to.eq(fixture.type_icon);
					expect(icon.naturalWidth).to.be.greaterThan(0);
				});
			cy.get('[col-id="deliverable_type"]')
				.closest(".ag-row")
				.should(([row]) => {
					expect(row.style.getPropertyValue("--scope-result-type-color")).to.eq(
						fixture.type_color
					);
					expect(
						row.ownerDocument.defaultView.getComputedStyle(row).backgroundColor
					).not.to.eq("rgba(0, 0, 0, 0)");
				});
			cy.get('[col-id="accountable"] .avatar[role="img"]')
				.should(([avatar]) => expect(avatar.title).to.eq(fixture.title))
				.find("img")
				.should(([photo]) => {
					expect(new URL(photo.src).pathname).to.eq(fixture.avatar_image);
					expect(photo.naturalWidth).to.be.greaterThan(0);
				});
			cy.get('[col-id="progress"] .progress[role="progressbar"]')
				.should(([meter]) => expect(meter.getAttribute("aria-valuenow")).to.eq("20"))
				.find(".progress-bar")
				.should("be.visible");
		});
		resultCells(`${fixture.title} shared component`)
			.find('[col-id="accountable"] .avatar .standard-image')
			.should("have.text", "C");
		resultCells(`${fixture.title} shared component`)
			.find('[col-id="deliverable_type"] svg')
			.should("be.visible");
		resultCells(`${fixture.title} peer`)
			.find('[col-id="accountable"]')
			.should("have.text", "—");
	});

	it("opens the current project's responsibility matrix from the results toolbar", () => {
		cy.login(fixture.actor, fixture.password);
		showResults(fixture.project);
		resultFilter("Deliverables by type", "deliverable_type").select(fixture.title);
		resultFilter("Deliverables by category", "category").select(`${fixture.title} secondary`);
		cy.contains(`${resultHost} [role="status"]`, "No records match the filters.").should(
			"be.visible"
		);
		cy.contains(`${resultHost} .dinext-table-toolbar button`, "Project Responsibility Matrix")
			.should("be.visible")
			.click();
		reportShown(responsibility, { project: fixture.project });
		cy.window().should(({ frappe }) => {
			expect(frappe.query_report.get_filter_value("deliverable_type") || "").to.eq("");
		});
	});

	it("keeps the result donuts compact and uses a brighter palette in the light theme", () => {
		showResults(fixture.project);
		const theme = (mode) => cy.window().then(({ frappe }) => frappe.ui.set_theme(mode));
		const byCategory = () =>
			cy
				.contains(`${resultHost} ${chartCard}`, "Deliverables by category")
				.find(".dinext-scope-chart:visible");
		theme("light");
		cy.get(`${resultHost} .dinext-scope-charts`).should(([charts]) => {
			const surface = charts.closest(".dinext-scope-analytics");
			expect(
				charts.getBoundingClientRect().top - surface.getBoundingClientRect().top
			).to.be.at.most(1);
		});
		chartOption(byCategory(), (option) => expect(option.color[0]).to.eq("#2868eb"));
		theme("dark");
		chartOption(byCategory(), (option) => expect(option.color[0]).to.eq("#3976b7"));
		theme("light");
		chartOption(byCategory(), (option) => expect(option.color[0]).to.eq("#2868eb"));
	});

	it("recounts unique results after an actual pie segment filters the two shared branches", () => {
		showResults(fixture.project);
		const categoryChart = "Deliverables by category";
		const child = `${fixture.title} shared component`;
		const category = `${fixture.title} secondary`;
		cy.get(`${resultHost} ${chartCard}`).should("have.length", 3);
		chartOption(chart(categoryChart), (option) => {
			expect(option.series[0].data).to.deep.include.members([
				{ name: fixture.title, value: 2 },
				{ name: category, value: 1 },
			]);
		});
		clickPieSegment(categoryChart, category);
		resultFilter(categoryChart, "category").should("have.value", category);
		cy.get(`${table} .ag-center-cols-container .dinext-scope-context-row`).should(
			"have.length",
			2
		);
		cy.get(`${table} a`).should(($links) => {
			expect($links.filter((_, link) => link.textContent === child)).to.have.length(2);
		});
		for (const [title, name] of [
			[categoryChart, category],
			["Deliverables by type", category],
			["Deliverables by status", "Not Started"],
		]) {
			chartOption(chart(title), (option) => {
				expect(option.series[0].data).to.deep.eq([{ name, value: 1 }]);
			});
		}
		cy.screenshot("project-results-charts");
		rowLink(child).first().click();
		cy.location("pathname").should("eq", `/app/project-deliverable/${fixture.shared}`);
	});

	it("filters results with the Frappe dropdowns below the charts", () => {
		showResults(fixture.project);
		const filters = [
			["Deliverables by category", "category"],
			["Deliverables by type", "deliverable_type"],
			["Deliverables by status", "status"],
		];
		for (const [title, fieldname] of filters) {
			resultFilter(title, fieldname).should(($input) => {
				const card = $input[0].closest(chartCard);
				const donut = card.querySelector(".dinext-scope-chart--donut");
				expect($input[0].getBoundingClientRect().top).to.be.at.least(
					donut.getBoundingClientRect().bottom
				);
			});
		}
		cy.get(`${resultHost} .dinext-scope-chart-legend`).should("not.exist");
		resultFilter("Deliverables by type", "deliverable_type").select(fixture.title);
		rowLink(`${fixture.title} peer`).should("be.visible");
		rowLink(`${fixture.title} shared component`).should("not.exist");
		resultFilter("Deliverables by status", "status").select("Not Started");
		chartOption(chart("Deliverables by status"), (option) => {
			expect(option.series[0].data).to.deep.eq([{ name: "Not Started", value: 2 }]);
		});
		resultFilter("Deliverables by category", "category").select(`${fixture.title} secondary`);
		cy.contains(`${resultHost} [role="status"]`, "No records match the filters.").should(
			"be.visible"
		);
		cy.get(`${resultHost} select`).should("have.length", 3);
		cy.contains(`${resultHost} button`, "Clear filters").click();
		for (const [title, fieldname] of filters) {
			resultFilter(title, fieldname).should("have.value", "");
		}
		chartOption(chart("Deliverables by status"), (option) => {
			expect(option.series[0].data).to.deep.eq([{ name: "Not Started", value: 3 }]);
		});
	});

	it("keeps the result tree's first column visible during horizontal scrolling", () => {
		cy.viewport(1050, 900);
		showResults(fixture.project);
		const header = `${resultHost} ${table} .ag-header-cell[col-id="label"]`;
		const cell = `${resultHost} ${table} .ag-cell[col-id="label"]`;
		cy.get(header)
			.should("be.visible")
			.then(($header) => {
				const left = $header[0].getBoundingClientRect().left;
				cy.get(`${resultHost} ${table} .ag-body-horizontal-scroll-viewport`)
					.scrollTo("right")
					.should(($viewport) => expect($viewport[0].scrollLeft).to.be.greaterThan(0));
				cy.get(header).should(($column) => {
					expect($column[0].getBoundingClientRect().left).to.be.closeTo(left, 1);
				});
				cy.get(cell)
					.first()
					.should(($column) => {
						expect($column[0].getBoundingClientRect().left).to.be.closeTo(left, 1);
					});
				rowLink(`${fixture.title} result`).should("be.visible");
			});
	});

	it("plots recorded values and a separate current plan on a result card", () => {
		cy.visit(`/app/project-deliverable/${fixture.result}`);
		const host = '[data-fieldname="progress_html"]';
		cy.contains(host, "No actual progress was recorded before").should("be.visible");
		chartOption(cy.get(`${host} .dinext-scope-chart--progress`), (option, instance) => {
			const [plan, actual] = option.series;
			expect(plan.name).to.eq("Current plan");
			expect(plan.step).to.eq(false);
			expect(plan.data[0][1]).to.eq(0);
			expect(plan.data).to.deep.include([Date.parse(fixture.planned_end), 100]);
			expect(actual.name).to.eq("Recorded progress");
			expect(actual.data.map(([, value]) => value)).to.deep.eq([60, 20]);
			const legend = instance.getModel().getComponent("legend").getData();
			expect(legend.map((entry) => entry.get("name"))).to.deep.eq([
				"Current plan",
				"Recorded progress",
			]);
		});
	});

	it("explains a missing planned interval on a result card", () => {
		cy.visit(`/app/project-deliverable/${fixture.hidden_result}`);
		cy.contains(
			'[data-fieldname="progress_html"]',
			"Set both planned dates to show the plan."
		).should("be.visible");
	});

	it("drills from the overview creation-date chart to the same project and inclusive date", () => {
		openReport(overview, { project: fixture.project });
		const dates = "Change requests by date";
		chartOption(chart(dates), (option) => {
			expect(option.series[0].type).to.eq("bar");
			expect(option.series[0].data).to.deep.eq([1]);
		});
		clickChartPoint(dates, (instance) =>
			instance.convertToPixel({ seriesIndex: 0 }, [0, 0.5])
		);
		reportShown(changes, {
			project: fixture.project,
			from_date: fixture.change_date,
			to_date: fixture.change_date,
		});
		downloadExcel("project_change_request_register", {
			project: fixture.project,
			from_date: fixture.change_date,
			to_date: fixture.change_date,
		});
		rowLink(`${fixture.title} change`).click();
		cy.location("pathname").should("eq", `/app/project-change-request/${fixture.change}`);
	});

	it("shows recorded progress in the overview and lets the user select a different result", () => {
		openReport(overview, { project: fixture.project });
		const output = ".dinext-scope-overview-progress .dinext-scope-chart--progress";
		chartOption(cy.get(output), (option) => {
			expect(option.series.map((series) => series.name)).to.deep.eq([
				"Current plan",
				"Recorded progress",
			]);
		});
		cy.get(progressPicker).clear().type(fixture.result);
		cy.contains(
			'.dinext-scope-progress-picker .awesomplete [role="option"]',
			`${fixture.title} result`
		).click();
		chartOption(cy.get(output), (option) => {
			expect(option.series.find((series) => series.name === "Recorded progress").data).not.to
				.be.empty;
		});
		cy.get(progressPicker).clear().type(fixture.shared);
		cy.contains(
			'.dinext-scope-progress-picker .awesomplete [role="option"]',
			"shared component"
		).click();
		chartOption(cy.get(output), (option) => {
			expect(
				option.series
					.find((series) => series.name === "Recorded progress")
					.data.map(([, value]) => value)
			).to.deep.eq([60, 20]);
		});
	});

	it("drills from a requirement-category legend under the user's project access", () => {
		cy.login(fixture.actor, fixture.password);
		openReport(overview, { project: fixture.project });
		cy.contains(chartCard, "Requirements by status")
			.contains("button", exact("In Progress · 1"))
			.should("be.visible");
		cy.contains(chartCard, "Change requests by stage")
			.contains("button", exact("Draft · 1"))
			.should("be.visible");
		chartOption(chart("Requirements by category"), (option) => {
			expect(option.series[0].data).to.deep.have.members([
				{ name: fixture.title, value: 2 },
				{ name: `${fixture.title} secondary`, value: 1 },
			]);
		});
		cy.contains(chartCard, "Requirements by category")
			.contains("button", exact(`${fixture.title} · 2`))
			.click();
		reportShown(traceability, { project: fixture.project, kind: fixture.title });
		rowLink(`${fixture.title} unlinked`).should("be.visible");
		rowLink(`${fixture.title} analyzed child`).should("not.exist");
	});

	it("denies other-project progress data and leaves it out of the progress picker", () => {
		cy.login(fixture.actor, fixture.password);
		openReport(overview, { project: fixture.project });
		cy.intercept("POST", "**/api/method/frappe.desk.search.search_link", (request) => {
			const text =
				typeof request.body === "string"
					? new URLSearchParams(request.body).get("txt")
					: request.body.txt;
			if (text === fixture.hidden_result) request.alias = "hiddenProgressSearch";
		});
		cy.get(progressPicker).clear().type(fixture.hidden_result);
		cy.wait("@hiddenProgressSearch").its("response.body.message").should("deep.eq", []);
		cy.contains(
			'.dinext-scope-progress-picker .awesomplete [role="option"]',
			"hidden deliverable"
		).should("not.exist");
		cy.request({
			url: "/api/method/dinext_project_scope.analytics.data.deliverable_progress",
			qs: { deliverable: fixture.hidden_result },
			failOnStatusCode: false,
		})
			.its("status")
			.should("eq", 403);
		cy.request({
			url: "/api/method/dinext_project_scope.analytics.data.project_results",
			qs: { project: fixture.hidden_project },
			failOnStatusCode: false,
		})
			.its("status")
			.should("eq", 403);
	});

	it("localizes overview chart titles and the progress legend for a Russian user", () => {
		cy.login(fixture.russian_actor, fixture.password);
		cy.visit(`/app/query-report/${encodeURIComponent(overview)}?project=${fixture.project}`);
		cy.get(".page-title:visible").should("contain.text", "Обзор содержания проекта");
		for (const label of [
			"Требования по статусам",
			"Требования по категориям",
			"Результаты по статусам",
			"Запросы на изменение по стадиям",
			"Запросы на изменение по датам создания",
		]) {
			cy.contains(chartCard, label).should("be.visible");
		}
		chartOption(chart("Плановый и фактический прогресс"), (option) => {
			expect(option.series.map((series) => series.name)).to.deep.eq([
				"Текущий план",
				"Фактический прогресс",
			]);
		});
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('[data-fieldname="custom_scope_deliverables_progress_html"] progress').should(
			"have.attr",
			"title",
			"Средняя готовность уникальных корневых результатов с равным весом каждого. Отменённые результаты и шаблоны исключаются."
		);
	});

	it("uses Russian scope labels even when other apps translate the same words", () => {
		cy.login(fixture.russian_actor, fixture.password);
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_результаты"]').should("be.visible");
		cy.window().then(({ frappe }) => {
			Object.assign(frappe._messages, {
				All: "Всего",
				Completed: "Завершено",
				Done: "Готово",
			});
		});
		cy.get('button[data-fieldname="custom_результаты"]').click();
		resultFilter("Результаты по статусам", "status")
			.find('option[value=""]')
			.should("have.text", "Все");
		cy.window().then(({ frappe }) => {
			frappe.route_options = { project: fixture.project };
			return frappe.set_route("query-report", "Project Deliverable Register");
		});
		cy.get('.page-form:visible [data-fieldname="status"] option[value="Completed"]').should(
			"have.text",
			"Завершён"
		);
		cy.window().then(({ frappe }) => {
			frappe.route_options = { project: fixture.project };
			return frappe.set_route("query-report", traceability);
		});
		cy.get('.page-form:visible [data-fieldname="status"] option[value="Done"]').should(
			"have.text",
			"Реализовано"
		);
	});

	it("shows Russian result and change request labels and workflow actions", () => {
		const workflowMenu = ".page-container:visible .actions-btn-group";
		const startWork = /^\s*Начать работу\s*$/;
		cy.login(fixture.russian_actor, fixture.password);
		cy.visit(`/app/project-deliverable/${fixture.result}`);
		cy.get('.frappe-control[data-fieldname="deliverable_type"] .control-label').should(
			"have.text",
			"Тип результата"
		);
		cy.scrollTo("top", { ensureScrollable: false });
		// The form label can render before Workflow populates the action menu.
		cy.contains(`${workflowMenu} .dropdown-menu a`, startWork)
			.closest(".actions-btn-group")
			.children("button:visible")
			.click({ scrollBehavior: false });
		cy.contains(`${workflowMenu} .dropdown-menu:visible a`, startWork).should("be.visible");
		cy.contains(
			`${workflowMenu} .dropdown-menu:visible a`,
			/^\s*Передать на приёмку\s*$/
		).should("be.visible");
		cy.visit(`/app/project-change-request/${fixture.change}`);
		cy.get('.frappe-control[data-fieldname="change_relations"] .control-label').should(
			"have.text",
			"Связанные объекты изменения"
		);
	});

	it("repaints overview charts when switching theme in the same report", () => {
		openReport(overview, { project: fixture.project });
		const labels = "Requirements by category";
		let lightColor;
		cy.window().then((window) => window.frappe.ui.set_theme("light"));
		chartOption(chart(labels), (option) => {
			lightColor = option.title[0].textStyle.color;
			expect(option.title[0].text).to.eq("3");
		});
		cy.window().then((window) => window.frappe.ui.set_theme("dark"));
		chartOption(chart(labels), (option) => {
			expect(option.title[0].textStyle.color).not.to.eq(lightColor);
			expect(option.title[0].text).to.eq("3");
		});
		reportShown(overview, { project: fixture.project });
	});

	it("moves the plan endpoint without changing recorded progress after a task schedule edit", () => {
		cy.visit(`/app/project-deliverable/${fixture.result}`);
		const series = '[data-fieldname="progress_html"] .dinext-scope-chart--progress';
		let recorded;
		chartOption(cy.get(series), (option) => {
			const [plan, actual] = option.series;
			expect(plan.data).to.deep.include([Date.parse(fixture.planned_end), 100]);
			recorded = actual.data;
			expect(recorded.map(([, value]) => value)).to.deep.eq([60, 20]);
		});
		cy.call("frappe.client.set_value", {
			doctype: "Task",
			name: fixture.work,
			fieldname: "custom_planned_end_date",
			value: fixture.later_planned_end,
		});
		cy.reload();
		chartOption(cy.get(series), (option) => {
			const [plan, actual] = option.series;
			expect(plan.data).to.deep.include([Date.parse(fixture.later_planned_end), 100]);
			expect(actual.data).to.deep.eq(recorded);
		});
	});
});
