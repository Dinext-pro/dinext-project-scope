from dinext_project_scope.analytics.reports import IMPACT, execute_report


def execute(filters=None):
	return execute_report(IMPACT, filters)
