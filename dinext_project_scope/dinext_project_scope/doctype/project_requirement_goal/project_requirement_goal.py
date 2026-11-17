# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from dinext_project_scope.requirements import RequirementChild


class ProjectRequirementGoal(RequirementChild):
	link_doctype = "Goal"
	link_field = "goal"
