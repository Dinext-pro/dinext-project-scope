from dinext_project_scope.analytics.reports import CONSTRAINT_REGISTER, execute_report


def execute(filters=None):
	return execute_report(CONSTRAINT_REGISTER, filters)
