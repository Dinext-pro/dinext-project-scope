from dinext_project_scope.analytics.reports import TRACEABILITY, execute_report


def execute(filters=None):
	return execute_report(TRACEABILITY, filters)
