# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from dinext_project_scope.access import lock_project
from dinext_project_scope.changes import validate_change


class ProjectChangeRequest(Document):
	def load_doc_before_save(self, *, raise_exception=False):
		if self.project:
			lock_project(self.project)
		return super().load_doc_before_save(raise_exception=raise_exception)

	def validate(self):
		validate_change(self)

	def before_update_after_submit(self):
		validate_change(self)

	def before_cancel(self):
		validate_change(self, cancelling=True)
