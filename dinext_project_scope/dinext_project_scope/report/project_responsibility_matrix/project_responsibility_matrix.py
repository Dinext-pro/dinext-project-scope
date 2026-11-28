from dinext_project_scope.analytics.reports import RESPONSIBILITY, execute_report


def execute(filters=None):
	return execute_report(RESPONSIBILITY, filters)
