import { linkOption } from "../support/link_options";

describe("Project scope Data Import", () => {
	const page = ".page-container:visible";
	const field = `${page} .frappe-control[data-fieldname="reference_doctype"]:visible`;

	it("offers the five scope document types in the native importer", () => {
		cy.login();
		cy.openDesk("/app/data-import");
		cy.get(`${page} .page-actions .primary-action:visible`).click();
		cy.location("pathname").should("match", /^\/app\/data-import\/new-data-import-/);
		cy.get(field).find("input:visible").should("be.visible");

		for (const doctype of [
			"Project Requirement",
			"Project Requirement Specification",
			"Project Requirement Specification Template",
			"Project Deliverable",
			"Project Change Request",
		]) {
			cy.get(field).find("input:visible").clear().type(doctype);
			linkOption(field, doctype).click();
			cy.window().its("cur_frm.doc.reference_doctype").should("eq", doctype);
		}
	});
});
