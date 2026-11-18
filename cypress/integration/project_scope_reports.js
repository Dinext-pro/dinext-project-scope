import {
	downloadExcel,
	exact,
	exportMethod,
	openReport,
	reportShown,
	rowLink,
	table,
	useReportFixture,
} from "../support/scope_reports";

const traceability = "Requirement Traceability Matrix";
const responsibility = "Project Responsibility Matrix";
const impact = "Project Change Impact Matrix";
const overview = "Project Scope Overview";
const deliverables = "Project Deliverable Register";
const constraints = "Project Constraint Register";

describe("Project scope reports", () => {
	const fixture = useReportFixture();

	it("shows the unique requirements tree, constraints and requests inside Project Scope", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		cy.get('[data-fieldname="project_scopes"] .grid-body').should("be.visible");
		cy.get('[data-fieldname="project_constraints"] .grid-body').should("be.visible");
		cy.get('[data-fieldname="custom_scope_requirements_html"] .scope-table tbody tr')
			.should("have.length", 3)
			.and("be.visible");
		cy.contains(
			'[data-fieldname="custom_scope_changes_html"]',
			`${fixture.title} change`
		).should("be.visible");
		cy.get('[data-fieldname="custom_project_requirements"] .grid-body:visible').should(
			"not.exist"
		);
		cy.get(
			'[data-fieldname="custom_project_requirement_specifications"] .grid-body:visible'
		).should("not.exist");
		cy.screenshot("project-scope-requirements");
	});

	it("opens the responsibility matrix from the Project Scope Reports menu with its project", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.contains("button", exact("Scope Reports")).click();
		cy.contains(".dropdown-menu a", exact(responsibility)).click();
		reportShown(responsibility, { project: fixture.project });
		rowLink(`${fixture.title} result`).should("be.visible");
	});

	it("shows result readiness and its calculation on Project Details", () => {
		cy.visit(`/app/project/${fixture.project}`);
		const readiness = '[data-fieldname="custom_scope_deliverables_progress_html"]';
		cy.contains(`${readiness} strong`, "20%").should("be.visible");
		cy.get(`${readiness} progress`).should(($meter) => {
			expect($meter).to.have.prop("value", 20);
			expect($meter).to.have.attr(
				"title",
				"Average progress of unique root deliverables with equal weight for each. Cancelled and template deliverables are excluded."
			);
		});
	});

	it("requires an explicit project for traceability and responsibility", () => {
		for (const name of [traceability, responsibility]) {
			openReport(name);
			cy.contains("Please set filters").should("be.visible");
			cy.get(table).should("not.exist");
		}
	});

	it("filters traceability by specification, requirement category and status and preserves its ancestor", () => {
		openReport(traceability, {
			project: fixture.project,
			specification: fixture.ordinary,
			requirement: fixture.working,
			kind: `${fixture.title} secondary`,
			author: fixture.contact,
			responsible: "Administrator",
			priority: "High",
			requirement_importance: "Must Have",
			status: "In Progress",
		});
		rowLink(`${fixture.title} working`)
			.closest(".ag-row")
			.should("have.class", "dinext-scope-context-row");
		rowLink(`${fixture.title} analyzed child`)
			.closest(".ag-row")
			.find(".dinext-scope-state-cell--blue")
			.should("contain.text", "In Progress");
		rowLink(`${fixture.title} unlinked`).should("not.exist");
	});

	it("opens result and task branches independently and marks missing links and overdue results", () => {
		openReport(traceability, { project: fixture.project });
		rowLink(`${fixture.title} unlinked`)
			.closest(".ag-row")
			.find(".dinext-scope-state-cell--red")
			.should("be.visible")
			.and("contain.text", "New")
			.and("contain.text", "No linked deliverables in this project");
		rowLink(`${fixture.title} result`)
			.closest(".ag-row")
			.find(".dinext-scope-state-cell--red")
			.should("contain.text", "20%");
		rowLink(`${fixture.title} analyzed child`)
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		rowLink(`${fixture.title} result`).then(() => {
			cy.get(`${table} a`).should(($links) => {
				expect(
					$links.filter((_, link) => link.textContent === `${fixture.title} result`)
				).to.have.length(2);
			});
		});
		for (const title of ["result", "shared component", "work group"]) {
			rowLink(`${fixture.title} ${title}`)
				.first()
				.closest(".ag-cell")
				.find(".dinext-table-tree-toggle")
				.click();
		}
		rowLink(`${fixture.title} detail task`).should("be.visible");
		cy.screenshot("traceability-matrix");
		rowLink(`${fixture.title} detail task`).click();
		cy.location("pathname").should("eq", `/app/task/${fixture.task}`);
	});

	it("shows RACI roles, same-name participants, multiple colors and results without assignments", () => {
		openReport(responsibility, { project: fixture.project });
		cy.contains(`${table} .ag-header-group-text`, exact(fixture.title)).should("be.visible");
		cy.contains(`${table} .ag-header-group-text`, exact(`${fixture.title} secondary`)).should(
			"be.visible"
		);
		cy.contains(`${table} .ag-header-cell-text`, `Contact · ${fixture.contact}`).should(
			"be.visible"
		);
		cy.contains(`${table} .ag-header-cell-text`, `User · ${fixture.actor}`).should(
			"be.visible"
		);
		rowLink(`${fixture.title} peer`)
			.closest(".ag-row")
			.find(".dinext-scope-badge")
			.should("not.exist");
		rowLink(`${fixture.title} result`)
			.closest(".ag-row")
			.within(() => {
				cy.get(`[title="${fixture.title} contributor"]`)
					.first()
					.should("have.css", "background-color", "rgb(44, 124, 112)");
				cy.get(`[title="${fixture.title} reviewer"]`).should(
					"have.css",
					"background-color",
					"rgb(120, 44, 196)"
				);
			});
		cy.screenshot("responsibility-matrix");
		rowLink(`${fixture.title} result`).click();
		cy.location("pathname").should("eq", `/app/project-deliverable/${fixture.result}`);
	});

	it("applies combined RACI filters to a single assignment and downloads collapsed results", () => {
		const filters = {
			project: fixture.project,
			category: fixture.title,
			deliverable_type: fixture.title,
			project_role: fixture.title,
			responsibility: `${fixture.title} secondary`,
			responsible_type: "User",
			responsible: fixture.actor,
		};
		openReport(responsibility, filters);
		rowLink(`${fixture.title} result`)
			.closest(".ag-row")
			.find(".dinext-scope-badge")
			.should("have.length", 1)
			.and("have.attr", "title", `${fixture.title} reviewer`);
		rowLink(`${fixture.title} peer`).should("not.exist");
		cy.contains(`${table} .dinext-scope-label`, exact(fixture.title))
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		rowLink(`${fixture.title} result`).should("not.exist");
		downloadExcel("project_responsibility_matrix", filters);

		openReport(responsibility, {
			...filters,
			responsible_type: "Contact",
			responsible: fixture.contact,
		});
		cy.contains("Nothing to show").should("be.visible");
		rowLink(`${fixture.title} result`).should("not.exist");
	});

	it("keeps the full impact including historical levels and marks the matching detail", () => {
		const filters = {
			project: fixture.project,
			status: "Draft",
			initiator: fixture.contact,
			from_date: fixture.change_date,
			to_date: fixture.change_date,
			impact_type: fixture.title,
			impact_level: "Weak",
			link_doctype: "Project Deliverable",
			link: fixture.shared,
		};
		openReport(impact, filters);
		rowLink(`${fixture.title} change`).should("be.visible");
		cy.contains(`${table} .ag-header-group-text`, "Impact").should("be.visible");
		cy.contains(`${table} .ag-header-cell-text`, exact(`${fixture.title} secondary`)).should(
			"exist"
		);
		cy.contains(`${table} button.dinext-scope-badge--red`, /Strong.*1 without level/).click();
		cy.get(".modal:visible .dinext-scope-impact-detail").should("have.length", 3);
		cy.contains(".modal:visible .dinext-scope-impact-detail", "2–4 days")
			.should("contain.text", "Matched filters")
			.and("contain.text", "Use the shared component.")
			.find("a")
			.should("have.attr", "href", `/app/project-deliverable/${fixture.shared}`);
		cy.contains(".modal:visible .dinext-scope-impact-detail", "5 days").should(
			"not.contain.text",
			"Matched filters"
		);
		cy.contains(".modal:visible .dinext-scope-impact-detail", "Historical assessment.").should(
			"contain.text",
			"Level not specified"
		);
		cy.get(".modal:visible button.btn-modal-close").click();
		cy.screenshot("change-impact-matrix");
		downloadExcel("project_change_impact_matrix", filters);
	});

	it("excludes an impact request when level and related object match different details", () => {
		openReport(impact, {
			project: fixture.project,
			impact_type: fixture.title,
			impact_level: "Weak",
			link_doctype: "Project Deliverable",
			link: fixture.result,
		});
		cy.contains("Nothing to show").should("be.visible");
		rowLink(`${fixture.title} change`).should("not.exist");
	});

	it("shows unique overview counts and drills down to overdue results", () => {
		openReport(overview, { project: fixture.project });
		for (const [label, count] of [
			["Requirements", "3"],
			["Requirements without deliverables", "1"],
			["Project deliverables", "3"],
			["Overdue deliverables", "3"],
			["Constraints and assumptions due for review", "1"],
			["Change requests", "1"],
		]) {
			cy.contains(`${table} button.dinext-scope-link`, exact(label))
				.closest(".ag-row")
				.find('[col-id="count"]')
				.should("have.text", count);
		}
		cy.contains(`${table} button.dinext-scope-link`, exact("Overdue deliverables")).click();
		reportShown(deliverables, { project: fixture.project, overdue: 1 });
		rowLink(`${fixture.title} result`).should("be.visible");
		rowLink(`${fixture.title} hidden deliverable`).should("not.exist");
		downloadExcel("project_deliverable_register", { project: fixture.project, overdue: 1 });
	});

	it("drills from the overview review metric to the assumption and exports the filtered register", () => {
		openReport(overview, { project: fixture.project });
		cy.contains(
			`${table} button.dinext-scope-link`,
			exact("Constraints and assumptions due for review")
		).click();
		reportShown(constraints, { project: fixture.project, review_due: 1 });
		rowLink(`${fixture.title} assumption`).should("be.visible");
		downloadExcel("project_constraint_register", { project: fixture.project, review_due: 1 });
		rowLink(`${fixture.title} assumption`).click();
		cy.location("pathname").should("eq", `/app/project/${fixture.project}`);
		cy.get('[data-fieldname="project_constraints"] .grid-row-open:visible').should(
			"contain.text",
			`${fixture.title} assumption`
		);
	});

	it("keeps the active matrix usable when switching reports and theme in the same Desk session", () => {
		openReport(traceability, { project: fixture.project });
		rowLink(`${fixture.title} working`).should("be.visible");
		cy.window().then((window) => {
			window.frappe.route_options = { project: fixture.project };
			return window.frappe.set_route("query-report", responsibility);
		});
		reportShown(responsibility, { project: fixture.project });
		rowLink(`${fixture.title} result`).should("be.visible");
		cy.window().then((window) => {
			window.document.documentElement.setAttribute("data-theme-mode", "dark");
			window.frappe.ui.set_theme();
		});
		cy.get("html").should("have.attr", "data-theme", "dark");
		cy.get(`${table} .ag-header-group-text`).should("have.length", 2);
		rowLink(`${fixture.title} working`).should("not.exist");
		cy.get(`${table} button[title="Fullscreen"]`).click();
		cy.document().its("fullscreenElement").should("have.class", "dinext-scope-report-page");
		cy.get(`${table} button[title="Exit fullscreen"]`).click();
		cy.document().its("fullscreenElement").should("eq", null);
	});

	it("updates matrix rows and role columns when the project changes", () => {
		openReport(responsibility, { project: fixture.project });
		rowLink(`${fixture.title} result`).should("be.visible");
		cy.get(`${table} .ag-header-group-text`).should("have.length", 2);
		cy.window().then((window) => {
			return window.frappe.query_report.set_filter_value("project", fixture.hidden_project);
		});
		reportShown(responsibility, { project: fixture.hidden_project });
		rowLink(`${fixture.title} hidden deliverable`).should("be.visible");
		rowLink(`${fixture.title} result`).should("not.exist");
		cy.get(`${table} .ag-header-group-text`).should("not.exist");
	});

	it("limits cross-project impact rows, historical columns and XLSX to a Projects User's access", () => {
		cy.login(fixture.actor, fixture.password);
		openReport(impact);
		rowLink(`${fixture.title} change`).should("be.visible");
		rowLink(`${fixture.title} hidden change`).should("not.exist");
		cy.contains(`${table} .ag-header-cell-text`, exact(`${fixture.title} hidden`)).should(
			"not.exist"
		);
		cy.contains(`${table} .ag-header-cell-text`, exact(`${fixture.title} secondary`)).should(
			"exist"
		);
		cy.contains(`${table} button`, "Download Excel").should("be.visible");
		cy.request({
			url: exportMethod,
			qs: {
				report_name: impact,
				filters: JSON.stringify({ project: fixture.hidden_project }),
			},
			failOnStatusCode: false,
		})
			.its("status")
			.should("eq", 403);
	});
});
