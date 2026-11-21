Cypress.Commands.add("login", (email, password) => {
	if (!email) {
		email = "Administrator";
	}
	if (!password) {
		password = Cypress.env("adminPassword");
	}
	// Leave the old Desk page so its pending requests cannot restore its session cookie.
	cy.intercept("GET", "/__scope-test-sign-in", {
		headers: { "Content-Type": "text/html; charset=utf-8" },
		body: "<!doctype html><title>Scope test sign-in</title>",
	});
	cy.visit("/__scope-test-sign-in", { log: false });
	cy.clearCookies({ log: false });
	return cy
		.request({
			url: "/api/method/login",
			method: "POST",
			body: { usr: email, pwd: password },
			log: false,
		})
		.then(() => cy.request("/api/method/frappe.auth.get_logged_user"))
		.its("body.message")
		.should("eq", email);
});

Cypress.Commands.add("call", (method, args, { timeout } = {}) => {
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf_token) => {
			expect(csrf_token).to.be.a("string").and.not.eq("None");
			return cy
				.request({
					url: `/api/method/${method}`,
					method: "POST",
					body: args || {},
					timeout,
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": csrf_token,
					},
				})
				.then((res) => {
					expect(res.status).to.eq(200);
					return res;
				});
		});
});

Cypress.Commands.add("openDesk", (path) => {
	cy.visit(path || "/app");
	cy.window().its("frappe.csrf_token").should("be.a", "string").and("not.eq", "None");
	cy.window().its("frappe.session.user").should("not.eq", "Guest");
});
