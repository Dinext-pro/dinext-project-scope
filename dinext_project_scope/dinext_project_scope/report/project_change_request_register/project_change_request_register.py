from dinext_project_scope.analytics.reports import CHANGE_REGISTER, execute_report


def execute(filters=None):
	return execute_report(CHANGE_REGISTER, filters)
