const fixtureApi = "dinext_project_scope.tests.requirement_ui_test_helpers";

describe("Requirement specification composition", () => {
	const runId = Array.from(crypto.getRandomValues(new Uint8Array(8)), (part) =>
		part.toString(16).padStart(2, "0")
	).join("");
	let fixture;

	const prepareSession = () => {
		cy.login();
		cy.visit("/app/project");
		cy.window().its("frappe.csrf_token").should("be.a", "string");
	};

	before(() => {
		prepareSession();
		cy.call(`${fixtureApi}.create_fixture`, { run_id: runId }).then((response) => {
			fixture = response.body.message;
		});
	});

	beforeEach(() => cy.login());

	after(() => {
		prepareSession();
		cy.call(`${fixtureApi}.remove_fixture`, { run_id: runId });
	});

	it("shows one template requirement under its parent and reveals all included paths", () => {
		cy.visit(`/app/project-requirement-specification-template/${fixture.template}`);
		cy.get(".requirement-form-table tbody tr").should("have.length", 2);
		cy.get(`.requirement-form-table tbody tr a[href$="/${fixture.parent}"]`).should(
			"have.length",
			1
		);
		cy.get(`.requirement-form-table tbody tr a[href$="/${fixture.child}"]`)
			.should("have.length", 1)
			.closest("tr")
			.within(() => {
				cy.get(".requirement-form-tree-label").should(
					"have.attr",
					"style",
					"--requirement-depth: 1;"
				);
				cy.get("summary").click();
				cy.get("details li").should("have.length", 3);
				cy.get(`details a[href$="/${fixture.branch}"]`).should("have.length", 1);
				cy.get(`details a[href$="/${fixture.leaf}"]`).should("have.length", 2);
			});
		cy.screenshot("specification-template-composition");
	});

	it("keeps a nested empty specification accessible from composition management", () => {
		cy.viewport(700, 820);
		cy.visit(`/app/project-requirement-specification/${fixture.ordinary}`);
		cy.get(".requirement-form-table tbody tr").should("have.length", 1);
		cy.get(`.requirement-form-table tbody a[href$="/${fixture.working}"]`).should(
			"be.visible"
		);
		cy.document().then((document) =>
			document.documentElement.setAttribute("data-theme", "dark")
		);
		cy.get('[data-action="manage-composition"]').click();
		cy.get(".modal:visible").within(() => {
			cy.get(`a[href$="/${fixture.empty}"]`).should("be.visible");
			cy.get('[data-fieldname="target_type"] select').select(
				"Project Requirement Specification"
			);
			cy.get('[data-fieldname="target"] input').should("be.visible");
		});
		cy.screenshot("specification-narrow-dark", { capture: "viewport" });
	});
});
