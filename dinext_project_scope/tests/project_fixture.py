"""Create a project compatible with both core and finance-enabled test sites."""

import frappe
from frappe.utils import add_days, today


def make_project(title, name, project_type=None):
	if not project_type:
		project_type = frappe.get_doc(doctype="Project Type", project_type=title).insert().name
	project = frappe.get_doc(doctype="Project", project_name=title, project_type=project_type)
	if project.meta.has_field("custom_payment_scheme"):
		project.custom_payment_scheme = frappe.db.get_value(
			"Project Payment Scheme", {}, "name", order_by="name asc"
		)
	return project.insert(set_name=name)


def project_user_roles():
	"""Use the normal Desk baseline when this stack includes Dinext_User."""
	roles = [{"role": "Projects User"}]
	if frappe.db.exists("Role", "Dinext_User"):
		roles.append({"role": "Dinext_User"})
	return roles


def goal_project_parameter(projects):
	return dict(
		code="delivery_projects",
		param_type="Link List",
		link_doctype="Project",
		value_list="\n".join(projects),
	)


def make_goal(subject, goal_type, owner, projects):
	return frappe.get_doc(
		doctype="Goal",
		goal_type=goal_type,
		subject=subject,
		goal_owner=owner,
		priority="Medium",
		exp_start_date=today(),
		exp_end_date=add_days(today(), 30),
		progress_method="Manual",
		is_group=1,
		parameters=[goal_project_parameter(projects)],
	).insert()
