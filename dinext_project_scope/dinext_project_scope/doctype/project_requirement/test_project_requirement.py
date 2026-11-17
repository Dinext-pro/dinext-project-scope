# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from dinext_common.workflow_approval.api import apply_workflow
from dinext_common.workflow_approval.engine import WorkflowDomainRollbackError
from dinext_common.workflow_approval.scenarios.service import workflow_context
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope import requirement_approval, requirements
from dinext_project_scope.tests.project_fixture import make_project


class TestProjectRequirement(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.project = self.make_project()
		self.contact = (
			frappe.get_doc(
				doctype="Contact", first_name=f"Requirements test {frappe.generate_hash(length=10)}"
			)
			.insert()
			.name
		)
		self.kind = (
			frappe.get_doc(doctype="Requirement Kind", enabled=1)
			.insert(set_name=f"Requirements test {frappe.generate_hash(length=10)}")
			.name
		)

	def make_project(self):
		suffix = frappe.generate_hash(length=10)
		return make_project(f"Requirements {suffix}", f"TEST-SCOPE-REQ-{suffix}")

	def make_requirement(self, **values):
		defaults = {
			"requirement_title": "Shared requirement title",
			"author": self.contact,
			"kind": self.kind,
			"requirement_importance": "Must Have",
			"project": self.project.name,
			"responsible": frappe.session.user,
		}
		defaults.update(values)
		return frappe.get_doc(doctype="Project Requirement", **defaults).insert()

	def make_specification(self, items, *, template=False):
		doctype = requirements.SPEC_TEMPLATE if template else requirements.SPECIFICATION
		return frappe.get_doc(
			{
				"doctype": doctype,
				"title": "Requirement set",
				"project": None if template else self.project.name,
				"author": self.contact,
				"responsible": frappe.session.user,
				"items": [{"reference_doctype": doctype, "reference_name": name} for doctype, name in items],
			}
		).insert()

	def test_project_membership_keeps_paths_and_resolves_visible_parent(self):
		parent = self.make_requirement(is_group=1)
		child = self.make_requirement(parent_project_requirement=parent.name)
		child_entry = ("Project Requirement", child.name)
		nested = self.make_specification([child_entry])
		root = self.make_specification([child_entry, (nested.doctype, nested.name)])
		self.project.append("custom_project_requirement_specifications", {"specification": root.name})
		self.project.save()
		self.assertEqual(
			requirements.project_membership(self.project.name),
			{
				child.name: [[root.name], [root.name, nested.name]],
			},
		)
		self.assertIsNone(requirements.project_rows(self.project.name)[0]["parent"])
		self.project.append("custom_project_requirements", {"project_requirement": parent.name})
		self.project.save()
		self.assertEqual(
			[row["parent"] for row in requirements.project_rows(self.project.name)], [None, parent.name]
		)

	def test_transitive_specification_cycle_preserves_existing_composition(self):
		inner = self.make_specification([])
		outer = self.make_specification([(inner.doctype, inner.name)])
		inner.append("items", {"reference_doctype": outer.doctype, "reference_name": outer.name})
		with self.assertRaises(frappe.ValidationError):
			inner.save()
		self.assertFalse(inner.reload().items)

	def test_composition_edit_cannot_move_another_specifications_item(self):
		requirement = self.make_requirement()
		original = self.make_specification([(requirement.doctype, requirement.name)])
		other = self.make_specification([])
		other.append("items", original.items[0].as_dict())
		with self.assertRaises(frappe.ValidationError):
			other.save()
		self.assertFalse(other.reload().items)
		self.assertEqual(original.reload().items[0].reference_name, requirement.name)

	def test_standalone_composition_row_cannot_bypass_parent_validation(self):
		requirement = self.make_requirement()
		specification = self.make_specification([(requirement.doctype, requirement.name)])
		row = frappe.get_doc(specification.items[0].doctype, specification.items[0].name)
		row.reference_doctype = specification.doctype
		row.reference_name = specification.name
		with self.assertRaises(frappe.ValidationError):
			row.save()
		self.assertEqual(specification.reload().items[0].reference_name, requirement.name)

	def test_project_change_is_rejected_even_without_membership(self):
		requirement = self.make_requirement()
		requirement.project = self.make_project().name
		with self.assertRaises(frappe.ValidationError):
			requirement.save()

	def test_requirement_cannot_be_completed_before_assigned_responsible(self):
		requirement = self.make_requirement(responsible=None)
		requirement.status = "Done"
		with self.assertRaises(frappe.PermissionError):
			requirement.save()
		self.assertEqual(requirement.reload().status, "New")

	def test_template_is_copied_once_per_request_and_once_per_distinct_project(self):
		root_req = self.make_requirement(status="Template", project=None, is_group=1)
		child_req = self.make_requirement(
			status="Template", project=None, parent_project_requirement=root_req.name
		)
		inner = self.make_specification([("Project Requirement", child_req.name)], template=True)
		root = self.make_specification(
			[
				("Project Requirement", root_req.name),
				(inner.doctype, inner.name),
				("Project Requirement", child_req.name),
			],
			template=True,
		)
		other = self.make_project()
		preview = requirements.preview_specification_template(self.project.name, root.name)
		key = frappe.generate_hash(length=32)
		first = requirements.apply_specification_template(
			self.project.name, root.name, key, preview["digest"]
		)
		self.assertEqual(
			first,
			requirements.apply_specification_template(self.project.name, root.name, key, preview["digest"]),
		)
		other_preview = requirements.preview_specification_template(other.name, root.name)
		second = requirements.apply_specification_template(
			other.name, root.name, frappe.generate_hash(length=32), other_preview["digest"]
		)
		self.assertNotEqual(first["requirements"], second["requirements"])
		self.assertEqual(len(first["requirements"]), 2)
		first_child = frappe.get_doc("Project Requirement", first["requirements"][child_req.name])
		self.assertEqual(first_child.parent_project_requirement, first["requirements"][root_req.name])
		self.assertEqual(first_child.template_source, child_req.name)
		first_child.status = "Done"
		first_child.save()
		self.assertEqual(
			frappe.db.get_value("Project Requirement", second["requirements"][child_req.name], "status"),
			"New",
		)
		self.assertEqual(child_req.reload().status, "Template")

	def vote(self, doc, action, *, comment=None, request_id=None):
		result = apply_workflow(
			{"doctype": doc.doctype, "name": doc.name}, action, comment=comment, request_id=request_id
		)
		self.assertTrue(result["transitioned"], result)
		doc.reload()

	def test_submission_without_an_approver_preserves_draft(self):
		doc = self.make_requirement(responsible=None)
		workflow = workflow_context(doc)[1]
		savepoint = "requirements_no_eligible_approver"
		frappe.db.savepoint(savepoint)
		try:
			for transition in workflow.transitions:
				if transition.state == "In Review" and transition.next_state == "Approved":
					frappe.db.set_value("Workflow Transition", transition.name, "condition", "False")
			frappe.clear_document_cache("Workflow", workflow.name)
			with self.assertRaises(WorkflowDomainRollbackError):
				self.vote(doc, "Submit for Review")
			self.assertEqual(doc.reload().workflow_state, "Draft")
			self.assertFalse(
				frappe.db.exists(
					"Project Scope Approval", {"reference_doctype": doc.doctype, "reference_name": doc.name}
				)
			)
		finally:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_document_cache("Workflow", workflow.name)

	def test_workflow_covers_shared_requirement_once_and_keeps_done(self):
		new = self.make_requirement()
		done = self.make_requirement()
		done.status = "Done"
		done.save()
		new_link = (new.doctype, new.name)
		inner = self.make_specification([new_link, (done.doctype, done.name)])
		outer = self.make_specification([new_link, (inner.doctype, inner.name)])
		self.vote(outer, "Submit for Review")
		vote_key = frappe.generate_hash(length=24)
		self.vote(outer, "Approve", request_id=vote_key)
		self.vote(outer, "Approve", request_id=vote_key)

		approval_name = frappe.db.get_value(
			"Project Scope Approval",
			{
				"reference_doctype": outer.doctype,
				"reference_name": outer.name,
				"decision": "Approved",
			},
			"name",
		)
		approval = frappe.get_doc("Project Scope Approval", approval_name)
		self.assertCountEqual([row.requirement for row in approval.requirements], [new.name, done.name])
		self.assertEqual(new.reload().status, "Approved")
		self.assertEqual(done.reload().status, "Done")
		self.assertEqual(inner.reload().workflow_state, "Draft")

	def test_reused_specification_name_does_not_inherit_the_previous_review(self):
		previous = self.make_specification([])
		self.vote(previous, "Submit for Review")
		old_round = frappe.db.get_value(
			"Project Scope Approval", {"reference_name": previous.name, "decision": "In Review"}, "name"
		)
		requirement = self.make_requirement()
		fresh = self.make_specification([(requirement.doctype, requirement.name)])
		frappe.db.set_value("Project Scope Approval", old_round, "reference_name", fresh.name)

		self.vote(fresh, "Submit for Review")
		self.assertEqual(
			requirement_approval.approval_summary(fresh.doctype, fresh.name)["status"], "In Review"
		)
		self.vote(fresh, "Approve")
		self.assertEqual(requirement.reload().status, "Approved")
		self.assertEqual(frappe.db.get_value("Project Scope Approval", old_round, "decision"), "In Review")
		history = requirement_approval.approval_history(fresh.doctype, fresh.name)["rounds"]
		self.assertEqual([row["decision"] for row in history], ["Approved"])

	def test_nested_change_requires_a_new_submission_and_preserves_independent_approval(self):
		requirement = self.make_requirement()
		self.vote(requirement, "Submit for Review")
		self.vote(requirement, "Approve")
		inner = self.make_specification([(requirement.doctype, requirement.name)])
		outer = self.make_specification([(inner.doctype, inner.name)])
		self.vote(outer, "Submit for Review")
		inner.description = "Changed after submission"
		inner.save()

		with self.assertRaises(WorkflowDomainRollbackError):
			self.vote(outer, "Approve")
		self.assertEqual(outer.reload().workflow_state, "In Review")
		self.assertEqual(
			requirement_approval.approval_summary(outer.doctype, outer.name)["status"], "Reapproval Required"
		)
		self.assertEqual(
			requirement_approval.approval_summary(requirement.doctype, requirement.name)["status"], "Approved"
		)
		self.vote(outer, "Withdraw Review", comment="A nested specification changed.")
		self.vote(outer, "Submit for Review")
		self.vote(outer, "Approve")

		history = requirement_approval.approval_history(outer.doctype, outer.name)["rounds"]
		self.assertEqual([row["decision"] for row in history], ["Approved", "Superseded"])
		self.assertEqual(
			history[0]["snapshot"]["specifications"][inner.name]["content"]["description"],
			"Changed after submission",
		)
		self.assertEqual(history[1]["snapshot"]["specifications"][inner.name]["content"]["description"], "")
		inner.description = "Changed again after approval"
		inner.save()
		self.assertEqual(
			requirement_approval.approval_summary(outer.doctype, outer.name)["status"], "Reapproval Required"
		)
		self.assertEqual(
			requirement_approval.approval_summary(requirement.doctype, requirement.name)["status"], "Approved"
		)
