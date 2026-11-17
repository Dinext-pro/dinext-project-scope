# Copyright (c) 2026, Dinext and contributors
# See license.txt

import frappe
from dinext_common.workflow_approval import engine
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from dinext_project_scope.changes import approval_history
from dinext_project_scope.tests.project_fixture import make_project


class TestProjectChangeRequest(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		tag = f"SCOPE-TEST-{frappe.generate_hash(length=10)}"
		self.project = make_project(tag, tag)
		role = (
			frappe.db.get_single_value("Project Scope Settings", "project_manager_role") or "Project Manager"
		)
		if not frappe.db.exists("Project Role", role):
			frappe.get_doc(doctype="Project Role", role_name=role, enabled=1).insert(set_name=role)
		self.project.append(
			"custom_ts_details",
			{"pt_role": role, "pt_participant_type": "User", "pt_participant": "Administrator"},
		)
		self.project.save()
		self.contact = (
			frappe.get_doc(doctype="Contact", first_name=f"Test contact {frappe.generate_hash(length=10)}")
			.insert()
			.name
		)
		self.kind = (
			frappe.get_doc(doctype="Project Change Relation Type", enabled=1, reqd_estimation=1)
			.insert(set_name=frappe.generate_hash(length=10))
			.name
		)

	def change(self):
		return frappe.get_doc(
			doctype="Project Change Request",
			title="Scope test change",
			project=self.project.name,
			initiator=self.contact,
			description="Adjust scope",
			implementation_responsible="Administrator",
			change_relations=[
				{"type": self.kind, "direction": "target", "level": "Strong", "estimation": "2\u20134 days"},
				{"type": self.kind, "direction": "target", "level": "Weak", "estimation": "1 day"},
			],
		).insert()

	def vote(self, change, action, comment=None):
		name = frappe.db.get_value(
			"Workflow Task",
			{
				"reference_doctype": change.doctype,
				"reference_name": change.name,
				"status": "Working",
				"round_status": "Open",
				"approver": "Administrator",
			},
			"name",
		)
		self.assertTrue(name, f"No open task for {action}")
		result = engine.cast_vote(name, action=action, comment=comment)
		self.assertTrue(result["transitioned"], result)
		change.reload()

	def test_approved_estimate_is_preserved_through_implementation(self):
		change = self.change()
		self.assertEqual(change.status, "Draft")
		self.vote(change, "Submit for Review")
		self.assertEqual(change.status, "In Review")
		change.change_relations[0].estimation = "6\u20138 days"
		with self.assertRaises(frappe.ValidationError):
			change.save()
		change.reload()
		self.vote(change, "Approve")
		self.assertEqual(change.docstatus, 1)
		self.assertEqual(change.change_relations[0].estimation, "2\u20134 days")
		self.assertEqual([row.decision for row in approval_history(change.name)], ["Approved"])
		task = frappe.get_doc(doctype="Task", subject="Scope update", project=self.project.name).insert()
		change.implementation_date = today()
		change.implementation_note = "Changed the project task."
		change.append("implementation_items", {"reference_doctype": "Task", "reference_name": task.name})
		change.save()
		self.vote(change, "Mark Implemented")
		self.assertEqual(change.status, "Implemented")
		self.assertEqual(change.implemented_by, "Administrator")
		self.assertEqual(change.implementation_items[0].reference_name, task.name)
		self.vote(change, "Cancel", comment="Replaced by a revised request.")
		self.assertEqual(change.docstatus, 2)
		self.assertEqual(change.implemented_by, "Administrator")

		amendment = frappe.copy_doc(change, ignore_no_copy=False)
		amendment.amended_from = change.name
		amendment.docstatus = 0
		amendment.insert()
		self.assertEqual(amendment.status, "Draft")
		self.assertEqual(amendment.change_relations[0].estimation, "2\u20134 days")
		self.assertFalse(amendment.implementation_items)
		self.assertFalse(amendment.implementation_date)
		self.assertEqual([row.decision for row in approval_history(change.name)], ["Approved"])

	def test_rejected_request_has_separate_history_when_resubmitted(self):
		change = self.change()
		self.vote(change, "Submit for Review")
		self.vote(change, "Reject", comment="Review the estimate.")
		self.vote(change, "Return to Draft")
		change.change_relations[0].estimation = "1\u20132 days"
		change.save()
		self.vote(change, "Submit for Review")
		rounds = approval_history(change.name)
		self.assertEqual([row.decision for row in rounds], ["In Review", "Rejected"])
