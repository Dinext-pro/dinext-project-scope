# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ProjectDeliverableLog(Document):
	def validate(self):
		if not self.is_new() or not self.flags.in_deliverable_calculation:
			frappe.throw(_("Project result events are recorded by the server."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Project result events are recorded by the server."), frappe.PermissionError)
