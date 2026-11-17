# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe.model.document import Document

from dinext_project_scope.deliverables import (
	lock_source_projects,
	on_deliverable_update,
	validate_deliverable,
)


class ProjectDeliverable(Document):
	def load_doc_before_save(self, *, raise_exception=False):
		lock_source_projects(self)
		return super().load_doc_before_save(raise_exception=raise_exception)

	def validate(self):
		validate_deliverable(self)

	def on_update(self):
		on_deliverable_update(self)
