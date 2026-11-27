# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from dinext_common.workflow_approval.api import apply_workflow
from dinext_common.workflow_approval.engine import WorkflowDomainRollbackError
from dinext_common.workflow_approval.scenarios.service import workflow_context
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope import requirement_approval, requirements
from dinext_project_scope.analytics import reports
from dinext_project_scope.project_scope import create_project_requirement
from dinext_project_scope.tests.project_fixture import make_goal, make_project


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
		specification = self.make_specification([])
		other = self.make_project().name
		for doc in (requirement, specification):
			with self.subTest(doctype=doc.doctype):
				doc.project = other
				with self.assertRaises(frappe.ValidationError):
					doc.save()
				self.assertEqual(doc.reload().project, self.project.name)

	def test_scope_version_contains_previous_value_new_value_and_editor(self):
		from frappe.core.doctype.version.version import Version

		scope_type = frappe.get_doc(doctype="Project Scope Type", enabled=1).insert(
			set_name=f"Scope version {frappe.generate_hash(length=10)}"
		)
		row = self.project.append(
			"project_scopes", {"scope_title": "Initial service boundary", "scope_type": scope_type.name}
		)
		self.project.save()
		user = frappe.get_doc(
			doctype="User",
			email=f"scope-editor-{frappe.generate_hash(length=10)}@example.test",
			first_name="Scope Editor",
			send_welcome_email=0,
			roles=[{"role": "Projects User"}],
		).insert()
		frappe.share.add("Project", self.project.name, user=user.name, read=1, write=1)
		try:
			frappe.set_user(user.name)
			row.scope_title = "Expanded service boundary"
			self.project.save(ignore_version=False)
		finally:
			frappe.set_user("Administrator")
		name = frappe.db.get_value(
			"Version", {"ref_doctype": "Project", "docname": self.project.name, "owner": user.name}, "name"
		)
		self.assertTrue(name)
		version: Version = frappe.get_doc("Version", name)
		changes = version.get_data()["row_changed"]
		self.assertTrue(
			any(
				change[0] == "project_scopes"
				and row.name in change[1:3]
				and ["scope_title", "Initial service boundary", "Expanded service boundary"] in change[3]
				for change in changes
			),
			changes,
		)
		self.assertTrue(version.creation)

	def test_rename_title_preserves_distinct_requirement_ids_and_specification_links(self):
		other_project = self.make_project()
		first = self.make_requirement()
		second = self.make_requirement(project=other_project.name)
		self.assertEqual(first.requirement_title, second.requirement_title)
		self.assertNotEqual(first.name, second.name)
		specification = self.make_specification([(first.doctype, first.name)])
		self.project.append(requirements.PROJECT_SPECIFICATIONS, {"specification": specification.name})
		self.project.save()
		first.requirement_title = "Revised service requirement"
		first.save()
		self.assertEqual(specification.reload().items[0].reference_name, first.name)
		self.assertIn(first.name, requirements.project_membership(self.project.name))
		self.assertEqual(second.reload().requirement_title, "Shared requirement title")

	def test_shared_goal_keeps_one_document_for_requirements_in_two_projects(self):
		other = self.make_project()
		kind = frappe.get_doc(
			doctype="Goal Type", goal_type_name=f"Service goal {frappe.generate_hash(length=10)}"
		).insert()
		project_names = {self.project.name, other.name}
		goal = make_goal("Reduce first response time", kind.name, "Administrator", sorted(project_names))
		self.assertEqual({row.project for row in goal.reload().goal_projects}, project_names)
		for project in (self.project, other):
			doc = self.make_requirement(project=project.name, goals=[{"goal": goal.name}])
			self.assertEqual(doc.reload().goals[0].goal, goal.name)
			self.assertEqual(requirements.related_documents(doc.name)["goals"][0]["name"], goal.name)

	def test_existing_deliverable_link_survives_removal_from_scope(self):
		requirement = self.make_requirement()
		self.project.append(requirements.PROJECT_REQUIREMENTS, {"project_requirement": requirement.name})
		self.project.save()
		label = f"Historical result {frappe.generate_hash(length=10)}"
		kind = frappe.get_doc(doctype="Project Deliverable Type", enabled=1).insert(set_name=label)
		category = frappe.get_doc(doctype="Project Deliverable Category", enabled=1).insert(set_name=label)

		def make_deliverable(title):
			return frappe.get_doc(
				doctype="Project Deliverable",
				title=title,
				project=self.project.name,
				deliverable_type=kind.name,
				category=category.name,
				deliverable_requirements=[{"project_requirement": requirement.name}],
			)

		result = make_deliverable("Previously linked result").insert()
		self.project.set(requirements.PROJECT_REQUIREMENTS, [])
		self.project.save()
		self.assertNotIn(requirement.name, requirements.project_membership(self.project.name))
		self.assertEqual(result.reload().deliverable_requirements[0].project_requirement, requirement.name)
		self.assertFalse(requirements.related_documents(requirement.name)["in_scope"])
		with self.assertRaises(frappe.ValidationError):
			make_deliverable("New result outside scope").insert()

	def test_requirement_cannot_be_completed_before_assigned_responsible(self):
		requirement = self.make_requirement(responsible=None)
		requirement.status = "Done"
		with self.assertRaises(frappe.PermissionError):
			requirement.save()
		self.assertEqual(requirement.reload().status, "New")

	def test_project_rows_return_typed_profiles_for_legacy_links(self):
		image = "/files/test-requirement-author.png"
		frappe.db.set_value("Contact", self.contact, "image", image)
		name = create_project_requirement(
			self.project.name, "Legacy participants", self.kind, self.contact, "Administrator"
		)
		frappe.db.set_value("Project Requirement", name, {"author_type": None, "responsible_type": None})
		[row] = requirements.project_rows(self.project.name)
		self.assertEqual(
			(row["name"], row["author"], row["responsible"]), (name, self.contact, "Administrator")
		)
		self.assertEqual((row["author_type"], row["responsible_type"]), ("Contact", "User"))
		self.assertEqual(row["author_profile"]["doctype"], "Contact")
		self.assertEqual(row["author_profile"]["name"], self.contact)
		self.assertEqual(row["author_profile"]["image"], image)
		self.assertEqual(row["responsible_profile"]["doctype"], "User")
		doc = frappe.get_doc("Project Requirement", name)
		doc.requirement_title = "Existing requirement edited through Desk"
		self.assertEqual((doc.save().author_type, doc.responsible_type), ("Contact", "User"))

	def test_create_requirement_with_user_author_and_contact_responsible(self):
		name = create_project_requirement(
			self.project.name,
			"Typed participants",
			self.kind,
			"Administrator",
			self.contact,
			author_type="User",
			responsible_type="Contact",
		)
		[entry] = requirements.project_rows(self.project.name)
		self.assertEqual(entry["name"], name)
		self.assertEqual((entry["author_type"], entry["author"]), ("User", "Administrator"))
		self.assertEqual((entry["responsible_type"], entry["responsible"]), ("Contact", self.contact))

	def test_traceability_filters_distinguish_user_and_contact_with_same_identifier(self):
		identity = f"scope-participant-{frappe.generate_hash(length=8)}@example.test"
		frappe.get_doc(
			doctype="User", first_name="Traceability user", email=identity, send_welcome_email=0
		).insert()
		frappe.get_doc(doctype="Contact", first_name="Traceability contact").insert(set_name=identity)
		contact_requirement = create_project_requirement(
			self.project.name, "Contact author", self.kind, identity
		)
		user_requirement = create_project_requirement(
			self.project.name, "User author", self.kind, identity, author_type="User"
		)
		filters = {"project": self.project.name, "author": identity}
		_, legacy_rows = reports.dataset(reports.TRACEABILITY, filters)
		_, typed_rows = reports.dataset(reports.TRACEABILITY, {**filters, "author_type": "User"})
		self.assertEqual([row["document"] for row in legacy_rows], [contact_requirement])
		self.assertEqual([row["document"] for row in typed_rows], [user_requirement])
		self.assertEqual(
			reports.reference_query(
				"User",
				identity,
				"name",
				0,
				20,
				{"project": self.project.name, "context": "requirement", "participant_field": "author"},
			),
			[(identity, "Traceability user")],
		)

	def test_requirement_rejects_an_unrelated_participant_type(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_requirement(author_type="Project", author=self.contact, responsible=None)

	def test_inactive_user_cannot_be_selected_as_author_or_responsible(self):
		user = frappe.get_doc(
			doctype="User",
			first_name="Inactive requirement participant",
			email=f"scope-inactive-{frappe.generate_hash(length=8)}@example.test",
			enabled=0,
			send_welcome_email=0,
		).insert()
		for field in ("author", "responsible"):
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.make_requirement(**{f"{field}_type": "User", field: user.name})

	def test_done_uses_the_linked_account_and_keeps_the_saved_contact_assignment(self):
		doc = self.make_requirement(responsible_type="Contact", responsible=self.contact)
		self.assertFalse(requirements.can_mark_done(doc.name))
		doc.status = "Done"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

		frappe.db.set_value("Contact", self.contact, "user", "Administrator")
		self.assertTrue(requirements.can_mark_done(doc.name))
		replacement = frappe.get_doc(
			doctype="Contact",
			first_name=f"Replacement requirement participant {frappe.generate_hash(length=8)}",
			user="Administrator",
		).insert()
		doc.reload()
		doc.update({"responsible": replacement.name, "status": "Done"})
		with self.assertRaises(frappe.PermissionError):
			doc.save()

		doc.reload()
		doc.status = "Done"
		self.assertEqual(doc.save().status, "Done")
		self.assertEqual(doc.reload().responsible, self.contact)

	def test_stock_requirement_workflow_uses_the_linked_responsible_account(self):
		frappe.db.set_value("Contact", self.contact, "user", "Administrator")
		doc = self.make_requirement(responsible_type="Contact", responsible=self.contact)

		self.vote(doc, "Submit for Review")
		self.vote(doc, "Approve")
		self.assertEqual(doc.status, "Approved")

	def test_template_copies_typed_participants_eligible_in_the_target_project(self):
		role = frappe.get_doc(
			doctype="Project Role",
			role_name=f"Requirement participant {frappe.generate_hash(length=8)}",
			enabled=1,
		).insert()
		self.project.append("custom_contact_list", {"contact": self.contact, "project_role": role.name})
		self.project.save()
		source = self.make_requirement(
			project=None,
			status="Template",
			author_type="User",
			author="Administrator",
			responsible_type="Contact",
			responsible=self.contact,
		)
		template = self.make_specification([(source.doctype, source.name)], template=True)
		for project, expected in (
			(self.project, ("Contact", self.contact)),
			(self.make_project(), ("User", "Administrator")),
		):
			with self.subTest(project=project.name):
				preview = requirements.preview_specification_template(project.name, template.name)
				[prepared] = preview["requirements"]
				self.assertEqual((prepared["responsible_type"], prepared["responsible"]), expected)
				result = requirements.apply_specification_template(
					project.name, template.name, frappe.generate_hash(length=32), preview["digest"]
				)
				copy = frappe.get_doc(source.doctype, result["requirements"][source.name])
				self.assertEqual((copy.author_type, copy.author), ("User", "Administrator"))
				self.assertEqual((copy.responsible_type, copy.responsible), expected)

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
		label = f"Template result {frappe.generate_hash(length=10)}"
		kind = frappe.get_doc(doctype="Project Deliverable Type", enabled=1).insert(set_name=label)
		category = frappe.get_doc(doctype="Project Deliverable Category", enabled=1).insert(set_name=label)
		result = frappe.get_doc(
			doctype="Project Deliverable",
			title=label,
			project=self.project.name,
			deliverable_type=kind.name,
			category=category.name,
			deliverable_requirements=[{"project_requirement": first_child.name}],
		).insert()
		_, first_rows = reports.dataset(reports.TRACEABILITY, {"project": self.project.name})
		_, second_rows = reports.dataset(reports.TRACEABILITY, {"project": other.name})
		first_documents = {row["document"]: row for row in first_rows}
		second_documents = {row["document"]: row for row in second_rows}
		self.assertIn(result.name, first_documents)
		self.assertEqual(first_documents[first_child.name]["status"], "Done")
		self.assertNotIn(first_child.name, second_documents)
		self.assertNotIn(result.name, second_documents)
		other_child = second_documents[second["requirements"][child_req.name]]
		self.assertEqual(other_child["status"], "New")
		self.assertEqual(other_child["status_tone"], "red")
		self.assertEqual(other_child["status_note"], "No linked deliverables in this project")

	def vote(self, doc, action, *, comment=None, request_id=None):
		result = apply_workflow(
			{"doctype": doc.doctype, "name": doc.name}, action, comment=comment, request_id=request_id
		)
		self.assertTrue(result["transitioned"], result)
		doc.reload()

	def test_requirement_edit_invalidates_all_approved_sets_and_keeps_snapshots(self):
		requirement = self.make_requirement()
		original = requirement.requirement_title
		inner = self.make_specification([(requirement.doctype, requirement.name)])
		outer = self.make_specification([(inner.doctype, inner.name)])
		for source in (inner, outer):
			self.project.append(requirements.PROJECT_SPECIFICATIONS, {"specification": source.name})
			self.vote(source, "Submit for Review")
			self.vote(source, "Approve")
		self.project.save()

		requirement.reload()
		requirement.requirement_title = "Revised after approving two sets"
		requirement.save()
		[entry] = requirements.project_rows(self.project.name)
		self.assertEqual(entry["title"], requirement.requirement_title)
		self.assertTrue(entry["approval_stale"])
		for source in (inner, outer):
			self.assertEqual(
				requirement_approval.approval_summary(source.doctype, source.name)["status"],
				"Reapproval Required",
			)
			[decision] = requirement_approval.approval_history(source.doctype, source.name)["rounds"]
			self.assertEqual(decision["decision"], "Approved")
			self.assertEqual(
				decision["snapshot"]["requirements"][requirement.name]["content"]["requirement_title"],
				original,
			)

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
