import { rowLink, useReportFixture } from "../support/scope_reports";

const host = '[data-fieldname="custom_scope_results_html"]';
const widget = ".dinext-scope-dynamics";
const toggle = 'button[title="Result dynamics"]';
const seriesApi =
	"**/api/method/dinext_project_scope.analytics.dynamics.project_result_dynamics?*";
const treeApi = "**/api/method/dinext_project_scope.analytics.data.project_results?*";
const emptyValue = "__dinext_scope_no_value__";

function openResults(project) {
	cy.visit("/app/project/" + project);
	cy.get('button[data-fieldname="custom_результаты"]').click();
	cy.get(host).should("be.visible");
}

function chart(group) {
	return cy.get(widget + " [data-dynamics-group=" + group + "] .dinext-scope-dynamics-chart");
}

function withChart(group, assertion) {
	chart(group).should(([element]) => {
		const instance = element.ownerDocument.defaultView.echarts.getInstanceByDom(element);
		expect(instance, "mounted ECharts").to.exist;
		assertion(instance, instance.getOption());
	});
}

function select(group) {
	return cy.get(widget + " .frappe-control[data-fieldname=dynamics_" + group + "] select");
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

	it("loads both charts lazily and keeps their selectors independent under the result filters", () => {
		cy.login(fixture.actor, fixture.password);
		cy.intercept("GET", seriesApi).as("dynamics");
		openResults(fixture.project);
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
		select("category").should("have.value", "");
		select("responsible").should("have.value", "");

		let original;
		withChart("responsible", (instance, option) => {
			original = instance;
			expect(option.yAxis[0]).to.include({ min: 0, max: 100 });
			expect(option.series.find((line) => line.name === "Actual").step).to.eq("end");
		});
		select("category").select(fixture.title + " secondary");
		cy.wait("@dynamics").then(({ response }) => {
			expect(response.body.message.category.count).to.eq(1);
			expect(response.body.message.responsible.selected).to.eq("");
		});
		withChart("responsible", (instance) => expect(instance).to.eq(original));

		select("responsible").select("Contact:" + fixture.contact);
		cy.wait("@dynamics").then(({ response }) => {
			expect(response.body.message.responsible.count).to.eq(1);
			expect(response.body.message.category.selected).to.eq(fixture.title + " secondary");
		});
		rowLink(fixture.title + " result").should("exist");

		cy.get(host + ' .frappe-control[data-fieldname="category"] select').select(fixture.title);
		cy.wait("@dynamics").then(({ request, response }) => {
			expect(JSON.parse(request.query.filters).category).to.eq(fixture.title);
			expect(response.body.message.category.count).to.eq(2);
			expect(response.body.message.responsible.count).to.eq(2);
		});
		select("category").should("have.value", "");
		select("responsible").should("have.value", "");
	});

	it("uses the reporting date and leaves the chart query unchanged for the table comparison controls", () => {
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
		changeDate("reporting_date", fixture.reporting_date);
		cy.wait("@dynamics").then(({ request, response }) => {
			expect(request.query.reporting_date).to.eq(fixture.reporting_date);
			expect(response.body.message.cutoff).to.eq(fixture.reporting_date);
			for (const group of ["category", "responsible"]) {
				const { actual } = response.body.message[group].series;
				expect(actual.at(-1)[0]).to.eq(fixture.reporting_date);
			}
		});
		cy.wait("@tree");
		changeDate("baseline_date", fixture.baseline_date);
		cy.wait("@tree");
		cy.get(host + ' input[data-fieldname="show_plan"]').check();
		cy.wait("@tree");
		cy.get("@dynamics.all").should("have.length", 2);
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
			expect(cards[0].getBoundingClientRect().top).to.eq(
				cards[1].getBoundingClientRect().top
			);
		});
		select("category").select(fixture.title + " secondary");
		cy.wait("@dynamics");
		cy.get(viewport).should("be.visible");
		cy.get(host + " " + toggle).click();
		cy.get(widget).should("not.be.visible");
		cy.get(viewport).should(([element]) =>
			expect(element.clientHeight).to.be.closeTo(closedHeight, 1)
		);
	});
});
