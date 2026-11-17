from dinext_project_scope.analytics.reports import OVERVIEW, execute_report


def execute(filters=None):
	return execute_report(OVERVIEW, filters)
