import { linkOption } from "../support/link_options";
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

function workCells(label) {
	return cy
		.contains(`${resultHost} .dinext-scope-label`, label)
		.first()
		.closest(".ag-row")
		.invoke("attr", "row-id")
		.then((id) => cy.get(`${resultHost} .ag-center-cols-container [row-id="${id}"]`));
}

describe("Project scope charts", () => {
	const fixture = useReportFixture();

	it("shows the results loader until data arrives and keeps fullscreen through donut filters", () => {
		cy.viewport(1440, 680);
		let release;
		const incoming = new Cypress.Promise((resolve) => {
			release = resolve;
		});
		cy.intercept(
			{
				method: "GET",
				pathname: "/api/method/dinext_project_scope.analytics.data.project_results",
			},
			() => incoming
		).as("loadResults");
		showResults(fixture.project);
		const spinner = `${resultHost} .dinext-scope-results-spinner`;
		cy.get(spinner)
			.should("be.visible")
			.and("have.css", "animation-name", "dinext-scope-results-spin");
		cy.then(() => release());
		cy.wait("@loadResults");
		cy.get(spinner).should("not.exist");

		// Cypress clicks do not grant the transient activation required by the Fullscreen API.
		cy.window().then((view) => {
			const { document } = view;
			let fullscreenElement = null;
			Object.defineProperty(document, "fullscreenElement", {
				configurable: true,
				get: () => fullscreenElement,
			});
			cy.stub(view.Element.prototype, "requestFullscreen").callsFake(function () {
				fullscreenElement = this;
				document.dispatchEvent(new view.Event("fullscreenchange"));
				return Promise.resolve();
			});
			cy.stub(document, "exitFullscreen").callsFake(() => {
				fullscreenElement = null;
				document.dispatchEvent(new view.Event("fullscreenchange"));
				return Promise.resolve();
			});
		});
		cy.get(`${resultHost} button[title="Fullscreen"]`).click();
		let fullscreenTable;
		const grid = `${resultHost} .dinext-table--fullscreen`;
		cy.get(grid).then(([$element]) => {
			fullscreenTable = $element;
		});
		cy.get(`${resultHost} .dinext-scope-results`).should(([shell]) => {
			const viewport = shell.querySelector(".ag-body-viewport");
			expect(shell.ownerDocument.defaultView.getComputedStyle(shell).overflowY).to.eq(
				"hidden"
			);
			expect(shell.scrollHeight).to.be.at.most(shell.clientHeight + 1);
			expect(viewport.clientHeight).to.be.greaterThan(0);
			expect(viewport.getBoundingClientRect().bottom).to.be.at.most(
				shell.getBoundingClientRect().bottom
			);
		});
		clickPieSegment("Deliverables by category", `${fixture.title} secondary`);
		resultFilter("Deliverables by category", "category").should(
			"have.value",
			`${fixture.title} secondary`
		);
		rowLink(`${fixture.title} shared component`).should("exist");
		cy.get(grid).should(([$element]) => expect($element).to.eq(fullscreenTable));
		resultFilter("Deliverables by type", "deliverable_type").select(fixture.title);
		cy.contains(`${resultHost} [role="status"]`, "No records match the filters.").should(
			"be.visible"
		);
		cy.get(grid).should(([$element]) => expect($element).to.eq(fullscreenTable));
	});

	it("compares deliverable progress on selected dates and exports the same tree", () => {
		cy.viewport(1700, 900);
		showResults(fixture.project);
		const control = (field) =>
			`${resultHost} .dinext-scope-progress-controls input[data-fieldname="${field}"]`;
		const header = (field) => `${resultHost} .ag-header-cell[col-id="${field}"]`;
		const cell = (field) => resultCells(`${fixture.title} peer`).find(`[col-id="${field}"]`);
		function setDate(field, date) {
			cy.window().then((win) => {
				cy.get(control(field))
					.invoke("val", date ? win.frappe.datetime.str_to_user(date) : "")
					.trigger("change");
			});
		}

		cy.get(control("show_plan")).should("not.be.checked");
		cy.get(control("baseline_date")).should("have.value", "");
		cy.window().then((win) => {
			const today = win.frappe.datetime.get_today();
			cy.get(control("reporting_date")).should(
				"have.value",
				win.frappe.datetime.str_to_user(today)
			);
		});
		cy.get(header("planned_progress")).should("not.exist");
		cy.get(header("baseline_progress")).should("not.exist");
		setDate("reporting_date", fixture.reporting_date);
		cell("progress").find('[role="progressbar"]').should("have.attr", "aria-valuenow", "54");
		setDate("baseline_date", fixture.baseline_date);
		cell("baseline_progress")
			.find('[role="progressbar"]')
			.should("have.attr", "aria-valuenow", "20");
		cell("baseline_delta").find('[data-direction="up"]').should("contain.text", "↑ 34");
		cy.get(control("show_plan")).check();
		cy.get(header("planned_progress")).should("exist");
		cy.get(`${resultHost} .ag-body-horizontal-scroll-viewport`).scrollTo(550, 0, {
			ensureScrollable: false,
		});
		cell("planned_progress")
			.find('[role="progressbar"]')
			.should("have.attr", "aria-valuenow", "50");
		cell("plan_delta").find('[data-direction="up"]').should("contain.text", "↑ 4");

		cy.intercept(
			"GET",
			"**/api/method/dinext_project_scope.analytics.export.download_project_results?*"
		).as("resultsExcel");
		cy.get(`${resultHost} button[title="Export XLSX"]`).click();
		cy.wait("@resultsExcel").then(({ request, response }) => {
			expect(request.query).to.include({
				project: fixture.project,
				reporting_date: fixture.reporting_date,
				baseline_date: fixture.baseline_date,
				show_plan: "1",
			});
			expect(response.statusCode).to.eq(200);
			expect(response.headers["content-disposition"]).to.contain("project-results.xlsx");
		});
		cy.readFile(`${Cypress.config("downloadsFolder")}/project-results.xlsx`, null).should(
			(file) => expect(file.slice(0, 2).toString()).to.eq("PK")
		);
		cy.get(control("show_plan")).uncheck();
		cy.get(header("planned_progress")).should("not.exist");
		setDate("baseline_date", "");
		cy.get(header("baseline_progress")).should("not.exist");
	});

	it("shows the Task type and omits empty optional work in the expanded results tree", () => {
		showResults(fixture.project);
		cy.get(
			`${resultHost} .ag-header-cell[col-id="deliverable_type"] .ag-header-cell-text`
		).should("have.text", "Type");
		rowLink(`${fixture.title} shared component`)
			.first()
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		workCells(`${fixture.title} work group`)
			.find('[col-id="deliverable_type"]')
			.should("have.text", fixture.title)
			.and(([cell]) => {
				const label = cell.ownerDocument.createRange();
				label.selectNodeContents(cell.querySelector("span"));
				expect(label.getBoundingClientRect().width).to.be.lessThan(cell.clientWidth);
				expect(cell.getBoundingClientRect().width).to.be.greaterThan(135);
			});
		cy.contains(`${resultHost} .dinext-scope-label`, "Contact reference").should("not.exist");
	});

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
			cy.get('[col-id="assignment"] .avatar[role="img"]')
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
			.find('[col-id="assignment"] .avatar .standard-image')
			.should("have.text", "C");
		resultCells(`${fixture.title} shared component`)
			.find('[col-id="deliverable_type"] svg')
			.should("be.visible");
		resultCells(`${fixture.title} peer`)
			.find('[col-id="assignment"] .avatar')
			.should("have.length", 1)
			.and("have.attr", "title", fixture.title);
	});

	it("ships a distinct visible icon for each standard deliverable type", () => {
		for (const [name, file] of [
			["Документ", "document"],
			["Работа", "work"],
			["Разработка", "development"],
			["Тестирование", "testing"],
			["Миграция данных", "data-migration"],
		]) {
			const icon = `/assets/dinext_project_scope/icons/deliverable-types/${file}.svg`;
			cy.visit(`/app/project-deliverable-type/${encodeURIComponent(name)}`);
			cy.window().should(({ cur_frm }) => {
				expect(cur_frm.doc.name).to.eq(name);
				expect(cur_frm.doc.icon).to.eq(icon);
			});
			cy.request(icon).its("headers.content-type").should("include", "image/svg+xml");
		}
	});

	context("configured result tree responsibilities", () => {
		const url = "/app/project-scope-settings";
		const field = "result_tree_responsibilities";
		const control = `.page-container:visible [data-fieldname="${field}"]`;
		let original;

		function openSettings() {
			cy.openDesk(url);
			cy.window().its("cur_frm.doc.doctype").should("eq", "Project Scope Settings");
		}

		function saveSettings() {
			cy.window().then(({ cur_frm }) => cur_frm.save());
		}

		afterEach(() => {
			if (!original) return;
			cy.login();
			openSettings();
			cy.window().then(({ cur_frm }) => {
				cur_frm.clear_table(field);
				for (const responsibility of original)
					cur_frm.add_child(field, { responsibility });
				cur_frm.dirty();
			});
			saveSettings();
		});

		it("combines selected responsibilities in Assignment and keeps work assignees when the list is empty", () => {
			openSettings();
			cy.window().then(({ cur_frm }) => {
				original = cur_frm.doc[field].map(({ responsibility }) => responsibility);
				expect(original).to.deep.eq(["О"]);
			});
			cy.get(`${control} .tb-selected-value .btn-remove`).click();
			for (const [value, query] of [
				[`${fixture.title} secondary`, `${fixture.title} review`],
				[fixture.title, `${fixture.title} contribut`],
			]) {
				cy.get(`${control} input:visible`).type(query);
				linkOption(control, value).click();
			}
			saveSettings();

			showResults(fixture.project);
			cy.get(
				`${resultHost} .ag-header-cell[col-id="assignment"] .ag-header-cell-text`
			).should("have.text", "Assignment");
			resultCells(`${fixture.title} result`)
				.find('[col-id="assignment"] .avatar')
				.should("have.length", 2);
			resultCells(`${fixture.title} shared component`)
				.find('[col-id="assignment"]')
				.should("have.text", "—");
			openSettings();
			cy.get(`${control} .tb-selected-value .btn-remove`).first().click();
			cy.get(`${control} .tb-selected-value .btn-remove`).first().click();
			saveSettings();

			showResults(fixture.project);
			resultCells(`${fixture.title} result`)
				.find('[col-id="assignment"]')
				.should("have.text", "—");
			rowLink(`${fixture.title} shared component`)
				.first()
				.closest(".ag-cell")
				.find(".dinext-table-tree-toggle")
				.click();
			workCells(`${fixture.title} work group`)
				.find('[col-id="assignment"] .avatar')
				.should("have.length", 1);
		});
	});

	it("links an Other document without counting its dates or progress and shows its assignment", () => {
		cy.visit(
			`/app/project-deliverable-type/${encodeURIComponent(`${fixture.title} secondary`)}`
		);
		cy.get('[data-fieldname="elements"] .grid-row[data-idx="2"] .btn-open-row').click();
		const kind = '.grid-row-open .form-in-grid [data-fieldname="element_type"] select';
		cy.get(kind).should("have.value", "Other");
		const filter =
			'.grid-row-open .form-in-grid [data-fieldname="filter_type"].frappe-control';
		cy.get(`${filter} input:visible`).should("have.value", "Contact");
		cy.window().its("cur_frm.doc.elements.1.filter_doctype").should("eq", "DocType");

		cy.visit(`/app/project-deliverable/${fixture.shared}`);
		let schedule;
		cy.window()
			.should(({ cur_frm }) => {
				expect(cur_frm.doc.name).to.eq(fixture.shared);
				expect(cur_frm.doc.table_xuct[1].element_doctype).to.eq("Contact");
			})
			.then(({ cur_frm }) => {
				schedule = [
					cur_frm.doc.progress,
					cur_frm.doc.planned_end_date,
					cur_frm.doc.expected_end_date,
				];
			});
		cy.get('[data-fieldname="table_xuct"] .grid-row[data-idx="2"] .btn-open-row').click();
		const field = '.grid-row-open .form-in-grid [data-fieldname="element"].frappe-control';
		cy.get(`${field} input:visible`).type(fixture.title.slice(0, -1));
		linkOption(field, fixture.contact).click();
		cy.window().its("cur_frm.doc.table_xuct.1.element").should("eq", fixture.contact);
		cy.get(".grid-row-open .grid-collapse-row").click();
		cy.window().then(({ cur_frm }) => cur_frm.save());
		cy.window().should(({ cur_frm }) => {
			expect(cur_frm.doc.table_xuct[1].element).to.eq(fixture.contact);
			expect([
				cur_frm.doc.progress,
				cur_frm.doc.planned_end_date,
				cur_frm.doc.expected_end_date,
			]).to.deep.eq(schedule);
		});

		showResults(fixture.project);
		rowLink(`${fixture.title} shared component`)
			.first()
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		workCells("Contact reference")
			.find('[col-id="assignment"] .avatar')
			.should("have.attr", "title", fixture.title);
		workCells("Contact reference")
			.find('[col-id="deliverable_type"]')
			.should("have.text", "Contact");
	});

	it("opens the current project's responsibility matrix from the results toolbar", () => {
		cy.login(fixture.actor, fixture.password);
		showResults(fixture.project);
		resultFilter("Deliverables by type", "deliverable_type").select(fixture.title);
		resultFilter("Deliverables by category", "category").select(`${fixture.title} secondary`);
		cy.contains(`${resultHost} [role="status"]`, "No records match the filters.").should(
			"be.visible"
		);
		const matrix = `${resultHost} .dinext-table-toolbar button[title="Responsibility Matrix"]`;
		cy.get(matrix)
			.should("be.visible")
			.should(([button]) =>
				expect(button.textContent.trim()).to.eq("Responsibility Matrix")
			);
		for (const theme of ["dark", "light"]) {
			cy.window().then(({ frappe }) => frappe.ui.set_theme(theme));
			cy.get(matrix)
				.find("svg use")
				.should(([icon]) => {
					const symbol = icon.ownerDocument.getElementById(
						icon.getAttribute("href").slice(1)
					);
					expect(symbol.id).to.eq("icon-dashboard-list");
					expect(symbol.querySelector("path").getAttribute("stroke")).to.eq(
						"var(--icon-stroke)"
					);
					expect(
						icon.ownerDocument.defaultView
							.getComputedStyle(icon)
							.getPropertyValue("--icon-stroke")
							.trim()
					).not.to.eq("");
				});
		}
		cy.get(matrix).click();
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
		cy.get(`${table} .dinext-scope-link:not(button)`).should(($links) => {
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
		cy.location("pathname").should("eq", `/app/project/${fixture.project}`);
		rowLink(child).first().dblclick();
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
		const clear = `${resultHost} .dinext-table-toolbar button[title="Clear filters"]`;
		cy.get(clear)
			.should(([button]) => expect(button.textContent.trim()).to.eq(""))
			.find("svg use")
			.should("have.attr", "href", "#icon-filter-x");
		cy.get(clear).click();
		for (const [title, fieldname] of filters) {
			resultFilter(title, fieldname).should("have.value", "");
		}
		chartOption(chart("Deliverables by status"), (option) => {
			expect(option.series[0].data).to.deep.eq([{ name: "Not Started", value: 3 }]);
		});
	});

	it("toggles result status, type and category filters from their cells", () => {
		showResults(fixture.project);
		for (const [field, label, value] of [
			["status", "Deliverables by status", "Not Started"],
			["deliverable_type", "Deliverables by type", fixture.title],
			["category", "Deliverables by category", fixture.title],
		]) {
			const cell = () => resultCells(`${fixture.title} result`).find(`[col-id="${field}"]`);
			cell().click();
			resultFilter(label, field).should("have.value", value);
			cy.location("pathname").should("eq", `/app/project/${fixture.project}`);
			cell().click();
			resultFilter(label, field).should("have.value", "");
		}
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

	it("opens a task only by double-click in the results tree", () => {
		showResults(fixture.project);
		const result = `${resultHost} ${table}`;
		const projectPath = `/app/project/${fixture.project}`;
		rowLink(`${fixture.title} shared component`)
			.first()
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		cy.contains(`${result} .dinext-scope-label`, `${fixture.title} work group`)
			.first()
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		cy.location("pathname").should("eq", projectPath);
		const taskLabel = () =>
			cy.contains(`${result} .dinext-scope-label`, `${fixture.title} detail task`).first();
		taskLabel().should("not.have.descendants", "a").click();
		cy.location("pathname").should("eq", projectPath);
		taskLabel().closest(".ag-cell").trigger("keydown", { key: "Enter" });
		cy.location("pathname").should("eq", projectPath);
		taskLabel().dblclick();
		cy.location("pathname").should("eq", `/app/task/${fixture.task}`);
	});

	it("shows the progress chart first and uses project titles for saved links", () => {
		cy.visit(`/app/project-deliverable/${fixture.result}`);
		cy.contains('[data-fieldname="progress_html"]', "Planned and recorded progress")
			.should("be.visible")
			.should(($heading) => {
				const form = $heading[0].closest(".form-layout");
				const title = form.querySelector('.frappe-control[data-fieldname="title"]');
				expect(
					$heading[0].compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING
				).to.be.greaterThan(0);
			});
		for (const [field, id, title] of [
			["deliverable_scopes", fixture.scope, `${fixture.title} warehouse operations`],
			["deliverable_constraints", fixture.assumption, `${fixture.title} assumption`],
		]) {
			cy.get(`[data-fieldname="${field}"] .tb-selected-value[data-value="${id}"]`)
				.find(".btn-link-to-form")
				.should("have.text", title);
		}
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

	it("keeps the progress legend below date labels when resizing and switching theme", () => {
		cy.visit(`/app/project-deliverable/${fixture.result}`);
		const host = '[data-fieldname="progress_html"] .dinext-scope-chart--progress';
		const bounds = (item) => {
			const rect = item.getBoundingRect().clone();
			const transform = item.getComputedTransform();
			if (transform) rect.applyTransform(transform);
			return rect;
		};
		for (const [width, theme] of [
			[1440, "dark"],
			[800, "dark"],
			[800, "light"],
		]) {
			cy.viewport(width, 960);
			cy.window().then(({ frappe }) => frappe.ui.set_theme(theme));
			cy.get("html").should("have.attr", "data-theme", theme);
			chartOption(cy.get(host), (_option, instance) => {
				expect(instance.getWidth()).to.eq(instance.getDom().clientWidth);
				const model = instance.getModel();
				const group = (name) =>
					instance.getViewOfComponentModel(model.getComponent(name)).group;
				const labelBottoms = [];
				group("xAxis").traverse((item) => {
					if (item.type !== "text" || item.ignore) return;
					const rect = bounds(item);
					labelBottoms.push(rect.y + rect.height);
				});
				expect(labelBottoms, "rendered date labels").not.to.be.empty;
				const legend = bounds(group("legend"));
				expect(
					legend.y - Math.max(...labelBottoms),
					"gap above the legend"
				).to.be.at.least(4);
				expect(legend.y + legend.height, "legend bottom").to.be.at.most(
					instance.getHeight()
				);
			});
		}
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
		cy.get('.form-graph [data-pwa-bar="deliverables"] [role="progressbar"]').should(
			"have.attr",
			"aria-description",
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

	it("creates in the current project and deletes a result selected in the first column", () => {
		showResults(fixture.project);
		const toolbar = `${resultHost} .dinext-table-toolbar`;
		const addButton = `${toolbar} button[title="Add Project Deliverable"]`;
		const deleteButton = `${toolbar} button[title="Delete selected results"]`;
		const title = `${fixture.title} toolbar result`;
		cy.get(deleteButton).should("be.disabled");
		cy.get(addButton).click();
		cy.window().should(({ cur_frm }) => {
			expect(cur_frm?.doctype).to.eq("Project Deliverable");
			expect(cur_frm.is_new()).to.be.ok;
			expect(cur_frm.doc.project).to.eq(fixture.project);
		});
		const page = ".page-container:visible";
		cy.get(`${page} input[data-fieldname="title"]:visible`).type(title);
		for (const fieldname of ["category", "deliverable_type"]) {
			const field = `${page} .frappe-control[data-fieldname="${fieldname}"]`;
			cy.get(field).find("input:visible").type(fixture.title, { delay: 0 });
			linkOption(field, fixture.title).click();
		}
		cy.get(`${page} .page-actions .primary-action:visible`).click();
		cy.window().should(({ cur_frm }) => {
			expect(Boolean(cur_frm.is_new())).to.be.false;
			expect(cur_frm.doc.title).to.eq(title);
		});
		showResults(fixture.project);
		rowLink(title)
			.closest(".ag-row")
			.within(() => {
				cy.get(".ag-cell")
					.first()
					.should("have.attr", "col-id", "__dinext_row_check")
					.find('input[type="checkbox"]')
					.check();
			});
		cy.get(deleteButton).should("be.enabled").click();
		cy.contains(".modal:visible button", "Yes").click();
		cy.contains(`${resultHost} .dinext-scope-label`, title).should("not.exist");
		cy.get(deleteButton).should("be.disabled");
	});
});
