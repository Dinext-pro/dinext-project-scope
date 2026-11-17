# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.deliverable_structure import validate_type_definition


class ProjectDeliverableType(Document):
	def validate(self):
		validate_type_definition(self)
