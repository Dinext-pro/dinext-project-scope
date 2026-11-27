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
const deliverables = "Project Deliverable Register";
const constraints = "Project Constraint Register";

function assignmentRow(title) {
	return rowLink(title)
		.closest(".ag-row")
		.invoke("attr", "row-id")
		.then((id) => cy.get(`${table} .ag-center-cols-container [row-id="${id}"]`));
}

function clickFullscreenControl(title) {
	cy.get(`${table} button[title="${title}"]`)
		.should("be.visible")
		.then(async ([button]) => {
			// Chromium requires trusted user input to enter fullscreen.
			button.scrollIntoView({ block: "nearest" });
			const rect = button.getBoundingClientRect();
			let x = rect.left + rect.width / 2;
			let y = rect.top + rect.height / 2;
			const view = button.ownerDocument.defaultView;
			const frame =
				view.frameElement || view.parent.document.querySelector("iframe.aut-iframe");
			if (frame) {
				const bounds = frame.getBoundingClientRect();
				x = bounds.left + (x * bounds.width) / frame.offsetWidth;
				y = bounds.top + (y * bounds.height) / frame.offsetHeight;
			}
			for (const type of ["mousePressed", "mouseReleased"]) {
				await Cypress.automation("remote:debugger:protocol", {
					command: "Input.dispatchMouseEvent",
					params: { type, x, y, clickCount: 1, button: "left" },
				});
			}
		});
}

function pressFullscreenControl(root, title) {
	cy.get(`${root} button[title="${title}"]`)
		.scrollIntoView({ offset: { top: -160, left: 0 } })
		.should("be.visible")
		.focus();
	cy.focused().should("have.attr", "title", title);
	cy.then(async () => {
		// Use trusted keyboard input for the fullscreen button after scrolling the project form.
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
}

function expectCentered(selector, property = "text-align") {
	cy.get(selector).should((elements) => {
		for (const element of elements) {
			const style = element.ownerDocument.defaultView.getComputedStyle(element);
			expect(style.getPropertyValue(property)).to.eq("center");
		}
	});
}

function scopeToolbarEnd(pane, fullscreenTitle) {
	cy.get(`${pane} .dinext-table-toolbar-group--end button`).should((buttons) => {
		expect([...buttons].map(({ title }) => title)).to.deep.eq(["Excel", fullscreenTitle]);
	});
}

describe("Project scope reports", () => {
	const fixture = useReportFixture();

	it("shows the unique requirements tree, constraints and requests inside Project Scope", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		cy.get('[data-fieldname="project_scopes"] .grid-body').should("be.visible");
		cy.get('[data-fieldname="project_constraints"] .grid-body').should("be.visible");
		cy.get(
			'[data-fieldname="custom_scope_requirements_html"] .ag-center-cols-container .ag-row'
		)
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

	it("opens and closes the four native Scope sections independently", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		const layouts = [
			["custom_scope_items_section", "project_scopes", 1],
			["custom_scope_requirements_section", "custom_scope_requirements_html", 4],
			["custom_scope_constraints_section", "project_constraints", 4],
			["custom_scope_changes_section", "custom_scope_changes_html", 4],
		];
		for (const [section, field, charts] of layouts) {
			const group = `.form-section[data-fieldname="${section}"]`;
			const content = `${group} [data-fieldname="${field}"]`;
			const header = `${group} .section-head.collapsible`;
			cy.get(content).should("be.visible");
			cy.get(content).should(($content) => {
				expect($content.find(".dinext-scope-chart-card")).to.have.length(charts);
			});
			cy.get(header).click();
			cy.get(content).should("not.be.visible");
			cy.get(header).click();
			cy.get(content).should("be.visible");
		}
	});

	it("centers Scope headers and requirement values and displays priority badges", () => {
		cy.login(fixture.actor, fixture.password);
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		for (const field of ["project_scopes", "project_constraints"]) {
			const header = `[data-fieldname="${field}"] .grid-heading-row`;
			expectCentered(`${header} .grid-static-col .static-area`);
		}
		const requirements = '[data-fieldname="custom_scope_requirements_html"]';
		const changes = '[data-fieldname="custom_scope_changes_html"]';
		for (const pane of [requirements, changes]) {
			expectCentered(`${pane} .ag-header-cell-label`, "justify-content");
		}
		for (const field of ["priority", "kind", "requirement_importance"]) {
			expectCentered(`${requirements} .ag-center-cols-container [col-id="${field}"]`);
		}
		cy.get(`${requirements} [col-id="priority"] .indicator-pill.orange`)
			.should("be.visible")
			.and("have.text", "High");
	});

	it("renders centered constraint and change statuses from Document States", () => {
		cy.login(fixture.actor, fixture.password);
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		const native = '[data-fieldname="project_constraints"] .grid-body';
		for (const field of ["category", "record_type", "status"]) {
			expectCentered(`${native} [data-fieldname="${field}"] .static-area`);
		}
		for (const [selector, doctype] of [
			[`${native} [data-fieldname="status"] .static-area`, "Project Constraint"],
			[
				'[data-fieldname="custom_scope_changes_html"] .ag-body [col-id="status"]',
				"Project Change Request",
			],
		]) {
			cy.get(selector)
				.first()
				.should(([cell]) => {
					const view = cell.ownerDocument.defaultView;
					const pill = cell.querySelector(".indicator-pill");
					expect(pill, doctype).to.exist;
					expect(pill.title).to.eq(pill.textContent);
					const state = view.frappe
						.get_meta(doctype)
						.states.find(
							(row) => view.__(row.title, null, doctype) === pill.textContent
						);
					expect(state?.color, `${doctype} color in Document States`).to.be.a("string");
					expect(pill.classList.contains(view.frappe.scrub(state.color, "-"))).to.eq(
						true
					);
					expect(view.getComputedStyle(cell).textAlign).to.eq("center");
				});
		}
		cy.get(`${native} .btn-open-row`).first().click({ scrollBehavior: "center" });
		const subject = `${native} .grid-row-open .form-in-grid .frappe-control[data-fieldname="subject"]`;
		cy.get(subject).should(($subject) => {
			expect($subject).to.be.visible;
			const value =
				$subject.find("input:visible").val() ??
				$subject.find(".control-value:visible").text();
			expect(value).to.eq(`${fixture.title} assumption`);
		});
	});

	for (const [label, field, filter] of [
		["Requirements", "custom_scope_requirements_html", "kind"],
		["Change Requests", "custom_scope_changes_html", "creation"],
	]) {
		it(`keeps ${label} charts and filters in fullscreen with internal table scrolling`, () => {
			cy.login(fixture.actor, fixture.password);
			cy.visit(`/app/project/${fixture.project}`);
			cy.get('button[data-fieldname="custom_объем"]').click();
			const pane = `[data-fieldname="${field}"] .dinext-project-scope`;
			scopeToolbarEnd(pane, "Fullscreen");
			pressFullscreenControl(pane, "Fullscreen");
			scopeToolbarEnd(pane, "Exit fullscreen");
			cy.get(pane).should(([root]) => {
				expect(root.ownerDocument.fullscreenElement).to.eq(root);
				expect(root.querySelectorAll(".dinext-scope-chart canvas")).to.have.length(4);
				const table = root.querySelector(".scope-embedded-grid");
				const viewport = root.querySelector(".ag-body-viewport");
				expect(viewport.clientHeight, "table body height").to.be.greaterThan(50);
				expect(table.getBoundingClientRect().bottom).to.be.closeTo(
					root.getBoundingClientRect().bottom,
					24
				);
				expect(root.scrollHeight).to.be.at.most(root.clientHeight + 1);
			});
			const control = `${pane} select[data-fieldname="${filter}"]`;
			cy.get(control).select(1).should("not.have.value", "");
			cy.get(`${pane} .dinext-scope-chart canvas`).should("have.length", 4);
			cy.get(pane).should(([root]) =>
				expect(root.ownerDocument.fullscreenElement).to.eq(root)
			);
			pressFullscreenControl(pane, "Exit fullscreen");
			cy.document().should(({ fullscreenElement }) => expect(fullscreenElement).to.be.null);
			cy.get(control).should("not.have.value", "");
		});
	}

	it("downloads each Scope table with the active filter as an Excel workbook", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		for (const [field, tableName, filter, pick, stem] of [
			["project_scopes", "scope_items", "scope_type", fixture.title, "project-scope-items"],
			[
				"custom_scope_requirements_html",
				"requirements",
				"priority",
				"High",
				"project-requirements",
			],
			[
				"project_constraints",
				"constraints",
				"responsible",
				"User:" + fixture.actor,
				"project-constraints",
			],
			[
				"custom_scope_changes_html",
				"change_requests",
				"status",
				"Draft",
				"project-change-requests",
			],
		]) {
			const pane = `[data-fieldname="${field}"]`;
			const url =
				"**/api/method/dinext_project_scope.analytics.export.download_project_scope_table";
			cy.intercept("POST", url).as(tableName);
			cy.get(pane + ` select[data-fieldname="${filter}"]`).select(pick);
			const exportButton = pane + ' button[title="Excel"]:visible';
			if (tableName === "requirements" || tableName === "change_requests") {
				scopeToolbarEnd(pane, "Fullscreen");
			}
			cy.get(exportButton).find('svg path[stroke="currentColor"]').should("exist");
			cy.get(exportButton).click();
			cy.wait("@" + tableName).then(({ response, request }) => {
				expect(response.statusCode).to.eq(200);
				expect(response.headers["content-disposition"]).to.contain(stem + ".xlsx");
				const params = new URLSearchParams(request.body);
				expect(params.get("table")).to.eq(tableName);
				expect(JSON.parse(params.get("filters"))).to.deep.eq({ [filter]: pick });
			});
			cy.readFile(`${Cypress.config("downloadsFolder")}/${stem}.xlsx`, null, {
				timeout: 30000,
			}).should((bytes) => expect(bytes.slice(0, 2).toString()).to.eq("PK"));
		}
	});

	it("opens the change impact matrix from the change grid and keeps project menus clear", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		cy.get(
			'.inner-group-button[data-label="Scope%20Reports"], .inner-group-button[data-label="Scope"]'
		).should("not.exist");
		cy.get('[data-fieldname="custom_scope_changes_html"] .ag-row').should("be.visible");
		cy.contains(
			'[data-fieldname="custom_scope_changes_html"] .dinext-table-toolbar button',
			impact
		)
			.should("be.visible")
			.find("svg")
			.should("exist");
		cy.contains(
			'[data-fieldname="custom_scope_changes_html"] .dinext-table-toolbar button',
			impact
		).click();
		reportShown(impact, { project: fixture.project });
		rowLink(`${fixture.title} change`).should("be.visible");
	});

	it("ships the requested default columns in the native child tables", () => {
		cy.visit(`/app/project/${fixture.project}`);
		cy.get('button[data-fieldname="custom_объем"]').click();
		cy.window().should(({ cur_frm }) => {
			for (const [field, expected] of [
				["project_scopes", ["Title", "Type", "Object"]],
				[
					"project_constraints",
					["Subject", "Category", "Record Type", "Status", "Responsible"],
				],
			]) {
				expect(
					cur_frm.get_field(field).grid.visible_columns.map(([column]) => column.label)
				).to.deep.eq(expected);
			}
		});
		cy.call("frappe.client.get_count", {
			doctype: "Report",
			filters: { name: "Project Scope Overview" },
		})
			.its("body.message")
			.should("eq", 0);
	});

	it("keeps deliverables progress in the Project dashboard after a rebuild and hides it without results", () => {
		const card = '[data-pwa-bar="deliverables"]';
		const readiness = `.form-graph ${card}`;
		const formula =
			"Average progress of unique root deliverables with equal weight for each. Cancelled deliverables are excluded.";
		cy.intercept({
			method: "GET",
			pathname: "/api/method/dinext_project_scope.analytics.data.project_progress",
			query: { project: fixture.project },
		}).as("deliverablesProgress");
		cy.visit(`/app/project/${fixture.project}`);
		cy.wait("@deliverablesProgress").then(({ response }) => {
			const planned = response.body.message.planned_progress;
			expect(planned).not.to.eq(undefined);
			const plan =
				planned === null
					? "Plan is incomplete"
					: `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
							planned
					  )}%`;
			cy.get(`${readiness} .chart-title`).should("have.text", "Deliverables");
			cy.get(`${readiness} .chart-percent`).should("have.text", "20%");
			const meter = `${readiness} [role="progressbar"]`;
			cy.get(meter).should("have.attr", "aria-valuenow", "20");
			cy.get(meter).should("have.attr", "aria-description", formula);
			cy.get(`${meter} .progress-bar-fill`).should(([fill]) => {
				const style = fill.ownerDocument.defaultView.getComputedStyle(fill);
				expect(style.animationName).to.be.oneOf([
					"pwa-dash-slide-in",
					"dinext-scope-progress-fill",
				]);
				expect(fill.style.width).to.eq("20%");
			});
			cy.get(meter).focus();
			cy.get(`${readiness} [role="tooltip"]`)
				.should("be.visible")
				.and("contain.text", `Plan: ${plan}`)
				.and("contain.text", "Fact: 20%");
		});
		cy.get('[data-fieldname="custom_scope_deliverables_progress_html"] progress').should(
			"not.exist"
		);
		let previousRow;
		cy.window().then((view) => {
			const host = view.cur_frm.dashboard.chart_area.wrapper[0];
			previousRow = host.querySelector(".dashboard-percents");
			if (typeof view.load_and_render_project_dashboard === "function") {
				view.load_and_render_project_dashboard(view.cur_frm);
				return;
			}
			// The scope-only acceptance bench has no Workload Assignment app.
			const grid = view.document.createElement("div");
			grid.className = "custom-dashboard-grid";
			const row = view.document.createElement("div");
			row.className = "dashboard-percents";
			grid.append(row);
			host.replaceChildren(grid);
		});
		cy.get(".form-graph .dashboard-percents").should(([row]) =>
			expect(row).not.to.eq(previousRow)
		);
		cy.get(`.form-graph .dashboard-percents > ${card}`).should("have.length", 1);
		cy.get(`${readiness} [role="progressbar"]`).should("have.attr", "aria-valuenow", "20");
		cy.intercept({
			method: "GET",
			pathname: "/api/method/dinext_project_scope.analytics.data.project_progress",
			query: { project: fixture.empty_project },
		}).as("emptyProgress");
		cy.window().then(({ frappe }) => {
			frappe.set_route("Form", "Project", fixture.empty_project);
		});
		cy.wait("@emptyProgress").its("response.body.message").should("deep.eq", {
			count: 0,
			progress: null,
			planned_progress: null,
		});
		cy.get(readiness).should("not.exist");
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

	it("intersects a detached specification's nested requirements with the current project scope", () => {
		cy.login(fixture.actor, fixture.password);
		openReport(traceability, {
			project: fixture.project,
			specification: fixture.detached_specification,
		});
		rowLink(`${fixture.title} working`)
			.closest(".ag-row")
			.should("have.class", "dinext-scope-context-row");
		rowLink(`${fixture.title} analyzed child`)
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		rowLink(`${fixture.title} result`).should("be.visible");
		rowLink(`${fixture.title} outside scope`).should("not.exist");
		rowLink(`${fixture.title} unlinked`).should("not.exist");
		cy.request({
			url: "/api/method/frappe.desk.query_report.run",
			qs: {
				report_name: traceability,
				filters: JSON.stringify({
					project: fixture.project,
					specification: fixture.hidden_specification,
				}),
			},
			failOnStatusCode: false,
		}).then(({ status, body }) => {
			expect(status).to.eq(403);
			expect(body.exc_type).to.eq("PermissionError");
		});
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
		openReport(traceability, { project: fixture.project });
		rowLink(`${fixture.title} result`).first().click();
		cy.location("pathname").should("eq", `/app/project-deliverable/${fixture.result}`);
	});

	it("refreshes ancestor progress and overdue styling after saving changed work", () => {
		cy.login(fixture.actor, fixture.password);
		const filters = { project: fixture.project };
		openReport(traceability, filters);
		rowLink(`${fixture.title} result`)
			.first()
			.closest(".ag-row")
			.find(".dinext-scope-state-cell--red")
			.should("contain.text", "20%");

		cy.call("frappe.client.set_value", {
			doctype: "Task",
			name: fixture.work,
			fieldname: {
				progress: 65,
				custom_planned_end_date: fixture.later_planned_end,
			},
		});
		cy.reload();
		reportShown(traceability, filters);
		rowLink(`${fixture.title} result`)
			.first()
			.closest(".ag-row")
			.should("contain.text", "65%")
			.find(".dinext-scope-state-cell--red")
			.should("not.exist");
		rowLink(`${fixture.title} result`)
			.first()
			.closest(".ag-cell")
			.find(".dinext-table-tree-toggle")
			.click();
		rowLink(`${fixture.title} shared component`)
			.first()
			.closest(".ag-row")
			.should("contain.text", "65%")
			.find(".dinext-scope-state-cell--red")
			.should("not.exist");

		cy.call("frappe.client.set_value", {
			doctype: "Task",
			name: fixture.work,
			fieldname: { progress: 20, custom_planned_end_date: fixture.planned_end },
		});
	});

	it("shows RACI roles, same-name participants and multiple colors", () => {
		openReport(responsibility, { project: fixture.project });
		cy.contains(`${table} .ag-header-group-text`, exact(fixture.title)).should("be.visible");
		cy.contains(`${table} .ag-header-group-text`, exact(`${fixture.title} secondary`)).should(
			"be.visible"
		);
		cy.get(`${table} .ag-header-cell .avatar[title$="Contact · ${fixture.contact})"]`)
			.should("be.visible")
			.find(".standard-image")
			.should("exist");
		cy.get(`${table} .ag-header-cell .avatar[title$="User · ${fixture.actor})"] img`)
			.should("be.visible")
			.and(($image) => expect($image[0].naturalWidth).to.be.greaterThan(0));
		cy.contains(`${table} .ag-header-group-text`, exact(fixture.title))
			.closest(".ag-header-group-cell")
			.should("have.attr", "aria-colspan", "2");
		cy.get(`${table} .ag-cell[col-id="deliverable_type"]`)
			.first()
			.should("have.css", "text-align", "center");
		cy.get(`${table} [data-toolbar-custom-id="scope-export"] button`)
			.should(($button) => expect($button.text().trim()).to.eq("Excel"))
			.find("svg use")
			.should(($icon) => expect($icon.attr("href")).to.contain("download"));
		assignmentRow(`${fixture.title} peer`)
			.find(`[title="${fixture.title} reviewer"]`)
			.should("not.exist");
		assignmentRow(`${fixture.title} result`).within(() => {
			cy.get(`[title="${fixture.title} contributor"]`)
				.first()
				.should("have.css", "background-color", "rgb(44, 124, 112)");
			cy.get(`[title="${fixture.title} reviewer"]`).should(
				"have.css",
				"background-color",
				"rgb(120, 44, 196)"
			);
		});
		assignmentRow(`${fixture.title} shared component`)
			.find(".dinext-scope-badge")
			.should(($badges) => {
				expect([...$badges].map((badge) => badge.textContent)).to.have.members([
					"I",
					"A",
					"V",
				]);
				const boxes = [...$badges].map((badge) => badge.getBoundingClientRect());
				expect(new Set(boxes.map((box) => box.top)).size).to.eq(1);
				const cell = $badges[0].closest(".ag-cell").getBoundingClientRect();
				expect(Math.max(...boxes.map((box) => box.right))).to.be.lessThan(cell.right);
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
			responsibility: [`${fixture.title} secondary`],
			responsible_type: "User",
			responsible: fixture.actor,
		};
		openReport(responsibility, filters);
		assignmentRow(`${fixture.title} result`)
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

	it("uses all matrix filters in one row and keeps multi-value filtering in fullscreen", () => {
		openReport(responsibility, { project: fixture.project });
		rowLink(`${fixture.title} result`).should("be.visible");
		cy.get(".page-form:visible > .frappe-control").should(($fields) => {
			expect($fields).to.have.length(7);
			const tops = [...$fields].map((field) => field.getBoundingClientRect().top);
			expect(new Set(tops).size).to.eq(1);
		});

		cy.get('.page-form:visible select[data-fieldname="responsible_type"] option').should(
			($options) => {
				expect([...$options].map((option) => option.value)).to.deep.equal([
					"",
					"User",
					"Contact",
				]);
				expect($options[0].textContent.trim()).to.eq("");
			}
		);

		const label = '.ag-pinned-left-header .ag-header-cell[col-id="label"]';
		cy.get(`${table} ${label}`).should("be.visible");
		cy.get(`${table} .ag-header-cell[col-id^="assignment_"]`).should(($headers) => {
			expect($headers.length).to.be.at.least(2);
			const widths = [...$headers].map((header) => header.getBoundingClientRect().width);
			expect(new Set(widths).size).to.eq(1);
			expect(widths[0]).to.be.within(100, 110);
		});

		clickFullscreenControl("Fullscreen");
		cy.document().should((doc) => {
			const shell = doc.fullscreenElement;
			expect(shell).to.exist;
			const grid = shell.querySelector(".dinext-scope-raci-table .ag-root-wrapper");
			expect(grid).to.exist;
			expect(
				shell.getBoundingClientRect().bottom - grid.getBoundingClientRect().bottom
			).to.be.within(0, 4);
			expect(shell.scrollHeight - shell.clientHeight).to.be.at.most(1);
		});
		cy.get(`${table} ${label}`).should("be.visible");
		const picker = '.page-form:visible .multiselect-list[data-fieldname="responsibility"]';
		const toggle = `${picker} [data-toggle="dropdown"]`;
		cy.intercept("GET", "**/api/method/frappe.desk.query_report.run?*").as("matrixFilter");
		cy.get(toggle).click();
		cy.get(`${picker} .dropdown-input-wrapper input`).type(fixture.title);
		function option(code) {
			return cy.get(`${picker} .selectable-item[data-value="${encodeURIComponent(code)}"]`);
		}
		option(`${fixture.title} secondary`)
			.should(($option) => {
				const element = $option[0];
				const { x, y, width, height } = element.getBoundingClientRect();
				expect(
					element.contains(
						element.ownerDocument.elementFromPoint(x + width / 2, y + height / 2)
					)
				).to.eq(true);
			})
			.click();
		cy.wait("@matrixFilter")
			.its("response.body.message.result")
			.should((rows) => {
				expect(rows.map((row) => row.document).filter(Boolean)).to.deep.equal([
					fixture.result,
				]);
			});
		option(fixture.title).click();
		cy.wait("@matrixFilter");
		cy.get(toggle).click();
		rowLink(`${fixture.title} peer`).should("be.visible");
		cy.document().should((doc) => expect(doc.fullscreenElement).to.exist);
		reportShown(responsibility, {
			responsibility: [`${fixture.title} secondary`, fixture.title],
		});
		downloadExcel("project_responsibility_matrix", {
			project: fixture.project,
			responsibility: [`${fixture.title} secondary`, fixture.title],
		});
		cy.window().then((win) =>
			win.frappe.query_report.set_filter_value("responsible_type", "Contact")
		);
		cy.window().then((win) =>
			win.frappe.query_report.set_filter_value("responsibility", [
				`${fixture.title} secondary`,
			])
		);
		cy.contains("No records match the filters.").should("be.visible");
		cy.document().should((doc) => expect(doc.fullscreenElement).to.exist);
		cy.get(toggle).click();
		cy.get(`${picker} .clear-selections`).click();
		cy.wait("@matrixFilter");
		cy.get(toggle).click();
		rowLink(`${fixture.title} result`).should("be.visible");
		const category = '.page-form:visible .frappe-control[data-fieldname="category"]';
		cy.get(`${category} input`).type(fixture.title);
		cy.get(`${category} [role="listbox"]`).should(($list) => {
			const list = $list[0];
			const field = list.closest(".frappe-control").querySelector("input");
			const menu = list.getBoundingClientRect();
			const input = field.getBoundingClientRect();
			expect(menu.top - input.bottom).to.be.within(-1, 8);
			expect(Math.abs(menu.left - input.left)).to.be.at.most(2);
			const option = [...list.querySelectorAll('[role="option"]')].find(
				(candidate) => candidate.textContent.trim() === fixture.title
			);
			expect(option).to.exist;
			const { x, y, width, height } = option.getBoundingClientRect();
			expect(
				option.contains(list.ownerDocument.elementFromPoint(x + width / 2, y + height / 2))
			).to.eq(true);
		});
		cy.contains(`${category} [role="option"]`, exact(fixture.title)).click();
		cy.wait("@matrixFilter");
		reportShown(responsibility, { category: fixture.title });
		cy.get(`${table} button[title="Exit fullscreen"]`).click();
		cy.document().should((doc) => expect(doc.fullscreenElement).to.be.null);
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

	it("exports the overdue report with the project's server-side filter", () => {
		openReport(deliverables, { project: fixture.project, overdue: 1 });
		rowLink(`${fixture.title} result`).should("be.visible");
		rowLink(`${fixture.title} hidden deliverable`).should("not.exist");
		downloadExcel("project_deliverable_register", { project: fixture.project, overdue: 1 });
	});

	it("filters review dates, exports the constraint register and opens the project row", () => {
		openReport(constraints, { project: fixture.project, review_due: 1 });
		rowLink(`${fixture.title} assumption`).should("be.visible");
		downloadExcel("project_constraint_register", { project: fixture.project, review_due: 1 });
		rowLink(`${fixture.title} assumption`).click();
		cy.location("pathname").should("eq", `/app/project/${fixture.project}`);
		cy.get('[data-fieldname="project_constraints"] .grid-row-open:visible').should(
			"contain.text",
			`${fixture.title} assumption`
		);
	});

	it("shows and exports the recorded assumption verification alongside its planned date", () => {
		cy.viewport(1440, 900);
		const filters = { project: fixture.project, verification_status: "Confirmed" };
		openReport(constraints, filters);
		rowLink(`${fixture.title} verified supplier capacity`).should("be.visible");
		rowLink(`${fixture.title} assumption`).should("not.exist");
		cy.get(`${table} .ag-root-wrapper[grid-id]`).then(([grid]) => {
			const api = grid.ownerDocument.defaultView.agGrid.getGridApi(
				grid.getAttribute("grid-id")
			);
			api.ensureColumnVisible("verified_at", "end");
		});
		cy.get(`${table} [col-id="review_date"].ag-header-cell`)
			.should("be.visible")
			.and("contain.text", "Planned review date");
		cy.get(`${table} [col-id="verified_at"].ag-header-cell`)
			.should("be.visible")
			.and("contain.text", "Verified At");
		cy.get(`${table} [col-id="verification_note"].ag-cell`)
			.should("be.visible")
			.and("have.text", fixture.assumption_verification_note);
		cy.get(`${table} [col-id="verification_note"].ag-cell [title]`).should(
			"have.attr",
			"title",
			fixture.assumption_verification_note
		);
		cy.window().then(({ frappe }) => {
			cy.get(`${table} [col-id="review_date"].ag-cell`)
				.should("be.visible")
				.and("have.text", frappe.datetime.str_to_user(fixture.assumption_review_date));
			cy.get(`${table} [col-id="verified_at"].ag-cell`)
				.should("be.visible")
				.and("have.text", frappe.datetime.str_to_user(fixture.assumption_verified_at));
		});
		downloadExcel("project_constraint_register", filters);
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
		const exportButtons = `${table} [data-toolbar-custom-id="scope-export"] button`;
		cy.get(exportButtons).should("have.length", 1);
		clickFullscreenControl("Fullscreen");
		cy.document().should((document) => {
			expect(document.fullscreenElement?.classList.contains("dinext-scope-report-page")).to
				.be.true;
		});
		rowLink(`${fixture.title} result`).should(($link) => {
			const element = $link[0];
			const bounds = element.getBoundingClientRect();
			const hit = element.ownerDocument.elementFromPoint(
				bounds.left + Math.min(5, bounds.width / 2),
				bounds.top + bounds.height / 2
			);
			expect(element.contains(hit), "result link inside the fullscreen viewport").to.be.true;
		});
		cy.get(exportButtons).should("have.length", 1);
		clickFullscreenControl("Exit fullscreen");
		cy.document().should((document) => expect(document.fullscreenElement).to.eq(null));
		cy.get(exportButtons).should("have.length", 1);
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
		rowLink(`${fixture.title} rollout change`).should("be.visible");
		rowLink(`${fixture.title} hidden change`).should("not.exist");
		cy.contains(`${table} .ag-header-cell-text`, exact(`${fixture.title} hidden`)).should(
			"not.exist"
		);
		cy.contains(`${table} .ag-header-cell-text`, exact(`${fixture.title} secondary`)).should(
			"exist"
		);
		cy.contains(`${table} button`, "Download Excel").should("be.visible");
		cy.request({ url: exportMethod, qs: { report_name: impact }, encoding: "binary" }).then(
			(response) => {
				expect(response.status).to.eq(200);
				expect(response.body.slice(0, 2)).to.eq("PK");
			}
		);
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
