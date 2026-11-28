from dinext_project_scope.analytics.reports import DELIVERABLE_REGISTER, execute_report


def execute(filters=None):
	return execute_report(DELIVERABLE_REGISTER, filters)
