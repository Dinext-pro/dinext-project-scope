# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from frappe.utils.nestedset import NestedSet

from dinext_project_scope import requirement_approval, requirements


class ProjectRequirement(requirements.GraphDocument, NestedSet):
	protected_links = "goals"

	def get_invalid_links(self, is_submittable=False):
		requirements.set_requirement_participant_types(self)
		return super().get_invalid_links(is_submittable=is_submittable)

	def validate(self):
		requirements.validate_requirement(self)
		requirement_approval.apply_transition(self)

	def on_trash(self):
		requirements.lock_source(self, wait=False)
		super().on_trash()
