# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.catalogs import preserve_fixture_settings
from dinext_project_scope.deliverable_responsibility import validate_category


class ProjectDeliverableCategory(Document):
	before_import = preserve_fixture_settings

	def validate(self):
		validate_category(self)
