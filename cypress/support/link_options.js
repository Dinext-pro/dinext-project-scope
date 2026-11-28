export function linkOptions(field) {
	const option = '[role="option"]:visible';
	return cy.get(
		`${field} .awesomplete ${option}, ${field} .dinext-scope-link-options ${option}`
	);
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
