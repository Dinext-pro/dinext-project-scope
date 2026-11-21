module.exports = {
	defaultCommandTimeout: 20000,
	pageLoadTimeout: 120000,
	requestTimeout: 30000,
	video: false,
	viewportWidth: 1440,
	viewportHeight: 960,
	e2e: {
		baseUrl: "http://localhost:8000",
		specPattern: "cypress/integration/**/*.js",
		supportFile: "cypress/support/e2e.js",
		includeShadowDom: true,
	},
};
