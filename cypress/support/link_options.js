export function linkOptions(field) {
	return cy.get(`${field} .awesomplete [role="option"]:visible`);
}

export function optionValue(element) {
	return element.ownerDocument.defaultView.$(element).data("item.autocomplete")?.value;
}

Cypress.Commands.addQuery("matchingScopeLinkOption", function (value) {
	return (options) => options.filter((index, element) => optionValue(element) === value);
});

export function linkOption(field, value) {
	return linkOptions(field).matchingScopeLinkOption(value).should("have.length", 1);
}
