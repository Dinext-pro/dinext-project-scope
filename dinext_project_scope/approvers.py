"""Resolve the project-role assignee for the supplied default Workflows."""

import frappe
from frappe import _

from dinext_project_scope.access import has_project_access, project_participants


def current_manager(project, *, current=False):
	if not project:
		return None
	configured_role = frappe.db.get_single_value("Project Scope Settings", "project_manager_role")
	roles = {configured_role} if configured_role else {"Project Manager", "Руководитель проекта"}
	users = {
		row["name"] for row in project_participants(project, "User", current=current) if row["role"] in roles
	}
	if len(users) != 1:
		return None
	actor = users.pop()
	return actor if has_project_access(project, user=actor) else None


def require_manager(project):
	actor = current_manager(project, current=True)
	if not actor:
		raise frappe.ValidationError(
			_("Assign one active user to the project manager role before submitting for approval.")
		)
	return actor
