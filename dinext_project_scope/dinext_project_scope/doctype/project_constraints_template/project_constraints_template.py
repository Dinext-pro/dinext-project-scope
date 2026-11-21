# Copyright (c) 2026, Dinext and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from dinext_project_scope.project_scope import validate_constraint
from dinext_project_scope.requirements import validate_child_rows


class ProjectConstraintsTemplate(Document):
	def validate(self):
		validate_child_rows(self, "project_constraints", self.get_doc_before_save())
		for row in self.project_constraints or []:
			validate_constraint(row)
