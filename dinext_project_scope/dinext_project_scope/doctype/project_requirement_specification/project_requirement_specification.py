# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from dinext_project_scope import requirement_approval, requirements


class ProjectRequirementSpecification(requirements.GraphDocument, Document):
	protected_links = "items"

	def validate(self):
		requirements.validate_specification(self)
		requirement_approval.apply_transition(self)

	def on_trash(self):
		requirements.lock_source(self, wait=False)
