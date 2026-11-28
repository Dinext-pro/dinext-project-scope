import { linkOption, linkOptions, optionValue } from "../support/link_options";

const fixtureApi = "dinext_project_scope.tests.operations_ui_test_helpers";
const runId = Array.from(crypto.getRandomValues(new Uint8Array(8)), (part) =>
	part.toString(16).padStart(2, "0")
).join("");
const page = ".page-container:visible";
const modal = ".modal:visible";
const rowForm = ".grid-row-open .form-in-grid";
const workflowButton = `${page} .actions-btn-group > button:visible`;
const workflowItem = `${page} .actions-btn-group .dropdown-menu:visible a`;
let fixture;
let linkSearchNumber = 0;

function actor(role) {
	cy.login(fixture.actors[role], fixture.password);
}

function openForm(doctype, name) {
	cy.openDesk(`/app/${doctype}/${encodeURIComponent(name)}`);
	readForm((doc) => expect(doc.name).to.eq(name));
}

function readForm(check) {
	cy.window().should((window) => {
		expect(window.cur_frm?.doc).to.exist;
		check(window.cur_frm.doc);
	});
}

function fields(name, host = page) {
	return `${host} .frappe-control[data-fieldname="${name}"]:visible`;
}

function type(name, value, host = page) {
	cy.get(fields(name, host)).find("input:visible, textarea:visible").clear().type(value).blur();
}

function select(name, value, host = page) {
	cy.get(fields(name, host)).find("select:visible").select(value);
}

function chooseLink(name, value, host = page, search = value) {
	const field = fields(name, host);
	const alias = `scopeLinkSearch${++linkSearchNumber}`;
	cy.intercept("POST", "**/api/method/frappe.desk.search.search_link", (request) => {
		if (new URLSearchParams(request.body).get("txt") === search) {
			request.alias = alias;
			request.continue();
		}
	});
	cy.get(field)
		.find("input:visible")
		.clear({ scrollBehavior: "center" })
		.type(search, { delay: 0, scrollBehavior: "center" });
	cy.wait(`@${alias}`).its("response.statusCode").should("eq", 200);
	linkOption(field, value).click({ scrollBehavior: "center" });
	cy.get(field)
		.find("input:visible")
		.then(($input) => $input[0].blur());
}

function checkWorkChoices(search, included, excluded) {
	const field = fields("element", rowForm);
	cy.get(field).find("input:visible").type(search, { delay: 0 });
	linkOptions(field).should(($options) => {
		const values = [...$options].map(optionValue);
		expect(values).to.include(included);
		expect(values).not.to.include(excluded);
	});
}

function selectDate(name, isoDate, host = page) {
	const [year, month, day] = isoDate.split("-").map(Number);
	cy.get(fields(name, host))
		.find("input:visible")
		.click({ scrollBehavior: "center" })
		.then(([input]) => {
			const view = input.ownerDocument.defaultView;
			const picker = view.$(input).data("datepicker");
			picker.date = new view.Date(year, month - 1, 1);
			const cell = `.datepicker--cell-day[data-year="${year}"][data-month="${
				month - 1
			}"][data-date="${day}"]`;
			cy.wrap(picker.$datepicker[0], { log: false })
				.find(cell)
				.click({ scrollBehavior: false });
		});
}

function showTaskTimeline() {
	const section = `${page} .form-section[data-fieldname="sb_timeline"]`;
	cy.get(section).then(($section) => {
		if (!$section.find(".section-body").is(":visible")) {
			cy.get(`${section} .section-head`).click({ scrollBehavior: "center" });
		}
	});
	cy.get(`${section} .section-body`).should("be.visible");
}

function grid(table) {
	return `${page} [data-fieldname="${table}"]`;
}

function row(table, idx) {
	return `${grid(table)} .grid-body .grid-row[data-idx="${idx}"]`;
}

function editRow(table, idx) {
	cy.get(`${row(table, idx)} .btn-open-row`).click();
	cy.get(rowForm)
		.should("be.visible")
		.then(($form) => {
			const first = $form.find("input:first").get(0);
			const doc = $form[0].ownerDocument.defaultView.cur_frm.doc;
			if (
				doc.docstatus === 0 &&
				first &&
				Cypress.$(first).is(":visible") &&
				!first.disabled &&
				!first.readOnly
			) {
				cy.document().should((document) => expect(document.activeElement).to.eq(first));
			}
		});
}

function addRow(table, idx) {
	cy.get(`${grid(table)} .grid-add-row`).click();
	editRow(table, idx);
}

function closeRow() {
	cy.get(".grid-row-open .grid-collapse-row").click();
	cy.window().then(
		(window) =>
			new Cypress.Promise((resolve) =>
				window
					.$("html, body")
					.promise()
					.done(() => resolve())
			)
	);
}

function clickSave() {
	cy.scrollTo("top", { ensureScrollable: false });
	cy.contains(`${page} .page-actions .primary-action:visible`, /^\s*(Save|Update)\s*$/).click({
		scrollBehavior: false,
	});
}

function save() {
	clickSave();
	cy.window().should((window) => {
		const frm = window.cur_frm;
		expect(frm?.doc?.name).to.be.a("string");
		expect(Boolean(frm.is_new())).to.be.false;
		expect(Boolean(frm.is_dirty())).to.be.false;
	});
}

function scopeTab() {
	cy.get('button[data-fieldname="custom_объем"]').click();
}

function openActions() {
	cy.scrollTo("top", { ensureScrollable: false });
	cy.get(workflowButton).click({ scrollBehavior: false });
}

function action(label, comment) {
	openActions();
	cy.contains(workflowItem, new RegExp(`^\\s*${label}\\s*$`)).click();
	if (comment) {
		type("comment", comment, modal);
		cy.get(`${modal} .modal-footer .btn-primary`).contains("Apply").click();
	}
}

function state(value) {
	readForm((doc) => expect(doc.status).to.eq(value));
}

function shot(name) {
	cy.screenshot(name, { capture: "viewport" });
}

describe("Project scope operations in Desk", () => {
	before(() => {
		cy.login();
		cy.openDesk("/app/project");
		cy.call(`${fixtureApi}.create_fixture`, { run_id: runId }).then(({ body }) => {
			fixture = body.message;
		});
	});

	after(() => {
		cy.login();
		cy.openDesk("/app/project");
		cy.call(`${fixtureApi}.remove_fixture`, { run_id: runId });
	});

	it("creates typed result slots and saves weighted Task and nested result links", () => {
		actor("author");
		cy.openDesk("/app/project-deliverable");
		cy.get(`${page} .page-actions .primary-action:visible`).click();
		type("title", `${fixture.label} user-created weighted result`);
		chooseLink("project", fixture.project);
		chooseLink("category", fixture.category);
		chooseLink("deliverable_type", fixture.parent_type);
		cy.get(`${grid("table_xuct")} .grid-body .grid-row`).should("have.length", 2);
		cy.get(`${grid("table_xuct")} .grid-add-row`).should("not.be.visible");
		editRow("table_xuct", 1);
		chooseLink("element", fixture.baseline, rowForm);
		closeRow();
		editRow("table_xuct", 2);
		chooseLink("element", fixture.leaf, rowForm);
		type("weight", "3", rowForm);
		closeRow();
		save();
		readForm((doc) => {
			expect(doc.owner).to.eq(fixture.actors.author);
			expect(doc.progress).to.eq(40);
			expect(doc.planned_start_date).to.eq("2026-11-01");
			expect(doc.planned_end_date).to.eq("2026-11-09");
			expect(doc.actual_end_date).not.to.be.ok;
		});
		cy.get(fields("progress")).should("contain.text", "40");
		shot("operations-weighted-result");
	});

	it("filters a Task link by type and recalculates a parent after a Task forecast edit", () => {
		actor("author");
		openForm("project-deliverable", fixture.leaf);
		editRow("table_xuct", 2);
		checkWorkChoices(fixture.label, fixture.partial, fixture.wrong_type);
		closeRow();

		openForm("task", fixture.partial);
		showTaskTimeline();
		type("progress", "60");
		selectDate("exp_end_date", "2026-11-26");
		readForm((doc) => {
			expect(doc.progress).to.eq(60);
			expect(doc.exp_end_date).to.eq("2026-11-26");
		});
		save();
		openForm("project-deliverable", fixture.parent);
		readForm((doc) => {
			expect(doc.progress).to.eq(80);
			expect(doc.planned_end_date).to.eq("2026-11-09");
			expect(doc.expected_end_date).to.eq("2026-11-26");
		});
		shot("operations-forecast-after-task-edit");
	});

	it("limits project results and work links to the signed-in user's project", () => {
		actor("author");
		cy.openDesk("/app/project-deliverable");
		cy.get(`a[href$="/${encodeURIComponent(fixture.acceptance)}"]`).should("be.visible");
		cy.get(`a[href$="/${encodeURIComponent(fixture.foreign_result)}"]`).should("not.exist");
		cy.request({
			url: `/api/resource/Project%20Deliverable/${encodeURIComponent(
				fixture.foreign_result
			)}`,
			failOnStatusCode: false,
		}).then(({ status, body }) => {
			expect(status).to.eq(403);
			expect(body).not.to.have.property("data");
		});

		openForm("project-deliverable", fixture.leaf);
		editRow("table_xuct", 2);
		checkWorkChoices(fixture.label, fixture.partial, fixture.foreign_task);
		shot("operations-project-scoped-work-picker");
		closeRow();
	});

	it("saves equally named User and Contact assignments as distinct participants", () => {
		actor("author");
		openForm("project-deliverable", fixture.parent);
		for (const [idx, kind, name] of [
			[1, "User", fixture.actors.author],
			[2, "Contact", fixture.contact],
		]) {
			addRow("deliverable_responsibles", idx);
			chooseLink("responsibility", fixture.responsibility, rowForm);
			if (idx === 1) {
				cy.intercept("POST", "**/api/method/frappe.desk.search.search_link", (request) => {
					const params = new URLSearchParams(request.body);
					if (
						params.get("doctype") === "Project Role" &&
						params.get("txt") === fixture.excluded_role
					) {
						request.alias = "excludedRole";
					}
				});
				const roleInput = `${fields("project_role", rowForm)} input:visible`;
				cy.get(roleInput).type(fixture.excluded_role, { delay: 0 });
				cy.wait("@excludedRole").its("response.body.message").should("deep.eq", []);
				cy.get(roleInput).clear();
			}
			chooseLink("project_role", fixture.role, rowForm);
			select("responsible_type", kind, rowForm);
			chooseLink("responsible", name, rowForm);
			closeRow();
		}
		save();
		cy.reload();
		readForm((doc) => {
			expect(
				doc.deliverable_responsibles.map((row) => [row.responsible_type, row.responsible])
			).to.deep.eq([
				["User", fixture.actors.author],
				["Contact", fixture.contact],
			]);
		});
		shot("operations-typed-assignments");
	});

	it("requires the project reviewer to clear a cancelled-work blocker before accepting the result", () => {
		actor("author");
		openForm("project-deliverable", fixture.acceptance);
		cy.get(fields("acceptance_html")).should(
			"contain.text",
			"Complete the linked work for Optional work."
		);
		shot("operations-acceptance-not-started");
		action("Request Acceptance");
		state("Acceptance");
		shot("operations-acceptance-requested");

		actor("reviewer");
		openForm("project-deliverable", fixture.acceptance);
		action("Accept Deliverable");
		cy.get(modal).should("contain.text", "Complete the linked work for Optional work.");
		state("Acceptance");
		shot("operations-acceptance-blocked");
		openForm("project-deliverable", fixture.acceptance);
		editRow("table_xuct", 2);
		cy.get(fields("element", rowForm)).find("input").clear();
		cy.get(fields("weight", rowForm)).find("input").click();
		readForm((doc) => expect(doc.table_xuct[1].element).not.to.be.ok);
		closeRow();
		save();
		cy.get(fields("acceptance_html")).should("contain.text", "Work is ready for acceptance.");
		shot("operations-acceptance-ready");
		openForm("project-deliverable", fixture.acceptance);
		action("Accept Deliverable");
		state("Completed");
		readForm((doc) => {
			expect(doc.actual_end_date).to.eq(fixture.finished_on);
			expect(doc.last_acceptance_log).to.be.a("string");
			expect(doc.table_xuct).to.have.length(2);
			expect(doc.table_xuct[1].element).not.to.be.ok;
		});
		shot("operations-acceptance-completed");
		openForm("project-requirement", fixture.requirement);
		cy.get(`${page} .requirement-form-related a[href$="/${fixture.acceptance}"]`)
			.should("be.visible")
			.parent()
			.should("contain.text", "Completed");
		cy.get(fields("status")).find("select").should("have.value", "New");
		cy.intercept("POST", "**/api/method/frappe.desk.form.save.savedocs").as(
			"markRequirementDone"
		);
		cy.get('button[data-label="Mark%20Done"]:visible').click({ scrollBehavior: "nearest" });
		cy.wait("@markRequirementDone").its("response.statusCode").should("eq", 200);
		cy.get(fields("status")).find("select").should("have.value", "Done");
		cy.request(`/api/resource/Project%20Requirement/${fixture.requirement}`)
			.its("body.data.status")
			.should("eq", "Done");

		actor("author");
		openForm("task", fixture.baseline);
		showTaskTimeline();
		selectDate("custom_planned_end_date", "2026-11-20");
		readForm((doc) => expect(doc.custom_planned_end_date).to.eq("2026-11-20"));
		save();
		actor("reviewer");
		openForm("project-deliverable", fixture.acceptance);
		state("Completed");
		cy.get(fields("acceptance_html")).should("contain.text", "Requires recheck");
		shot("operations-acceptance-recheck");
		action("Reconfirm Acceptance", "The revised schedule preserves the delivered work.");
		readForm((doc) => {
			expect(doc.status).to.eq("Completed");
			expect(Number(doc.requires_recheck)).to.eq(0);
		});
		shot("operations-acceptance-reconfirmed");
	});

	it("explains and prevents acceptance when no project manager can review it", () => {
		actor("observer");
		openForm("project-deliverable", fixture.foreign_result);
		const message = "Assign one active user to the project manager role";
		cy.get(fields("acceptance_html")).should("contain.text", message);
		action("Request Acceptance");
		cy.get(modal).should("contain.text", message);
		state("Not Started");
	});

	it("previews and applies project constraints then records verification from the Project form", () => {
		actor("author");
		openForm("project", fixture.project);
		scopeTab();
		cy.contains(
			'[data-fieldname="project_constraints"] button',
			"Apply Constraints Template"
		).click({ scrollBehavior: "center" });
		chooseLink("item", `${fixture.label} constraints`, modal);
		cy.get(`${modal} .modal-footer .btn-primary`).click();
		cy.get(modal).should("contain.text", `${fixture.label} capacity limit`);
		cy.get(modal).should("contain.text", `${fixture.label} availability`);
		cy.get(`${modal} select[aria-label="Responsible ${fixture.label} availability"]`).select(
			`${fixture.actors.author} · User`
		);
		shot("operations-constraints-preview");
		cy.contains(`${modal} button.btn-primary`, "Apply Template").click();
		readForm((doc) => {
			expect(doc.project_constraints).to.have.length(2);
			expect(doc.project_constraints.map((entry) => entry.status)).to.deep.eq([
				"New",
				"New",
			]);
			const assumption = doc.project_constraints.find(
				(entry) => entry.record_type === "Assumption"
			);
			expect(assumption.verification_status).to.eq("Pending");
			expect(assumption.responsible).to.eq(fixture.actors.author);
		});
		scopeTab();
		editRow("project_constraints", 2);
		select("verification_status", "Confirmed", rowForm);
		closeRow();
		cy.intercept("POST", "**/api/method/frappe.desk.form.save.savedocs").as("saveAssumption");
		clickSave();
		cy.wait("@saveAssumption")
			.its("response")
			.should(({ statusCode, body }) => {
				expect(statusCode).to.eq(417);
				expect(JSON.stringify(body)).to.contain(
					"Describe the evidence or select an attachment"
				);
			});
		cy.reload();
		readForm((doc) => expect(doc.project_constraints[1].verification_status).to.eq("Pending"));
		scopeTab();
		editRow("project_constraints", 2);
		select("verification_status", "Confirmed", rowForm);
		type("verification_note", "The participant confirmed resource availability.", rowForm);
		selectDate("review_date", "2026-11-27", rowForm);
		closeRow();
		save();
		cy.reload();
		readForm((doc) => {
			const row = doc.project_constraints.find(
				(entry) => entry.record_type === "Assumption"
			);
			expect(row.verification_status).to.eq("Confirmed");
			expect(row.verified_by).to.eq(fixture.actors.author);
			expect(row.review_date).to.eq("2026-11-27");
			expect(row.verification_note).to.eq(
				"The participant confirmed resource availability."
			);
		});
		scopeTab();
		editRow("project_constraints", 2);
		shot("operations-assumption-confirmed");
		closeRow();
		cy.window()
			.its("cur_frm.doc.project_constraints.1.name")
			.then((assumption) => {
				openForm("project-deliverable", fixture.leaf);
				chooseLink(
					"deliverable_constraints",
					assumption,
					page,
					`${fixture.label} availability`
				);
				save();
				cy.reload();
				readForm((doc) =>
					expect(doc.deliverable_constraints[0].project_constraint).to.eq(assumption)
				);
				cy.get(
					`${fields("deliverable_constraints")} .tb-selected-value .btn-link-to-form`
				).should("have.text", `${fixture.label} availability`);
				shot("operations-assumption-linked-to-result");
			});
	});

	it("requires a project before saving a new result", () => {
		actor("author");
		cy.openDesk("/app/project-deliverable");
		cy.get(`${page} .page-actions .primary-action:visible`).click();
		type("title", `${fixture.label} result without project`);
		chooseLink("category", fixture.category);
		chooseLink("deliverable_type", fixture.work_type);
		cy.get(fields("project")).find("input:visible").should("have.value", "");
		clickSave();
		cy.get(`${modal} .modal-title`).should("have.text", "Missing Fields");
		cy.contains(`${modal} .modal-body li`, "Project is required.").should("be.visible");
		readForm((doc) => expect(Boolean(doc.__islocal)).to.be.true);
	});

	it("only offers Not Started when creating a result", () => {
		actor("author");
		cy.openDesk("/app/project-deliverable");
		cy.get(`${page} .page-actions .primary-action:visible`).click();
		cy.get(fields("status"))
			.find("select:visible")
			.should("have.value", "Not Started")
			.find("option")
			.should(($options) => {
				expect([...$options].map((option) => option.value).filter(Boolean)).to.deep.equal([
					"Not Started",
				]);
			});
	});

	it("preserves both change-review rounds and records implementation as the project owner", () => {
		actor("author");
		openForm("project", fixture.project);
		scopeTab();
		cy.contains("button", "New Change Request").click();
		type("title", `${fixture.label} change`);
		chooseLink("initiator", fixture.contact);
		type("description", "Change the completion date for two tasks.");
		chooseLink("implementation_responsible", fixture.actors.author);
		for (const [idx, level, estimate, task] of [
			[1, "Strong", "3–5", fixture.baseline],
			[2, "Weak", "1–2", fixture.partial],
		]) {
			addRow("change_relations", idx);
			chooseLink("type", fixture.impact, rowForm);
			select("level", level, rowForm);
			type("estimation", estimate, rowForm);
			type("explanation", "The updated sequence may shift this task.", rowForm);
			chooseLink("link", task, rowForm);
			closeRow();
		}
		save();
		state("Draft");
		shot("operations-change-draft");
		cy.location("pathname").then((path) => {
			const name = decodeURIComponent(path.split("/").at(-1));
			action("Submit for Review");
			state("In Review");
			shot("operations-change-in-review");
			openActions();
			cy.contains(workflowItem, "Withdraw Review").should("be.visible");
			cy.contains(workflowItem, /^\s*(Approve|Reject)\s*$/).should("not.exist");
			shot("operations-change-author-actions");

			actor("reviewer");
			openForm("project-change-request", name);
			action("Reject", "Please allow for completion of the dependent work.");
			state("Rejected");
			shot("operations-change-rejected");

			actor("author");
			openForm("project-change-request", name);
			action("Return to Draft");
			state("Draft");
			openForm("project-change-request", name);
			editRow("change_relations", 1);
			type("estimation", "4–6", rowForm);
			closeRow();
			save();
			action("Submit for Review");
			state("In Review");
			shot("operations-change-resubmitted");

			actor("reviewer");
			openForm("project-change-request", name);
			action("Approve");
			state("Approved");
			shot("operations-change-approved");
			openActions();
			cy.contains(workflowItem, "Cancel").should("be.visible");
			cy.contains(workflowItem, "Mark Implemented").should("not.exist");
			shot("operations-change-reviewer-actions");

			actor("author");
			openForm("project-change-request", name);
			cy.get(fields("title")).find("input:visible").should("not.exist");
			selectDate("implementation_date", "2026-11-18");
			type("implementation_note", "The completion date was updated.");
			addRow("implementation_items", 1);
			select("reference_doctype", "Task", rowForm);
			chooseLink("reference_name", fixture.baseline, rowForm);
			closeRow();
			save();
			action("Mark Implemented");
			state("Implemented");
			readForm((doc) => {
				expect(doc.docstatus).to.eq(1);
				expect(doc.implemented_by).to.eq(fixture.actors.author);
				expect(doc.implementation_items[0].reference_name).to.eq(fixture.baseline);
			});
			shot("operations-change-implemented");
			openForm("project-change-request", name);
			cy.contains(`${page} button`, "Approval History").click();
			cy.contains(`${modal} summary`, "Rejected").click();
			cy.contains(`${modal} summary`, "Approved").click();
			cy.get(modal).should("contain.text", "3–5 · Day").and("contain.text", "4–6 · Day");
			shot("operations-change-approval-history");
		});
	});
});
