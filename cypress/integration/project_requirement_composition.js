import { linkOption, linkOptions, optionValue } from "../support/link_options";

const fixtureApi = "dinext_project_scope.tests.requirement_ui_test_helpers";
const fixtureRequest = { timeout: 120000 };
const workflowMenu = ".page-container:visible .actions-btn-group";
const modal = ".modal:visible";
const approvalBadge = ".requirement-form-status";
const projectTree = '[data-fieldname="custom_scope_requirements_html"] .dinext-project-scope';
const projectRows = projectTree + " .ag-center-cols-container .ag-row";
const projectTitles = projectTree + " .ag-pinned-left-cols-container .ag-row";
const compositionRows = ".requirement-form-table tbody";
const templateApply = "/api/method/dinext_project_scope.requirements.apply_specification_template";
const workflowApply = "/api/method/frappe.model.workflow.apply_workflow";
const ordinaryForm = (name) => `/app/project-requirement-specification/${name}`;
const requirementForm = (name) => `/app/project-requirement/${name}`;
const templateForm = (name) => `/app/project-requirement-specification-template/${name}`;

function workflowAction(label, comment) {
	cy.get(`${workflowMenu} > button`).click({ scrollBehavior: "nearest" });
	cy.contains(`${workflowMenu} .dropdown-menu:visible a`, label).click();
	if (comment) {
		cy.get(modal).within(() => {
			cy.get('[data-fieldname="comment"] textarea').type(comment).blur();
			cy.get(".modal-footer .btn-primary").should("not.be.disabled").click();
		});
	}
}

function approvalStatus(status) {
	cy.contains(approvalBadge, `Content approval · ${status}`).should("be.visible");
	cy.get("#freeze").should("not.exist");
	cy.window().should((window) => {
		expect(window.cur_frm.page.wrapper[0].inert).to.eq(false);
	});
}

function changeApprovalInPlace(action, status, comment) {
	cy.intercept("POST", workflowApply).as("applyScopeApproval");
	cy.document().then((page) => {
		workflowAction(action, comment);
		cy.wait("@applyScopeApproval").its("response.statusCode").should("eq", 200);
		approvalStatus(status);
		cy.document().should("eq", page);
	});
}

function openProjectScope(project) {
	cy.visit(`/app/project/${project}`);
	cy.get('button[data-fieldname="custom_объем"]').click();
	cy.get(projectTree).should("be.visible");
}

function projectGrid() {
	return cy
		.get(projectTree + " .ag-root-wrapper[grid-id]")
		.should("exist")
		.then(([grid]) =>
			grid.ownerDocument.defaultView.agGrid.getGridApi(grid.getAttribute("grid-id"))
		);
}

function showProjectSpecifications() {
	projectGrid().then((api) => {
		api.ensureColumnVisible("paths", "end");
	});
}

function moreScopeAction(label) {
	cy.contains(`${projectTree} summary`, "More Actions").click();
	cy.contains(`${projectTree} .scope-actions-menu button:visible`, label).click({
		scrollBehavior: "nearest",
	});
}

function linkSearch(field, text) {
	cy.get(`[data-fieldname="${field}"] input:visible`).clear().type(text, { delay: 0 });
}

function chooseLink(field, search) {
	linkSearch(field, search);
	linkOption(`[data-fieldname="${field}"]`, search).click();
}

function fitsViewport() {
	cy.document().should(({ documentElement }) => {
		expect(documentElement.scrollWidth).to.be.at.most(documentElement.clientWidth + 1);
	});
}

function compositionEditor() {
	cy.get('[data-action="manage-composition"]').click();
	return cy.get(modal).should(([$modal]) => {
		const dialog = $modal.ownerDocument.defaultView.cur_dialog;
		expect(dialog?.$wrapper?.get(0)).to.eq($modal);
	});
}

function approvalHistory() {
	cy.contains(".requirement-form-toolbar button", "Approval history").click();
	return cy.get(modal);
}

function applyTemplate(project, template, prefix, excludedReviewer) {
	cy.intercept("POST", templateApply).as("applySpecificationTemplate");
	openProjectScope(project);
	moreScopeAction("Apply Specification Template");
	cy.get(modal).within(() => {
		chooseLink("item", template);
		cy.contains("button", "Continue").click();
	});
	cy.contains(`${modal} .modal-title`, "Preview Template Application").should("be.visible");
	cy.get(modal).within(() => {
		cy.get(".scope-table tbody tr").should("have.length", 5);
		cy.contains(".scope-table td", `${prefix} template child`).should("be.visible");
		if (excludedReviewer) cy.get("select option").should("not.contain.text", excludedReviewer);
		cy.contains("button", "Apply Template").click();
	});
	return cy
		.wait("@applySpecificationTemplate")
		.its("response")
		.then((response) => {
			expect(response.statusCode).to.eq(200);
			const created = response.body.message;
			expect(Object.keys(created.requirements)).to.have.length(2);
			expect(Object.keys(created.specifications)).to.have.length(3);
			cy.get(modal).should("not.exist");
			cy.get(`${projectRows}[row-id$="${Object.values(created.requirements)[0]}"]`).should(
				"be.visible"
			);
			return cy.wrap(created, { log: false });
		});
}

function rejectedWrite(method, url, body, status, message) {
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((token) =>
			cy
				.request({
					method,
					url,
					body,
					failOnStatusCode: false,
					headers: { "X-Frappe-CSRF-Token": token },
				})
				.then((response) => {
					expect(response.status).to.eq(status);
					expect(JSON.stringify(response.body)).to.contain(message);
				})
		);
}

describe("Requirement specification composition", () => {
	const runId = Array.from(crypto.getRandomValues(new Uint8Array(8)), (part) =>
		part.toString(16).padStart(2, "0")
	).join("");
	let fixture;

	const prepareSession = () => {
		cy.login();
		cy.openDesk("/app/project");
	};
	const signIn = (role) => {
		const { email, password } = fixture.actors[role];
		cy.login(email, password);
	};

	before(() => {
		prepareSession();
		cy.call(`${fixtureApi}.create_fixture`, { run_id: runId }, fixtureRequest).then(
			(response) => {
				fixture = response.body.message;
			}
		);
	});

	beforeEach(() => signIn("author"));

	after(() => {
		prepareSession();
		cy.call(`${fixtureApi}.remove_fixture`, { run_id: runId }, fixtureRequest);
	});

	it("shows one template requirement under its parent and reveals all included paths", () => {
		cy.visit(templateForm(fixture.template));
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

	it("keeps all specification columns and nested empty specifications accessible at 800 px", () => {
		cy.viewport(800, 820);
		cy.visit(ordinaryForm(fixture.ordinary));
		cy.get(".requirement-form-table tbody tr").should("have.length", 2);
		cy.get(".requirement-form-table th").should(($columns) => {
			expect([...$columns].map((column) => column.textContent)).to.deep.equal([
				"Requirement",
				"Status",
				"Content approval",
				"Sources",
			]);
		});
		cy.get(".requirement-form-table").should("have.attr", "tabindex", "0");
		fitsViewport();
		cy.get(`.requirement-form-table tbody a[href$="/${fixture.working}"]`).should(
			"be.visible"
		);
		cy.document().then((document) =>
			document.documentElement.setAttribute("data-theme", "dark")
		);
		cy.get('[data-action="manage-composition"]').click();
		cy.get(modal).within(() => {
			cy.get(`a[href$="/${fixture.empty}"]`).should("be.visible");
			cy.get('[data-fieldname="target_type"] select').select(
				"Project Requirement Specification"
			);
			cy.get('[data-fieldname="target"] input').should("be.visible");
		});
		fitsViewport();
		cy.screenshot("specification-narrow-dark", { capture: "viewport" });
	});

	it("shows the project and valid composition choices in the two specification registries", () => {
		const target = '[data-fieldname="target"]';
		cy.visit("/app/project-requirement-specification");
		cy.get(`a[href$="/${fixture.ordinary}"]`).first().click();
		cy.get('[data-fieldname="project"] a[data-name]').should(
			"have.attr",
			"data-name",
			fixture.project
		);
		compositionEditor().within(() => {
			cy.get('[data-fieldname="target_type"] select option').then(($options) => {
				expect([...$options].map((option) => option.value)).to.deep.equal([
					"Project Requirement",
					"Project Requirement Specification",
				]);
			});
			cy.get('[data-fieldname="target_type"] select').should(
				"have.value",
				"Project Requirement"
			);
			linkSearch("target", fixture.prefix);
			linkOptions(target).should(($options) => {
				const values = [...$options].map(optionValue);
				expect(values).to.include(fixture.working);
				expect(values).not.to.include(fixture.foreign);
				expect(values).not.to.include(fixture.child);
			});
		});
		cy.visit("/app/project-requirement-specification-template");
		cy.get(`a[href$="/${fixture.template}"]`).first().click();
		cy.get('[data-fieldname="project"]').should("not.exist");
		compositionEditor().within(() => {
			cy.get('[data-fieldname="target_type"] select option').then(($options) => {
				expect([...$options].map((option) => option.value)).to.deep.equal([
					"Project Requirement",
					"Project Requirement Specification Template",
				]);
			});
			cy.get('[data-fieldname="target_type"] select').should(
				"have.value",
				"Project Requirement"
			);
			linkSearch("target", fixture.prefix);
			linkOptions(target).should(($options) => {
				const values = [...$options].map(optionValue);
				expect(values).to.include(fixture.child);
				expect(values).not.to.include(fixture.working);
			});
		});
	});

	it("shows one project requirement for direct and nested sources and filters that tree", () => {
		openProjectScope(fixture.project);
		const row = `${projectRows}[row-id$="${fixture.working}"]`;
		const child = `${projectRows}[row-id$="${fixture.nested_child}"]`;
		cy.get(row).should("have.length", 1);
		const titleRow = `${projectTitles}[row-id$="${fixture.working}"]`;
		showProjectSpecifications();
		cy.get(`${row} .scope-source-list button`).should("have.length", 2);
		cy.get(`${row} .scope-requirement-details`).click();
		cy.get(".modal:visible .scope-source-path").should("have.length", 3);
		cy.contains(".modal:visible .scope-source-path", "Included directly").should("be.visible");
		cy.contains(".modal:visible .scope-row-details", "Must Have").should("be.visible");
		cy.get(".modal:visible .btn-modal-close").click();
		cy.get(`${titleRow} .dinext-table-tree-toggle`).click();
		cy.get(child).should("not.exist");
		cy.get(`${titleRow} .dinext-table-tree-toggle`).click();
		cy.get(child).should("be.visible");
		cy.get(row).invoke("attr", "row-id").as("workingRequirementRow");
		chooseLink("scope_specification_filter", fixture.nested);
		cy.get("@workingRequirementRow").then((id) => {
			projectGrid().should((api) => {
				const paths = api.getRowNode(id)?.data?.paths;
				expect(paths, "updated paths for the selected specification").to.have.length(1);
				expect(paths[0]).to.include(fixture.nested);
			});
		});
		showProjectSpecifications();
		cy.get(`${row} .scope-requirement-details`).click();
		cy.contains(".modal:visible .scope-source-path", "Included directly").should("not.exist");
		cy.get(".modal:visible .scope-source-path").should("have.length", 1);
		cy.get(".modal:visible .btn-modal-close").click();
	});

	it("reflects nested composition edits in the project without losing other sources", () => {
		cy.visit(ordinaryForm(fixture.nested));
		compositionEditor().within(() => {
			cy.get(`.requirement-form-editor-row a[href$="/${fixture.nested_child}"]`)
				.closest("li")
				.contains("button", "Remove")
				.click();
			chooseLink("target", fixture.replacement);
			cy.contains("button", "Add link").click();
			cy.contains("button", "Save composition").click();
		});
		cy.get(`${compositionRows} a[href$="/${fixture.replacement}"]`).should("be.visible");
		openProjectScope(fixture.project);
		cy.get(`${projectRows}[row-id$="${fixture.nested_child}"]`).should("not.exist");
		cy.get(`${projectRows}[row-id$="${fixture.replacement}"]`).should("be.visible");
		cy.get(`${projectRows}[row-id$="${fixture.working}"]`).should("have.length", 1);
		cy.visit(requirementForm(fixture.nested_child));
		cy.contains(".requirement-form", "Outside current project scope").should("be.visible");
		cy.get('[data-fieldname="project"] a[data-name]').should(
			"have.attr",
			"data-name",
			fixture.project
		);
	});

	it("connects and disconnects an empty specification through project scope actions", () => {
		openProjectScope(fixture.project);
		moreScopeAction("Connect Specification");
		cy.get(modal).within(() => {
			chooseLink("item", fixture.standalone);
			cy.contains("button", "Continue").click();
		});
		cy.intercept("POST", "**/api/method/frappe.desk.form.save.savedocs").as(
			"updateConnections"
		);
		cy.contains(modal, "with 0 requirements").contains("button", "Yes").click();
		cy.wait("@updateConnections").its("response.statusCode").should("eq", 200);
		openProjectScope(fixture.project);
		moreScopeAction("Manage Requirement Connections");
		cy.contains(`${modal} .scope-connection-row button`, fixture.standalone)
			.should("be.visible")
			.click();
		cy.location("pathname").should("eq", ordinaryForm(fixture.standalone));
		openProjectScope(fixture.project);
		moreScopeAction("Manage Requirement Connections");
		cy.contains(`${modal} .scope-connection-row button`, fixture.standalone)
			.closest(".scope-connection-row")
			.contains("button", "Disconnect")
			.click();
		cy.contains(modal, "Remove this source").contains("button", "Yes").click();
		cy.wait("@updateConnections").its("response.statusCode").should("eq", 200);
		openProjectScope(fixture.project);
		moreScopeAction("Manage Requirement Connections");
		cy.contains(`${modal} .scope-connection-row button`, fixture.standalone).should(
			"not.exist"
		);
	});

	it("keeps project scope actions and table details accessible at 800 px", () => {
		cy.viewport(800, 820);
		openProjectScope(fixture.project);
		projectGrid().then((api) => {
			expect(
				api.getAllGridColumns().map((column) => column.getColDef().headerName)
			).to.deep.eq([
				"Requirement",
				"Status",
				"Priority",
				"Kind",
				"Author",
				"Importance",
				"Responsible",
				"Specifications",
			]);
			expect(api.getColumn("title").getPinned()).to.eq("left");
		});
		const status = `${projectRows} [col-id="status"]`;
		cy.get(status).first().should("have.css", "text-align", "center");
		cy.get(`${status} .indicator-pill`).each(($badge) => {
			cy.window().then(({ frappe }) => {
				const state = frappe
					.get_meta("Project Requirement")
					.states.find(({ title }) => title === $badge.text().trim());
				expect(state, "Document States configuration").to.exist;
				expect($badge).to.have.class(frappe.scrub(state.color, "-"));
			});
		});
		cy.contains(`${projectTree} button`, "Requirement Traceability Matrix").should(
			"be.visible"
		);
		cy.get(`${projectTree} [data-fieldname="scope_specification_filter"] input`).should(
			"be.visible"
		);
		cy.contains(`${projectTree} summary`, "More Actions").click();
		cy.contains(`${projectTree} button`, "Apply Specification Template").should("be.visible");
		cy.contains(`${projectTree} summary`, "More Actions").click();
		showProjectSpecifications();
		cy.get(`${projectTree} .ag-body-horizontal-scroll-viewport`).should(([viewport]) => {
			expect(viewport.scrollLeft).to.be.greaterThan(0);
		});
		cy.get(`${projectTitles}[row-id$="${fixture.working}"]`).should("be.visible");
		cy.get(`${projectRows}[row-id$="${fixture.working}"]`).within(() => {
			cy.get(".scope-requirement-details").then(([button]) => button.focus());
			cy.focused().should("have.attr", "title", "Details");
			cy.then(async () => {
				for (const type of ["keyDown", "keyUp"]) {
					await Cypress.automation("remote:debugger:protocol", {
						command: "Input.dispatchKeyEvent",
						params: {
							type,
							key: "Enter",
							code: "Enter",
							windowsVirtualKeyCode: 13,
							nativeVirtualKeyCode: 13,
							text: type === "keyDown" ? "\r" : "",
						},
					});
				}
			});
		});
		cy.contains(".modal:visible .scope-source-path", "Included directly").should("be.visible");
		cy.get(".modal:visible .btn-modal-close").click();
		fitsViewport();
		cy.screenshot("project-scope-narrow", { capture: "viewport" });
	});

	it("creates a requirement from the project and adds it directly to its scope", () => {
		const title = `${fixture.prefix} created in Project`;
		openProjectScope(fixture.project);
		moreScopeAction("New Requirement");
		cy.get(modal).within(() => {
			cy.get('[data-fieldname="title"] input').type(title);
			chooseLink("category", fixture.kind);
			chooseLink("author", fixture.contact);
			cy.contains("button", /^Create$/).click();
		});
		cy.location("pathname").should("match", /^\/app\/project-requirement\/.+$/);
		cy.get('[data-fieldname="project"] a[data-name]').should(
			"have.attr",
			"data-name",
			fixture.project
		);
		openProjectScope(fixture.project);
		showProjectSpecifications();
		cy.contains(projectTitles, title)
			.invoke("attr", "row-id")
			.then((id) => {
				cy.get(`${projectRows}[row-id="${id}"]`).within(() => {
					cy.get(".scope-source-list").should("not.exist");
					cy.contains('.ag-cell[col-id="paths"]', "—").should("be.visible");
				});
			});
	});

	it("updates the visible specification state immediately for the author and reviewer", () => {
		cy.viewport(1200, 800);
		const form = ordinaryForm(fixture.review_set);
		cy.visit(form);
		approvalStatus("Draft");
		cy.screenshot("approval-draft", { capture: "viewport" });
		changeApprovalInPlace("Submit for Review", "In Review");
		cy.location("pathname").should("eq", form);
		cy.get(`${workflowMenu} > button`).click();
		cy.contains(`${workflowMenu} .dropdown-menu:visible a`, "Withdraw Review").should(
			"be.visible"
		);
		cy.contains(`${workflowMenu} .dropdown-menu:visible a`, "Approve").should("not.exist");
		cy.get(`${workflowMenu} > button`).click();
		cy.screenshot("approval-in-review", { capture: "viewport" });
		signIn("reviewer");
		cy.visit(form);
		approvalStatus("In Review");
		changeApprovalInPlace("Approve", "Approved");
		cy.location("pathname").should("eq", form);
		cy.contains(`${workflowMenu} a`, /^Approve$/).should("not.exist");
		cy.get(`${compositionRows} a[href$="/${fixture.working}"]`)
			.closest("tr")
			.find("td")
			.eq(1)
			.should("have.text", "Approved");
		approvalHistory().contains("summary", "Approved").should("be.visible");
		cy.get(`${modal} .btn-modal-close`).click();
		cy.screenshot("approval-approved", { capture: "viewport" });
		cy.visit(requirementForm(fixture.working));
		approvalStatus("Approved");
		cy.get('[data-fieldname="status"] select').should("have.value", "Approved");
		cy.screenshot("approval-included-requirement", { capture: "viewport" });
	});

	it("keeps approved templates and their working copies independent across projects", () => {
		cy.visit(templateForm(fixture.template));
		approvalStatus("Draft");
		workflowAction("Submit for Review");
		approvalStatus("In Review");
		signIn("reviewer");
		cy.visit(templateForm(fixture.template));
		workflowAction("Approve");
		approvalStatus("Approved");
		cy.visit(requirementForm(fixture.child));
		approvalStatus("Approved");
		cy.get('[data-fieldname="status"] select').should("have.value", "Template");

		signIn("author");
		applyTemplate(fixture.project, fixture.template, fixture.prefix).then((first) => {
			applyTemplate(
				fixture.other,
				fixture.template,
				fixture.prefix,
				fixture.actors.reviewer.email
			).then((second) => {
				const firstChild = first.requirements[fixture.child];
				const secondChild = second.requirements[fixture.child];
				expect(first.root).not.to.eq(second.root);
				expect(firstChild).not.to.eq(secondChild);
				cy.visit(ordinaryForm(first.root));
				approvalStatus("Draft");
				cy.get(`${compositionRows} a[href$="/${firstChild}"]`)
					.should("have.length", 1)
					.closest(".requirement-form-tree-label")
					.should("have.attr", "style", "--requirement-depth: 1;");
				cy.get(`${compositionRows} a[href$="/${firstChild}"]`).click();
				approvalStatus("Draft");
				cy.get('[data-fieldname="status"] select').should("have.value", "New");
				cy.get(
					'.page-container:visible [data-fieldname="template_source"] a[data-name]'
				).should("have.attr", "data-name", fixture.child);
				const markDone = 'button[data-label="Mark%20Done"]:visible';
				cy.get(markDone).should("not.exist");
				signIn("reviewer");
				cy.visit(requirementForm(firstChild));
				cy.get(markDone).click({ scrollBehavior: "nearest" });
				cy.get('[data-fieldname="status"] select').should("have.value", "Done");
				approvalStatus("Draft");
				signIn("author");
				cy.visit(requirementForm(secondChild));
				cy.get('[data-fieldname="status"] select').should("have.value", "New");
				approvalStatus("Draft");
			});
		});
	});

	it("rejects the stale review and approves a fresh snapshot after a nested change", () => {
		const form = ordinaryForm(fixture.stale_set);
		cy.visit(requirementForm(fixture.stale_requirement));
		workflowAction("Submit for Review");
		approvalStatus("In Review");
		signIn("reviewer");
		cy.visit(requirementForm(fixture.stale_requirement));
		workflowAction("Approve");
		approvalStatus("Approved");

		signIn("author");
		cy.visit(form);
		workflowAction("Submit for Review");
		approvalStatus("In Review");
		cy.visit(ordinaryForm(fixture.stale_nested));
		compositionEditor().within(() => {
			chooseLink("target", fixture.stale_addition);
			cy.contains("button", "Add link").click();
			cy.contains("button", "Save composition").click();
		});
		cy.get(`${compositionRows} a[href$="/${fixture.stale_addition}"]`).should("be.visible");

		signIn("reviewer");
		cy.visit(form);
		approvalStatus("Reapproval Required");
		cy.intercept("POST", workflowApply).as("voteOnStaleSnapshot");
		workflowAction("Approve");
		cy.wait("@voteOnStaleSnapshot")
			.its("response.body")
			.should((body) => {
				expect(JSON.stringify(body)).to.contain(
					"The requirement composition changed. Withdraw the review and submit it again."
				);
			});
		approvalStatus("Reapproval Required");
		cy.visit(requirementForm(fixture.stale_addition));
		cy.get('[data-fieldname="status"] select').should("have.value", "New");
		cy.visit(requirementForm(fixture.stale_requirement));
		approvalStatus("Approved");

		signIn("author");
		cy.visit(form);
		changeApprovalInPlace("Withdraw Review", "Draft", "The nested specification changed.");
		workflowAction("Submit for Review");
		approvalStatus("In Review");
		signIn("reviewer");
		cy.visit(form);
		workflowAction("Approve");
		approvalStatus("Approved");
		approvalHistory().within(() => {
			cy.contains("summary", "Round 2 · Approved")
				.click()
				.parent()
				.contains("summary", `${fixture.prefix} added during review`)
				.should("be.visible");
			cy.contains("summary", "Round 1 · Superseded")
				.click()
				.parent()
				.contains("summary", `${fixture.prefix} added during review`)
				.should("not.exist");
		});
		cy.visit(requirementForm(fixture.stale_addition));
		approvalStatus("Approved");
	});

	it("rejects cyclic, mixed and cross-project composition links", () => {
		const specification = "Project Requirement Specification";
		const requirement = "Project Requirement";
		const argumentsFor = (modified, type, name) => ({
			doctype: specification,
			name: fixture.nested,
			modified,
			items: [{ reference_doctype: type, reference_name: name }],
		});
		cy.openDesk(ordinaryForm(fixture.nested));
		const method = "dinext_project_scope.requirements.direct_composition";
		const args = { doctype: specification, name: fixture.nested };
		cy.call(method, args)
			.its("body.message")
			.then(({ modified, items }) => {
				const url = "/api/method/dinext_project_scope.requirements.replace_composition";
				rejectedWrite(
					"POST",
					url,
					argumentsFor(modified, specification, fixture.ordinary),
					417,
					"contains a cycle"
				);
				rejectedWrite(
					"POST",
					url,
					argumentsFor(modified, requirement, fixture.child),
					417,
					"Template and working requirements must be kept in separate compositions."
				);
				rejectedWrite(
					"POST",
					url,
					argumentsFor(modified, specification, fixture.foreign_spec),
					417,
					"Every working requirement and specification must belong to the same project."
				);
				cy.call(method, args).its("body.message.items").should("deep.equal", items);
			});
	});

	it("limits working requirement parents to groups in the same project", () => {
		const parent = "parent_project_requirement";
		cy.openDesk(requirementForm(fixture.replacement));
		linkSearch(parent, fixture.prefix);
		const choices = `[data-fieldname="${parent}"] .awesomplete ul:visible`;
		cy.contains(`${choices} [role="option"]`, fixture.working).should("be.visible");
		cy.get(choices)
			.should("not.contain.text", fixture.foreign)
			.and("not.contain.text", fixture.parent)
			.and("not.contain.text", fixture.nested_child);
		const resource = `/api/resource/Project%20Requirement/${fixture.replacement}`;
		rejectedWrite(
			"PUT",
			resource,
			{ [parent]: fixture.foreign },
			417,
			"Every working requirement and specification must belong to the same project."
		);
		rejectedWrite(
			"PUT",
			resource,
			{ [parent]: fixture.parent },
			417,
			"Template and working requirements must be kept in separate compositions."
		);
		cy.request(resource).its(`body.data.${parent}`).should("eq", fixture.working);
	});

	it("rejects a non-responsible participant's move to Done and hides the other project", () => {
		const resource = `/api/resource/Project%20Requirement/${fixture.working}`;
		cy.openDesk(requirementForm(fixture.working));
		rejectedWrite("PUT", resource, { status: "Done" }, 403, fixture.actors.reviewer.email);
		cy.get('[data-fieldname="status"] select').should("not.have.value", "Done");
		signIn("outsider");
		cy.openDesk(requirementForm(fixture.foreign));
		rejectedWrite(
			"POST",
			"/api/method/dinext_project_scope.requirements.project_rows",
			{ project: fixture.project },
			403,
			"You do not have access to the selected project."
		);
	});

	it("links the same goal in two projects and hides it from a reader without goal access", () => {
		const page = ".page-container:visible";
		const goalGrid = `${page} [data-fieldname="goals"]`;
		const goalField = `${goalGrid} .grid-row-open [data-fieldname="goal"]`;
		const related = `${page} .requirement-form-related`;
		prepareSession();
		cy.call(`${fixtureApi}.create_goal_fixture`, { run_id: runId }, fixtureRequest)
			.its("body.message")
			.then(({ shared, private: privateGoal }) => {
				signIn("author");
				cy.intercept("POST", "/api/method/frappe.desk.form.save.savedocs").as(
					"saveGoalLink"
				);
				for (const name of [fixture.working, fixture.foreign]) {
					cy.openDesk(requirementForm(name));
					cy.get(`${goalGrid} .grid-add-row`).click({ scrollBehavior: "center" });
					cy.get(`${goalGrid} .grid-body .btn-open-row`).click({
						scrollBehavior: "center",
					});
					cy.get(`${goalField} input:visible`).type(fixture.prefix, { delay: 0 });
					linkOptions(goalField).should(($options) => {
						const names = [...$options].map(optionValue);
						expect(names).to.include(shared).and.not.include(privateGoal);
					});
					linkOption(goalField, shared).click({ scrollBehavior: "nearest" });
					cy.get(`${goalField} input:visible`).blur();
					cy.get(`${goalGrid} .grid-collapse-row`).click();
					cy.contains(`${page} .primary-action`, /^\s*Save\s*$/).click({
						scrollBehavior: "center",
					});
					cy.wait("@saveGoalLink").its("response.statusCode").should("eq", 200);
					cy.get(`${related} a[href$="/${shared}"]`).should("be.visible");
					cy.request(`/api/resource/Project%20Requirement/${name}`)
						.its("body.data.goals.0.goal")
						.should("eq", shared);
				}
				cy.get(`${related} a[href$="/${shared}"]`).click({ scrollBehavior: "center" });
				cy.location("pathname").should("eq", `/app/goal/${shared}`);

				signIn("reviewer");
				cy.openDesk(requirementForm(fixture.working));
				cy.get(related)
					.should("be.visible")
					.find(`a[href$="/${shared}"]`)
					.should("not.exist");
				cy.request(`/api/resource/Project%20Requirement/${fixture.working}`)
					.its("body.data.goals")
					.should("deep.equal", []);
				cy.request({ url: `/api/resource/Goal/${shared}`, failOnStatusCode: false })
					.its("status")
					.should("eq", 403);
			});
	});
});
