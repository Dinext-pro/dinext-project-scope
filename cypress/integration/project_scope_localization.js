import { rowLink, table, useReportFixture } from "../support/scope_reports";

const host = '[data-fieldname="custom_scope_results_html"]';
const resultsEndpoint = "/api/method/dinext_project_scope.analytics.data.project_results";
const reportEndpoint = "/api/method/frappe.desk.query_report.run";
const reportName = "Project Responsibility Matrix";
const category = "Проектирование";
const deliverableType = "Документ";

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
		});
	});

	for (const { language, actor, categoryLabel, typeLabel } of locales) {
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
