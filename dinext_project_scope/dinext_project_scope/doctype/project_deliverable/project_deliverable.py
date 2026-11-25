# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from frappe import permissions
from frappe.model.document import Document

from dinext_project_scope.access import project_document_permission
from dinext_project_scope.deliverable_structure import element_doctype
from dinext_project_scope.deliverables import (
	lock_source_projects,
	on_deliverable_update,
	validate_deliverable,
)


class ProjectDeliverable(Document):
	def has_permission(self, permtype="read", *, debug=False, user=None) -> bool:
		if (
			not self.flags.ignore_permissions
			and not hasattr(permissions, "has_final_permission")
			and project_document_permission(self, permtype, user) is False
		):
			return False
		return super().has_permission(permtype, debug=debug, user=user)

	def load_doc_before_save(self, *, raise_exception=False):
		lock_source_projects(self)
		return super().load_doc_before_save(raise_exception=raise_exception)

	def _validate_links(self):
		for row in self.table_xuct:
			row.element_doctype = element_doctype(row)
		super()._validate_links()

	def validate(self):
		validate_deliverable(self)

	def on_update(self):
		on_deliverable_update(self)
