import { rowLink, useReportFixture } from "../support/scope_reports";

const host = '[data-fieldname="custom_scope_results_html"]';
const widget = ".dinext-scope-dynamics";
const toggle = 'button[title="Result dynamics"]';
const seriesApi =
	"**/api/method/dinext_project_scope.analytics.dynamics.project_result_dynamics?*";
const treeApi = "**/api/method/dinext_project_scope.analytics.data.project_results?*";

function openResults(project) {
	cy.visit("/app/project/" + project);
	cy.get('button[data-fieldname="custom_результаты"]').click();
	cy.get(host).should("be.visible");
}

function chart(group) {
	return cy.get(widget + " [data-dynamics-group=" + group + "] .dinext-scope-dynamics-chart");
}

function withChart(group, assertion) {
	return chart(group).should(([element]) => {
		const instance = element.ownerDocument.defaultView.echarts.getInstanceByDom(element);
		expect(instance, "mounted ECharts").to.exist;
		assertion(instance, instance.getOption());
	});
}

function clickTreemapTile(value) {
	withChart("responsible", (_instance, option) => {
		expect(option.series[0].type).to.eq("treemap");
	}).then(([element]) => {
		const instance = element.ownerDocument.defaultView.echarts.getInstanceByDom(element);
		const series = instance.getModel().getSeriesByIndex(0);
		const tile = series.getData().tree.root.children.find((item) => item.getId() === value);
		expect(tile, "treemap tile").to.exist;
		const { x, y, width, height } = tile.getLayout();
		const offset = series.layoutInfo;
		const canvas = element.querySelector("canvas");
		canvas.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
		cy.wrap(canvas).click(
			Math.round(offset.x + x + width / 2),
			Math.round(offset.y + y + height / 2),
			{
				scrollBehavior: false,
			}
		);
	});
}

function simulateFullscreen() {
	// A scripted Cypress click cannot grant browser activation for requestFullscreen.
	cy.window().then((view) => {
		const { document } = view;
		let element = null;
		Object.defineProperty(document, "fullscreenElement", {
			configurable: true,
			get: () => element,
		});
		cy.stub(view.Element.prototype, "requestFullscreen").callsFake(function () {
			element = this;
			document.dispatchEvent(new view.Event("fullscreenchange"));
			return Promise.resolve();
		});
		cy.stub(document, "exitFullscreen").callsFake(() => {
			element = null;
			document.dispatchEvent(new view.Event("fullscreenchange"));
			return Promise.resolve();
		});
	});
}

describe("Project result dynamics", () => {
	const fixture = useReportFixture();

	it("filters the other charts and results from a highlighted treemap tile", () => {
		cy.login(fixture.actor, fixture.password);
		cy.intercept("GET", seriesApi).as("dynamics");
		cy.intercept("GET", treeApi).as("tree");
		openResults(fixture.project);
		cy.wait("@tree");
		rowLink(fixture.title + " result").should("exist");
		cy.get(widget).should("not.be.visible");
		cy.get("@dynamics.all").should("have.length", 0);
		cy.get(host + " " + toggle)
			.should("have.attr", "aria-pressed", "false")
			.next()
			.should("contain.text", "RACI");

		cy.get(host + " " + toggle).click();
		cy.wait("@dynamics").its("response.body.message.category.count").should("eq", 2);
		cy.get(host + " " + toggle).should("have.attr", "aria-pressed", "true");
		cy.get(widget).find("select").should("not.exist");
		cy.get(widget + ' [data-dynamics-group="category"] .dinext-scope-heading').should(
			"have.text",
			"Result dynamics"
		);
		const member = "Contact:" + fixture.contact;
		withChart("responsible", (_instance, option) => {
			const series = option.series[0];
			expect(series.type).to.eq("treemap");
			expect(series.data.map(({ id, value }) => [id, value])).to.deep.include([member, 1]);
		});

		clickTreemapTile(member);
		cy.wait("@dynamics").then(({ response }) => {
			expect(response.body.message.category.count).to.eq(1);
			expect(response.body.message.responsible.selected).to.eq(member);
			expect(response.body.message.responsible.items).to.have.length(2);
		});
		cy.wait("@tree").then(({ request, response }) => {
			expect(JSON.parse(request.query.filters).responsible).to.eq(member);
			for (const key of ["category", "deliverable_type", "status"]) {
				expect(response.body.message.counts[key].map(({ count }) => count)).to.deep.eq([
					1,
				]);
			}
		});
		withChart("responsible", (_instance, option) => {
			const tile = option.series[0].data.find(({ id }) => id === member);
			expect(tile.itemStyle.borderWidth).to.be.greaterThan(
				option.series[0].itemStyle.borderWidth
			);
		});
		rowLink(fixture.title + " shared component").should("exist");
		clickTreemapTile(member);
		cy.wait("@dynamics").its("response.body.message.responsible.selected").should("eq", "");
		cy.wait("@tree").its("response.body.message.counts.category").should("have.length", 2);
		clickTreemapTile(member);
		cy.wait("@dynamics")
			.its("response.body.message.responsible.selected")
			.should("eq", member);
		cy.wait("@tree");
		cy.get(host + ' button[title="Clear filters"]').click();
		cy.wait("@dynamics").its("response.body.message.responsible.selected").should("eq", "");
		cy.wait("@tree");
		cy.get(host + ' .dinext-scope-charts select[data-fieldname="category"]').select(
			fixture.title + " secondary"
		);
		cy.wait("@dynamics")
			.its("response.body.message")
			.should((data) => {
				expect(data.category.count).to.eq(1);
				expect(data.responsible.items.map(({ value }) => value)).to.deep.eq([member]);
			});
	});

	it("fills actual progress and marks both dates on the category chart", () => {
		cy.intercept("GET", seriesApi).as("dynamics");
		cy.intercept("GET", treeApi).as("tree");
		openResults(fixture.project);
		cy.wait("@tree");
		cy.get(host + " " + toggle).click();
		cy.wait("@dynamics");
		const changeDate = (field, date) => {
			cy.window().then(({ frappe }) =>
				cy
					.get(host + " input[data-fieldname=" + field + "]")
					.invoke("val", frappe.datetime.str_to_user(date))
					.trigger("change")
			);
		};
		withChart("category", (_instance, option) => {
			const actual = option.series.find(({ name }) => name === "Actual");
			expect(actual.step).to.eq("end");
			expect(actual.areaStyle.opacity).to.be.within(0.01, 0.99);
			expect(actual.markLine.data).to.have.length(1);
		});
		changeDate("reporting_date", fixture.reporting_date);
		cy.wait("@dynamics").then(({ request, response }) => {
			expect(request.query.reporting_date).to.eq(fixture.reporting_date);
			expect(response.body.message.cutoff).to.eq(fixture.reporting_date);
			expect(response.body.message.category.series.actual.at(-1)[0]).to.eq(
				fixture.reporting_date
			);
		});
		cy.wait("@tree");
		changeDate("baseline_date", fixture.baseline_date);
		cy.wait("@dynamics")
			.its("request.query.baseline_date")
			.should("eq", fixture.baseline_date);
		withChart("category", (_instance, option) => {
			expect(
				option.series
					.find(({ name }) => name === "Actual")
					.markLine.data.map(({ name, xAxis }) => [name, xAxis])
			).to.deep.eq([
				["Reporting date", Date.parse(fixture.reporting_date)],
				["Baseline date", Date.parse(fixture.baseline_date)],
			]);
		});
		cy.wait("@tree");
		cy.get(host + ' input[data-fieldname="show_plan"]').check();
		cy.wait("@tree");
		cy.get("@dynamics.all").should("have.length", 3);
	});

	it("downloads a PNG from each ECharts toolbox", () => {
		openResults(fixture.project);
		cy.get(host + " " + toggle).click();
		for (const group of ["category", "responsible"]) {
			withChart(group, (_instance, option) =>
				expect(option.toolbox[0].feature.saveAsImage.type).to.eq("png")
			);
			chart(group).then(([element]) => {
				element.scrollIntoView({ block: "center", inline: "nearest" });
				const instance =
					element.ownerDocument.defaultView.echarts.getInstanceByDom(element);
				const model = instance.getModel().getComponent("toolbox");
				const icons = instance.getViewOfComponentModel(model).group;
				const bounds = icons.getBoundingRect();
				const [x, y] = icons.transformCoordToGlobal(
					bounds.x + bounds.width / 2,
					bounds.y + bounds.height / 2
				);
				cy.wrap(element).find("canvas").first().click(Math.round(x), Math.round(y), {
					scrollBehavior: false,
				});
				const name = instance.getOption().toolbox[0].feature.saveAsImage.name;
				cy.readFile(Cypress.config("downloadsFolder") + "/" + name + ".png", null).should(
					(png) =>
						expect([...png.slice(0, 8)]).to.deep.eq([137, 80, 78, 71, 13, 10, 26, 10])
				);
			});
		}
	});

	it("keeps one row of charts and resizes only the results table in fullscreen", () => {
		cy.viewport(1440, 900);
		cy.intercept("GET", seriesApi).as("dynamics");
		openResults(fixture.project);
		simulateFullscreen();
		cy.get(host + ' button[title="Fullscreen"]').click();
		const viewport = host + " .dinext-table--fullscreen .ag-body-viewport";
		let closedHeight;
		cy.get(viewport)
			.should(([element]) => expect(element.clientHeight).to.be.greaterThan(300))
			.then(([element]) => {
				closedHeight = element.clientHeight;
			});
		cy.get(host + " " + toggle).click();
		cy.wait("@dynamics");
		cy.get(viewport).should(([element]) => {
			expect(element.clientHeight).to.be.within(1, closedHeight - 40);
			const shell = element.closest(".dinext-scope-results");
			expect(shell.scrollHeight).to.be.at.most(shell.clientHeight + 1);
			expect(getComputedStyle(shell).overflowY).to.eq("hidden");
			const cards = [...shell.querySelectorAll(widget + " section")];
			expect(cards).to.have.length(2);
			const [left, right] = cards.map((card) => card.getBoundingClientRect());
			expect(left.top).to.eq(right.top);
			expect(left.width / right.width).to.be.closeTo(2, 0.02);
		});
		clickTreemapTile("Contact:" + fixture.contact);
		cy.wait("@dynamics");
		cy.get(viewport).should("be.visible");
		cy.get(host + " " + toggle).click();
		cy.get(widget).should("not.be.visible");
		cy.get(viewport).should(([element]) =>
			expect(element.clientHeight).to.be.closeTo(closedHeight, 1)
		);
	});

	it("hides the incomplete forecast count under the category chart", () => {
		cy.openDesk("/app/project");
		cy.call("frappe.client.set_value", {
			doctype: "Task",
			name: fixture.work,
			fieldname: "exp_end_date",
			value: fixture.planned_end,
		});
		cy.intercept("GET", seriesApi).as("incompleteForecast");
		openResults(fixture.project);
		cy.get(host + " " + toggle).click();
		cy.wait("@incompleteForecast")
			.its("response.body.message.category.forecast_missing")
			.should("eq", 2);
		withChart("category", (_instance, option) => {
			const actual = option.series.find(({ name }) => name === "Actual");
			expect(actual.data).to.not.be.empty;
		});
		cy.get(widget + ' [data-dynamics-group="category"] [role="status"]').should(
			"not.contain.text",
			"Unfinished results without a valid expected end date"
		);
	});
});
