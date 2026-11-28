# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from dinext_project_scope.catalogs import preserve_fixture_settings

class ProjectChangeRelationType(Document):
	before_import = preserve_fixture_settings
