# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

"""Register this app's default Dinext Hub cards."""

from __future__ import annotations

import frappe

APP_NAME = 'dinext_project_scope'

HUB_ITEMS = (
	{
		"section": 'Scope & Governance',
		"element_type": 'DocType',
		"target": 'Project Scope',
		"label": 'Project Scope',
		"description": 'Defines project boundaries through scope items, types, descriptions, and linked records.',
		"icon": 'list',
	},
	{
		"section": 'Scope & Governance',
		"element_type": 'DocType',
		"target": 'Project Deliverable',
		"label": 'Project Deliverable',
		"description": 'Tracks deliverables by type, category, status, progress, related scope, requirements, and responsible parties.',
		"icon": 'file',
	},
	{
		"section": 'Scope & Governance',
		"element_type": 'DocType',
		"target": 'Project Change Request',
		"label": 'Project Change Request',
		"description": 'Manages submittable change requests with initiator, justification, alternatives, and linked project objects.',
		"icon": 'change',
	},
)


def register_dinext_hub_items() -> None:
	if "dinext_common" not in frappe.get_installed_apps():
		return

	try:
		from dinext_common.setup.hub_catalog import register_hub_items
	except ImportError:
		return

	register_hub_items(HUB_ITEMS, source_app=APP_NAME)
