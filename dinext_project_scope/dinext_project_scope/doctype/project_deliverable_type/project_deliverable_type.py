# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.catalogs import preserve_fixture_settings
from dinext_project_scope.deliverable_structure import WORK_FILTERS, validate_type_definition


class ProjectDeliverableType(Document):
	before_import = preserve_fixture_settings

	def _validate_links(self):
		for row in self.elements:
			row.filter_doctype = WORK_FILTERS.get(row.element_type)
		super()._validate_links()

	def validate(self):
		validate_type_definition(self)
