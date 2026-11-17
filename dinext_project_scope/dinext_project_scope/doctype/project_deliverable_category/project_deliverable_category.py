# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.deliverable_responsibility import validate_category


class ProjectDeliverableCategory(Document):
	def validate(self):
		validate_category(self)
