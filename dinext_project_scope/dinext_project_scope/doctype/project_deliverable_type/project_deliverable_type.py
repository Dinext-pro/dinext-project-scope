# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from frappe.model.document import Document

from dinext_project_scope.deliverable_structure import WORK_FILTERS, validate_type_definition


class ProjectDeliverableType(Document):
	def before_import(self):
		if frappe.flags.in_fixtures and (
			configured_icon := frappe.db.get_value(self.doctype, self.name, "icon")
		):
			self.icon = configured_icon

	def _validate_links(self):
		for row in self.elements:
			row.filter_doctype = WORK_FILTERS.get(row.element_type)
		super()._validate_links()

	def validate(self):
		validate_type_definition(self)
