export function linkOptions(field) {
	return cy.get(`${field} .awesomplete [role="option"]:visible`);
}

export function optionValue(element) {
	return element.ownerDocument.defaultView.$(element).data("item.autocomplete")?.value;
}

export function linkOption(field, value) {
	const matching = (options) => [...options].filter((element) => optionValue(element) === value);
	return linkOptions(field)
		.should((options) => expect(matching(options), value).to.have.length(1))
		.then((options) => cy.wrap(matching(options)[0], { log: false }));
}
