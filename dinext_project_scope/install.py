# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

"""Install / migrate hooks for Dinext Project Scope."""

import frappe
from frappe import _

from dinext_project_scope.setup.dinext_hub import register_dinext_hub_items
from dinext_project_scope.setup.workflows import ensure_default_workflows


_SCOPE_TAB = "custom_объем"
_SCOPE_FIELD_ORDER = (
	"custom_scope_items_section",
	"project_scopes",
	"custom_project_scope",
	"custom_scope_requirements_section",
	"custom_project_requirements",
	"custom_project_requirement_specifications",
	"custom_scope_requirements_html",
	"custom_scope_constraints_section",
	"project_constraints",
	"custom_constraints_and_assumptions",
	"custom_scope_changes_section",
	"custom_project_change_requests",
	"custom_scope_changes_html",
)
_SCOPE_SECTIONS = (
	"custom_scope_items_section",
	"custom_scope_requirements_section",
	"custom_scope_constraints_section",
	"custom_scope_changes_section",
)


def scope_field_order(order: list[str]) -> list[str]:
	if all(section in order for section in _SCOPE_SECTIONS):
		return order

	order = [field for field in order if field not in _SCOPE_FIELD_ORDER]
	if _SCOPE_TAB in order:
		start = order.index(_SCOPE_TAB) + 1
		order[start:start] = _SCOPE_FIELD_ORDER
	return order


def ensure_scope_field_order() -> None:
	"""Add the native sections to an existing Project layout on their first installation."""
	name = frappe.db.get_value("Property Setter", {"doc_type": "Project", "property": "field_order"})
	if not name:
		return

	setter = frappe.get_doc("Property Setter", name)
	if not isinstance(order := frappe.parse_json(setter.value), list):
		return
	if (expanded := scope_field_order(order)) != order:
		setter.value = frappe.as_json(expanded)
		setter.save(ignore_permissions=True)


def before_install() -> None:
	for app, doctype in (("Dinext Common", "Workflow Process"), ("Dinext Goals", "Goal")):
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(_("Install a version of {0} that includes {1}.").format(app, doctype))
	goal = frappe.get_meta("Goal")
	if not all(goal.has_field(field) for field in ("subject", "goal_projects")):
		frappe.throw(_("Use the Goal DocType from Dinext Goals to link project requirements."))


def after_install() -> None:
	register_dinext_hub_items()
	ensure_default_workflows()


def after_migrate() -> None:
	before_install()
	ensure_scope_field_order()
	register_dinext_hub_items()
	ensure_default_workflows()


def seed_default_result_tree_responsibility() -> None:
	from dinext_project_scope.analytics.data import ACCOUNTABLE_CODE, RESPONSIBILITY

	settings = frappe.get_single("Project Scope Settings")
	if not settings.result_tree_responsibilities and frappe.db.exists(RESPONSIBILITY, ACCOUNTABLE_CODE):
		settings.append("result_tree_responsibilities", {"responsibility": ACCOUNTABLE_CODE})
		settings.save(ignore_permissions=True)
