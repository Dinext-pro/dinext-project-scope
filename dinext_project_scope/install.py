# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

"""Install / migrate hooks for Dinext Project Scope."""

import frappe
from frappe import _

from dinext_project_scope.setup.dinext_hub import register_dinext_hub_items
from dinext_project_scope.setup.workflows import ensure_default_workflows


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
	register_dinext_hub_items()
	ensure_default_workflows()
