const fixtureApi = "dinext_project_scope.tests.scope_ui_test_helpers";
const runId = Array.from(crypto.getRandomValues(new Uint8Array(8)), (part) =>
	part.toString(16).padStart(2, "0")
).join("");
let fixture;

const session = () => {
	cy.login();
	cy.openDesk("/app/project");
};

function openReport(name, project) {
	cy.visit(
		`/app/query-report/${encodeURIComponent(name)}?project=${encodeURIComponent(project)}`
	);
	cy.get(".page-title:visible").should("contain.text", name);
	cy.window().should((window) => {
		expect(window.frappe?.query_report?.get_filter_value("project")).to.eq(project);
	});
}

function downloadExcel(report) {
	cy.intercept("GET", "**/api/method/dinext_project_scope.analytics.export.download?*").as(
		"workbook"
	);
	cy.get(".page-actions .menu-btn-group:visible .dropdown-toggle").click();
	cy.contains(".dropdown-menu:visible a", "Download Excel").click();
	cy.wait("@workbook").its("response.statusCode").should("eq", 200);
	cy.readFile(`${Cypress.config("downloadsFolder")}/${report}.xlsx`, null, {
		timeout: 30000,
	}).should((workbook) => expect(workbook.slice(0, 2).toString()).to.eq("PK"));
}

describe("Project scope", () => {
	before(() => {
		session();
		cy.call(`${fixtureApi}.create_report_fixture`, { run_id: runId }).then(({ body }) => {
			fixture = body.message;
		});
	});
	beforeEach(() => cy.login());
	after(() => {
		session();
		cy.call(`${fixtureApi}.remove_report_fixture`, { run_id: runId });
	});
	it("shows only one requirements tree inside the project scope form", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('[data-fieldname="custom_объем"]').filter("button").click();
		cy.get('[data-fieldname="project_scopes"] .grid-body').should("be.visible");
		cy.get('[data-fieldname="project_constraints"] .grid-body').should("be.visible");
		cy.get('[data-fieldname="custom_scope_requirements_html"] .scope-table').should(
			"be.visible"
		);
		cy.get('[data-fieldname="custom_scope_requirements_html"] .scope-table tbody tr').should(
			"have.length",
			1
		);
		cy.get("body").should(($body) =>
			expect(
				$body.find(
					'[data-fieldname="custom_project_requirement_specifications"] .grid-body:visible'
				)
			).to.have.length(0)
		);
		cy.screenshot("project-scope-requirements");
	});
	it("shows results with three charts and applies a category filter from the legend", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_результаты"]').click();
		cy.get('[data-fieldname="custom_scope_results_html"]').within(() => {
			cy.get(".dinext-scope-chart-card").should("have.length", 3);
			cy.contains(".dinext-scope-table", `${fixture.title} result`).should("be.visible");
			cy.get(".dinext-scope-chart-card").first().contains("button", fixture.title).click();
			cy.get(".dinext-scope-filter-strip select")
				.first()
				.should("have.value", fixture.title);
		});
		cy.screenshot("project-results-charts");
	});
	it("loads the traceability matrix for the active project", () => {
		openReport("Requirement Traceability Matrix", fixture.project);
		cy.contains(`${fixture.title} working`).should("be.visible");
		cy.screenshot("traceability-matrix");
	});
	it("loads the responsibility matrix in the project context", () => {
		openReport("Project Responsibility Matrix", fixture.project);
		cy.contains(`${fixture.title} result`).should("be.visible");
		cy.screenshot("responsibility-matrix");
		downloadExcel("project_responsibility_matrix");
	});
	it("loads the cross-project change impact matrix", () => {
		openReport("Project Change Impact Matrix", fixture.project);
		cy.contains(`${fixture.title} change`).should("be.visible");
		cy.screenshot("change-impact-matrix");
		downloadExcel("project_change_impact_matrix");
	});
});
