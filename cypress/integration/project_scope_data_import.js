import { linkOption } from "../support/link_options";

describe("Project scope Data Import", () => {
	const field = '.frappe-control[data-fieldname="reference_doctype"]';

	it("offers the five scope document types in the native importer", () => {
		cy.login();
		cy.openDesk("/app/data-import");
		cy.window().then((window) => {
			window.frappe.new_doc("Data Import");
		});
		cy.window().its("cur_frm.doc.doctype").should("eq", "Data Import");

		for (const doctype of [
			"Project Requirement",
			"Project Requirement Specification",
			"Project Requirement Specification Template",
			"Project Deliverable",
			"Project Change Request",
		]) {
			cy.get(`${field} input`).filter(":visible").clear().type(doctype);
			linkOption(field, doctype).click();
			cy.window().its("cur_frm.doc.reference_doctype").should("eq", doctype);
		}
	});
});
