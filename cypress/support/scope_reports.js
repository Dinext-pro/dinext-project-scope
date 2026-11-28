const fixtureApi = "dinext_project_scope.tests.scope_ui_test_helpers";
export const exportMethod = "/api/method/dinext_project_scope.analytics.export.download";
export const table = ".dinext-scope-table:visible";

export function useReportFixture() {
	const fixture = {};
	const runId = Array.from(crypto.getRandomValues(new Uint8Array(8)), (part) =>
		part.toString(16).padStart(2, "0")
	).join("");
	const prepareDesk = () => {
		cy.login();
		cy.openDesk("/app/project");
	};
	before(() => {
		prepareDesk();
		cy.call(`${fixtureApi}.create_report_fixture`, { run_id: runId }).then(({ body }) => {
			Object.assign(fixture, body.message);
		});
	});
	beforeEach(() => cy.login());
	after(() => {
		prepareDesk();
		cy.call(`${fixtureApi}.remove_report_fixture`, { run_id: runId });
	});
	return fixture;
}

export function reportShown(name, filters = {}) {
	cy.get(".page-title:visible").should("contain.text", name);
	cy.window().should((window) => {
		const report = window.frappe?.query_report;
		expect(report?.report_name).to.eq(name);
		for (const [field, value] of Object.entries(filters)) {
			expect(report.get_filter_value(field), field).to.deep.eq(value);
		}
	});
}

export function openReport(name, filters = {}) {
	const query = new URLSearchParams(
		Object.entries(filters).map(([key, value]) => [
			key,
			Array.isArray(value) ? JSON.stringify(value) : value,
		])
	);
	cy.visit(`/app/query-report/${encodeURIComponent(name)}?${query}`);
	reportShown(name, filters);
}

export function rowLink(title) {
	return cy.contains(`${table} .dinext-scope-link:not(button)`, exact(title));
}

export function exact(text) {
	return new RegExp(`^${Cypress._.escapeRegExp(text)}$`);
}

export function downloadExcel(name, expectedFilters) {
	cy.intercept("GET", `**${exportMethod}?*`).as("workbook");
	cy.get(`${table} [data-toolbar-custom-id="scope-export"] button`).click();
	cy.wait("@workbook").then(({ request, response }) => {
		expect(response.statusCode).to.eq(200);
		expect(response.headers["content-disposition"]).to.contain(`${name}.xlsx`);
		expect(JSON.parse(request.query.filters)).to.deep.include(expectedFilters);
	});
	cy.readFile(`${Cypress.config("downloadsFolder")}/${name}.xlsx`, null, {
		timeout: 30000,
	}).should((workbook) => expect(workbook.slice(0, 2).toString()).to.eq("PK"));
}

export function chart(title) {
	return cy.contains(".dinext-scope-chart-card", title).find(".dinext-scope-chart");
}

export function withChartPoint(title, locate, interact) {
	const canvas = () => chart(title).find("canvas").first();
	let point;
	canvas()
		.should(([element]) => {
			element.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
			const page = element.ownerDocument;
			const target = element.closest(".dinext-scope-chart");
			const instance = page.defaultView.echarts?.getInstanceByDom(target);
			expect(instance, "current chart instance").to.exist;
			const [x, y] = locate(instance).map(Math.round);
			const rect = element.getBoundingClientRect();
			expect(
				page.elementFromPoint(rect.left + x, rect.top + y),
				"chart at the pointer"
			).to.eq(element);
			point = [x, y];
		})
		.then(() => interact(canvas(), ...point));
}

export function clickChartPoint(title, locate) {
	withChartPoint(title, locate, (canvas, x, y) => {
		canvas.click(x, y, { scrollBehavior: "center" });
	});
}
