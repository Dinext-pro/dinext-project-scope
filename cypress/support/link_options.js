export function linkOptions(field) {
	return cy.get(`${field} .awesomplete [role="option"]:visible`);
}

export function optionValue(element) {
	return element.ownerDocument.defaultView.$(element).data("item.autocomplete")?.value;
}

export function linkOption(field, value) {
	return linkOptions(field)
		.filter((_, element) => optionValue(element) === value)
		.should("have.length", 1);
}
