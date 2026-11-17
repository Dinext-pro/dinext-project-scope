# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.deliverable_templates import validate_template


class ProjectDeliverablesTemplate(Document):
	def validate(self):
		validate_template(self)
