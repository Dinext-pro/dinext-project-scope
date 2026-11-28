import { rowLink, table, useReportFixture } from "../support/scope_reports";

const host = '[data-fieldname="custom_scope_results_html"]';
const resultsEndpoint = "/api/method/dinext_project_scope.analytics.data.project_results";
const reportEndpoint = "/api/method/frappe.desk.query_report.run";
const reportName = "Project Responsibility Matrix";
const category = "Проектирование";
const deliverableType = "Документ";
const migrationType = `/app/project-deliverable-type/${encodeURIComponent("Миграция данных")}`;
const elementFields =
	'[data-fieldname="elements"] .grid-body .grid-static-col[data-fieldname="element_name"] .static-area';

const locales = [
	{ language: "en", actor: "actor", categoryLabel: "Solution Design", typeLabel: "Document" },
	{
		language: "ru",
		actor: "russian_actor",
		categoryLabel: category,
		typeLabel: deliverableType,
	},
];

function resultFilter(field) {
	return cy.get(`${host} select[data-fieldname="${field}"]`);
}

function requestParameters(request) {
	const body =
		typeof request.body === "string"
			? Object.fromEntries(new URLSearchParams(request.body))
			: request.body;
	return { ...request.query, ...body };
}

function filterValues(value) {
	return typeof value === "string" ? JSON.parse(value) : value || {};
}

describe("Project scope catalog localization", () => {
	const fixture = useReportFixture();
	let localizedResult;
	const title = () => `${fixture.title} localized result`;

	before(() => {
		cy.call("frappe.client.insert", {
			doc: {
				doctype: "Project Deliverable",
				title: title(),
				project: fixture.project,
				category,
				deliverable_type: deliverableType,
			},
		}).then(({ body }) => {
			localizedResult = body.message.name;
		});
	});

	for (const { language, actor, categoryLabel, typeLabel } of locales) {
		it(`shows shipped type element names in ${language} and preserves the stored text`, () => {
			cy.login(fixture[actor], fixture.password);
			cy.visit(migrationType);
			cy.window().its("frappe.boot.lang").should("eq", language);
			const original = ["Шаблон загрузки", "Тестовый прогон", "Продуктивная миграция"];
			const labels =
				language === "en"
					? ["Data import template", "Trial run", "Production migration"]
					: original;
			cy.get(elementFields).should(($cells) => {
				expect([...$cells].map((cell) => cell.textContent.trim())).to.deep.eq(labels);
			});
			cy.window().should(({ cur_frm: form }) => {
				expect(form.doc.elements.map(({ element_name }) => element_name)).to.deep.eq(
					original
				);
			});

			if (language === "en") {
				cy.login();
				cy.visit(migrationType);
				cy.get('[data-fieldname="elements"] .grid-body .btn-open-row').first().click();
				cy.get(
					'[data-fieldname="elements"] input[data-fieldname="element_name"]:visible'
				).should("have.value", original[0]);
			}
		});

		it(`localizes the result card and tree structure in ${language}`, () => {
			cy.login(fixture[actor], fixture.password);
			const stored = ["Разработка", "Согласование / Приемка", "Отработка замечаний"];
			const labels =
				language === "en"
					? ["Drafting", "Review / acceptance", "Addressing feedback"]
					: stored;
			cy.visit(`/app/project-deliverable/${localizedResult}`);
			cy.window().its("frappe.boot.lang").should("eq", language);
			cy.get(
				'[data-fieldname="table_xuct"] .grid-body [data-fieldname="element_name"] .static-area'
			).should(($cells) => {
				expect([...$cells].map((cell) => cell.textContent.trim())).to.deep.eq(labels);
			});
			cy.window().should(({ cur_frm }) => {
				expect(cur_frm.doc.table_xuct.map(({ element_name }) => element_name)).to.deep.eq(
					stored
				);
			});
			cy.visit(`/app/project/${fixture.project}`);
			cy.get('button[data-fieldname="custom_результаты"]').click();
			resultFilter("deliverable_type")
				.select(typeLabel)
				.should("have.value", deliverableType);
			cy.contains(`${host} .dinext-scope-link`, title()).should("be.visible");
			for (const label of labels.slice(0, 2))
				cy.contains(`${host} .dinext-scope-label`, label).should("be.visible");
		});

		it(`shows the localized RACI abbreviation and keeps the original responsibility filter in ${language}`, () => {
			cy.login(fixture[actor], fixture.password);
			const responsibility = ["О"];
			cy.intercept({ pathname: reportEndpoint }, (request) => {
				const { report_name, filters } = requestParameters(request);
				const selected = filterValues(filters);
				if (
					report_name === reportName &&
					selected.project === fixture.project &&
					selected.responsibility?.length
				)
					request.alias = "localizedResponsibility";
			});
			const query = new URLSearchParams({ project: fixture.project });
			cy.visit(`/app/query-report/${encodeURIComponent(reportName)}?${query}`);
			rowLink(`${fixture.title} shared component`).should("be.visible");
			cy.window().then(({ frappe }) => {
				return frappe.query_report.set_filter_value("responsibility", responsibility);
			});
			cy.wait("@localizedResponsibility").then(({ request, response }) => {
				expect(response?.statusCode).to.eq(200);
				expect(filterValues(requestParameters(request).filters).responsibility).to.deep.eq(
					responsibility
				);
			});
			rowLink(`${fixture.title} shared component`)
				.closest(".ag-row")
				.invoke("attr", "row-id")
				.then((id) => {
					const abbreviation = language === "en" ? "A" : "О";
					const label = language === "en" ? "Accountable" : "Ответственный";
					cy.get(`${table} .ag-row[row-id="${id}"] .dinext-scope-badge`)
						.should("have.length", 1)
						.and("have.text", abbreviation)
						.and("have.attr", "aria-label", `${abbreviation} · ${label}`);
				});
		});

		it(`shows localized Results filters and sends the reference IDs in ${language}`, () => {
			cy.login(fixture[actor], fixture.password);
			cy.visit(`/app/project/${fixture.project}`);
			cy.window().its("frappe.boot.lang").should("eq", language);
			cy.get('button[data-fieldname="custom_результаты"]').click();

			resultFilter("category")
				.find("option")
				.should(($options) => {
					const options = [...$options];
					expect(options.find(({ value }) => value === category)?.textContent).to.eq(
						categoryLabel
					);
					expect(
						options.find(({ value }) => value === fixture.title)?.textContent
					).to.eq(fixture.title);
				});
			resultFilter("deliverable_type")
				.find("option")
				.should(($options) => {
					expect(
						[...$options].find(({ value }) => value === deliverableType)?.textContent
					).to.eq(typeLabel);
				});

			cy.intercept({ method: "GET", pathname: resultsEndpoint }, (request) => {
				const { project, filters } = request.query;
				const selected = filterValues(filters);
				if (
					project === fixture.project &&
					selected.category &&
					selected.deliverable_type
				) {
					request.alias = "localizedResults";
				}
			});
			resultFilter("category").select(categoryLabel).should("have.value", category);
			resultFilter("deliverable_type")
				.select(typeLabel)
				.should("have.value", deliverableType);
			cy.wait("@localizedResults").then(({ request, response }) => {
				expect(response?.statusCode).to.eq(200);
				expect(filterValues(request.query.filters)).to.include({
					category,
					deliverable_type: deliverableType,
				});
			});
			cy.contains(`${host} .dinext-scope-link`, title()).should("be.visible");
		});

		it(`shows the localized RACI type for the same reference IDs in ${language}`, () => {
			cy.login(fixture[actor], fixture.password);
			cy.intercept({ pathname: reportEndpoint }, (request) => {
				const { report_name, filters } = requestParameters(request);
				const selected = filterValues(filters);
				if (
					report_name === reportName &&
					selected.project === fixture.project &&
					selected.category
				) {
					request.alias = "localizedRaci";
				}
			});
			const filters = {
				project: fixture.project,
				category,
				deliverable_type: deliverableType,
			};
			cy.visit(
				`/app/query-report/${encodeURIComponent(reportName)}?${new URLSearchParams(
					filters
				)}`
			);
			cy.window().should((win) => {
				expect(win.frappe?.boot?.lang).to.eq(language);
				expect(win.frappe?.query_report?.report_name).to.eq(reportName);
			});
			cy.wait("@localizedRaci").then(({ request, response }) => {
				expect(response?.statusCode).to.eq(200);
				expect(filterValues(requestParameters(request).filters)).to.include(filters);
			});
			rowLink(title())
				.closest(".ag-row")
				.invoke("attr", "row-id")
				.then((id) => {
					cy.get(`${table} .ag-row[row-id="${id}"] [col-id="deliverable_type"]`)
						.should("be.visible")
						.and("have.text", typeLabel);
				});
		});
	}
});

describe("Project scope catalog descriptions", () => {
	it("shows the English description and opens the stored text for editing", () => {
		cy.login();
		cy.visit(`/app/project-deliverable-type/${encodeURIComponent("Миграция данных")}`);
		cy.get('.frappe-control[data-fieldname="description"] .control-value:visible')
			.should("contain.text", "Preparation and execution of data loading")
			.and("not.contain.text", "ExampleCustomer08");
		cy.get('button[title="Edit description"]:visible').click();
		cy.get('.frappe-control[data-fieldname="description"] textarea:visible').should(
			"have.value",
			"ExampleCustomer08 загрузки и миграции данных в тест и продуктив."
		);
	});
});
