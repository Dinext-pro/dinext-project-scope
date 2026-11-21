# Copyright (c) 2026, Dinext and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope import deliverable_structure as structure
from dinext_project_scope import deliverables
from dinext_project_scope.tests.project_fixture import make_project


class TestProjectDeliverable(FrappeTestCase):
	def setUp(self):
		project_type = f"Scope type {frappe.generate_hash(length=8)}"
		self.project_type = frappe.get_doc(doctype="Project Type", project_type=project_type).insert().name
		self.project = self.new_project()
		self.category = frappe.get_doc(
			doctype="Project Deliverable Category", name=frappe.generate_hash(length=8), enabled=1
		).insert()

	def new_project(self):
		name = f"SCOPE-TEST-{frappe.generate_hash(length=8)}"
		return make_project(name, name, self.project_type)

	def kind(self, *elements):
		return frappe.get_doc(
			doctype="Project Deliverable Type",
			name=frappe.generate_hash(length=8),
			enabled=1,
			elements=[
				{"element_key": key, "element_name": key, "element_type": doctype, **extra}
				for key, doctype, extra in elements
			],
		).insert()

	def result(self, kind, **kwargs):
		selections = {row["source_element_key"]: row for row in kwargs.pop("table_xuct", [])}
		rows = [
			{**row, **selections.get(row["source_element_key"], {})} for row in structure.from_type(kind.name)
		]
		return frappe.get_doc(
			doctype="Project Deliverable",
			title="Scope test result",
			project=self.project.name,
			deliverable_type=kind.name,
			category=self.category.name,
			table_xuct=rows,
			**kwargs,
		).insert()

	def task(self, progress, **kwargs):
		return frappe.get_doc(
			doctype="Task",
			subject="Scope test work",
			project=self.project.name,
			progress=progress,
			custom_planned_start_date="2026-11-01",
			**kwargs,
		).insert()

	def test_delete_results_checks_links_and_removes_a_selected_parent_first(self):
		kind = self.kind()
		unlinked = self.result(kind)
		child = self.result(kind)
		parent = self.result(
			self.kind(("child", "Project Deliverable", {})),
			table_xuct=[{"source_element_key": "child", "element": child.name}],
		)
		with self.assertRaises(frappe.LinkExistsError):
			deliverables.delete_project_results(self.project.name, [child.name, unlinked.name])
		self.assertTrue(frappe.db.exists("Project Deliverable", unlinked.name))
		self.assertTrue(frappe.db.exists("Project Deliverable Log", {"deliverable": unlinked.name}))

		deleted = deliverables.delete_project_results(
			self.project.name, [child.name, parent.name, unlinked.name, child.name]
		)
		self.assertEqual(set(deleted), {parent.name, child.name, unlinked.name})
		for name in deleted:
			self.assertFalse(frappe.db.exists("Project Deliverable", name))
			self.assertFalse(frappe.db.exists("Project Deliverable Log", {"deliverable": name}))

	def test_delete_results_rejects_cross_project_selection_and_read_only_access(self):
		doc = self.result(self.kind())
		foreign = self.new_project()
		with self.assertRaises(frappe.ValidationError):
			deliverables.delete_project_results(foreign.name, [doc.name])
		actor = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				deliverables.delete_project_results(self.project.name, [doc.name])
		finally:
			frappe.set_user(actor)
		self.assertTrue(frappe.db.exists("Project Deliverable", doc.name))

	def test_task_save_recalculates_shared_ancestors_without_duplicate_log(self):
		work_type = self.kind(("task", "Task", {}))
		parent_type = self.kind(("result", "Project Deliverable", {}))
		task = self.task(60, custom_planned_end_date="2026-11-07", exp_end_date="2026-11-11")
		leaf = self.result(work_type, table_xuct=[{"source_element_key": "task", "element": task.name}])
		parents = [
			self.result(parent_type, table_xuct=[{"source_element_key": "result", "element": leaf.name}])
			for _ in range(2)
		]

		task.progress = 20
		task.custom_planned_end_date = "2026-11-09"
		task.exp_end_date = "2026-11-14"
		task.save()
		for result in [*parents, leaf]:
			result.reload()
			self.assertEqual(result.progress, 20)
			self.assertEqual(str(result.planned_end_date), "2026-11-09")
			self.assertEqual(str(result.expected_end_date), "2026-11-14")
			self.assertTrue(
				frappe.db.exists(
					"Project Deliverable Log",
					{
						"deliverable": result.name,
						"source_name": task.name,
						"previous_progress": 60,
						"progress": 20,
					},
				)
			)

		counts = [
			frappe.db.count("Project Deliverable Log", {"deliverable": result.name}) for result in parents
		]
		deliverables.on_task_change(task)
		deliverables.rebuild_project(self.project.name)
		self.assertEqual(
			[frappe.db.count("Project Deliverable Log", {"deliverable": result.name}) for result in parents],
			counts,
		)

	def test_task_db_set_updates_the_result_when_a_value_returns_to_its_original_value(self):
		kind = self.kind(("work", "Task", {}))
		task = self.task(20)
		result = self.result(kind, table_xuct=[{"source_element_key": "work", "element": task.name}])
		task.db_set("progress", 30)
		self.assertEqual(result.reload().progress, 30)
		task.db_set("progress", 20)
		self.assertEqual(result.reload().progress, 20)

	def test_source_slots_survive_type_edit_until_preview_is_applied(self):
		kind = self.kind(("required", "Task", {}), ("optional", "Task", {"is_optional": 1}))
		task = self.task(40)
		result = self.result(kind, table_xuct=[{"source_element_key": "optional", "element": task.name}])
		result.table_xuct[1].element = None
		result.save()
		self.assertTrue(
			frappe.db.exists(
				"Project Deliverable Log", {"deliverable": result.name, "event_type": "Structure Changed"}
			)
		)
		self.assertEqual(len(result.table_xuct), 2)

		kind.elements[0].element_name = "New name"
		kind.save()
		result.reload()
		self.assertEqual(result.table_xuct[0].element_name, "required")
		with self.assertRaises(frappe.ValidationError):
			result.remove(result.table_xuct[0])
			result.save()

		preview = deliverables.preview_structure(result.name)
		self.assertEqual(preview["changes"][0]["before"]["element_name"], "required")
		deliverables.apply_structure(result.name, preview["deliverable_type"], preview["token"])
		self.assertEqual(result.reload().table_xuct[0].element_name, "New name")

	def test_cycle_and_cross_project_work_are_rejected(self):
		kind = self.kind(("child", "Project Deliverable", {}))
		first = self.result(kind)
		second = self.result(kind, table_xuct=[{"source_element_key": "child", "element": first.name}])
		first.table_xuct[0].element = second.name
		with self.assertRaises(frappe.ValidationError):
			first.save()

		other = self.new_project()
		foreign = frappe.get_doc(
			doctype="Project Deliverable",
			project=other.name,
			deliverable_type=kind.name,
			category=self.category.name,
			title="Foreign result",
		).insert()
		first.reload().table_xuct[0].element = foreign.name
		with self.assertRaises(frappe.ValidationError):
			first.save()

	def test_direct_edit_cannot_record_acceptance(self):
		simple = self.result(self.kind())
		simple.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			simple.save()

	def project_role(self, name=None):
		name = name or f"Scope role {frappe.generate_hash(length=8)}"
		return frappe.get_doc(doctype="Project Role", role_name=name, enabled=1).insert().name

	def user_assignment(self, responsibility, role):
		return {
			"responsibility": responsibility,
			"project_role": role,
			"responsible_type": "User",
			"responsible": "Administrator",
		}

	def team_member(self, role, **kwargs):
		return self.project.append(
			"custom_ts_details",
			{"pt_role": role, "pt_participant_type": "User", "pt_participant": "Administrator", **kwargs},
		)

	def test_single_responsibility_allows_one_person_in_multiple_roles(self):
		role = self.project_role()
		another_role = self.project_role()
		self.team_member(role)
		self.team_member(another_role)
		contact = frappe.get_doc(doctype="Contact", first_name="Administrator").insert()
		self.project.append("custom_contact_list", {"contact": contact.name, "project_role": role})
		self.project.save()
		responsibility = (
			frappe.get_doc(
				doctype="Project Deliverable Responsibility",
				name=frappe.generate_hash(length=8),
				responsibility=f"Test accountability {frappe.generate_hash(length=8)}",
				enabled=1,
				single=1,
			)
			.insert()
			.name
		)

		first = self.user_assignment(responsibility, role)
		result = self.result(
			self.kind(),
			deliverable_responsibles=[first, first, self.user_assignment(responsibility, another_role)],
		)
		self.assertEqual(len(result.deliverable_responsibles), 2)
		result.append(
			"deliverable_responsibles",
			{
				**first,
				"responsible_type": "Contact",
				"responsible": contact.name,
			},
		)
		with self.assertRaisesRegex(frappe.ValidationError, responsibility):
			result.save()

	def test_expired_participation_preserves_history_but_cannot_be_assigned_again(self):
		from frappe.utils import add_days, today

		role = self.project_role()
		member = self.team_member(role, pt_valid_from=add_days(today(), -7))
		self.project.save()
		responsibility = (
			frappe.get_doc(
				doctype="Project Deliverable Responsibility",
				name=frappe.generate_hash(length=8),
				responsibility=f"Test participation {frappe.generate_hash(length=8)}",
				enabled=1,
			)
			.insert()
			.name
		)
		assignment = self.user_assignment(responsibility, role)
		kind = self.kind()
		existing = self.result(kind, deliverable_responsibles=[assignment])

		member.pt_valid_for = add_days(today(), -1)
		self.project.save()
		existing.title = "Preserve past assignments"
		existing.save()
		details = deliverables.get_deliverable_details(existing.name)
		self.assertEqual(details["stale_assignments"], [existing.deliverable_responsibles[0].name])
		with self.assertRaises(frappe.ValidationError):
			self.result(kind, deliverable_responsibles=[assignment])

	def test_project_user_can_choose_a_participant_with_user_select_permission(self):
		import frappe.share

		# Dinext Projects replaces Frappe's standard Desk User link-select permission.
		frappe.get_doc(
			doctype="Custom DocPerm",
			parent="User",
			parenttype="DocType",
			parentfield="permissions",
			role="Projects User",
			permlevel=0,
			read=0,
			select=1,
		).insert()
		frappe.clear_cache(doctype="User")

		actor_name = f"scope-author-{frappe.generate_hash(length=8)}@example.test"
		member_name = f"scope-member-{frappe.generate_hash(length=8)}@example.test"
		for email in (actor_name, member_name):
			frappe.get_doc(
				doctype="User",
				first_name="Scope test user",
				email=email,
				send_welcome_email=0,
				user_type="System User",
				roles=[{"role": "Projects User"}],
			).insert()
		role = self.project_role()
		self.project.append(
			"custom_ts_details",
			{
				"pt_role": role,
				"pt_participant_type": "User",
				"pt_participant": member_name,
			},
		)
		self.project.save()
		responsibility = (
			frappe.get_doc(
				doctype="Project Deliverable Responsibility",
				name=frappe.generate_hash(length=8),
				responsibility=f"Selectable assignment {frappe.generate_hash(length=8)}",
				enabled=1,
			)
			.insert()
			.name
		)
		self.category.append("responsibilities", {"responsibility": responsibility, "project_role": role})
		self.category.save()
		kind = self.kind()
		for doctype, name in (
			("Project", self.project.name),
			("Project Role", role),
			(self.category.doctype, self.category.name),
			(kind.doctype, kind.name),
		):
			frappe.share.add(doctype, name, actor_name, read=1)
		previous = frappe.session.user
		frappe.set_user(actor_name)
		try:
			self.assertTrue(frappe.has_permission("User", "select", doc=member_name))
			self.assertFalse(frappe.has_permission("User", "read", doc=member_name))
			preview = deliverables.new_result_defaults(self.project.name, kind.name, self.category.name)
			self.assertEqual([row["responsible"] for row in preview["defaults"]], [member_name])
			created = self.result(kind, deliverable_responsibles=preview["defaults"])
			self.assertEqual(created.deliverable_responsibles[0].responsible, member_name)
		finally:
			frappe.set_user(previous)

	def _workflow_vote(self, doc, action, comment=None):
		from dinext_common.workflow_approval import engine

		task = frappe.db.get_value(
			"Workflow Task",
			{
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"round_status": "Open",
				"status": "Working",
				"approver": "Administrator",
			},
		)
		self.assertTrue(task, f"No open approval task for {action}")
		return engine.cast_vote(task, action=action, comment=comment)

	def test_default_acceptance_requires_a_current_project_manager(self):
		self.project.is_active = "Yes"
		self.project.save()
		doc = self.result(self.kind())
		self.assertTrue(deliverables.get_deliverable_details(doc.name)["missing_approver"])
		with self.assertRaisesRegex(frappe.ValidationError, "Assign one active user"):
			self._workflow_vote(doc, "Request Acceptance")
		self.assertEqual(doc.reload().status, "Not Started")
		self.assertFalse(doc.last_acceptance_log)

	def test_acceptance_is_separate_from_work_completion_and_can_be_reconfirmed(self):
		from dinext_common.workflow_approval.lifecycle import is_engine_enabled
		from frappe.utils import add_days, today

		if not is_engine_enabled() or not frappe.db.exists("Workflow", "Dinext Project Deliverable"):
			self.skipTest("The default Dinext deliverable Workflow is not enabled.")
		manager_role = frappe.db.get_single_value("Project Scope Settings", "project_manager_role")
		if not manager_role:
			manager_role = next(
				(
					name
					for name in ("Project Manager", "Руководитель проекта")
					if frappe.db.exists("Project Role", name)
				),
				None,
			) or self.project_role("Project Manager")
		self.team_member(manager_role)
		self.project.is_active = "Yes"
		self.project.save()
		assignments = [
			self.user_assignment(responsibility, manager_role)
			for responsibility in frappe.get_all(
				"Project Deliverable Responsibility", filters={"enabled": 1, "required": 1}, pluck="name"
			)
		]
		kind = self.kind(("main", "Task", {}), ("cancelled", "Task", {"is_optional": 1, "weight": 0}))
		finished_on = add_days(today(), -2)
		task = self.task(100, status="Completed", completed_on=finished_on)
		cancelled = self.task(0, status="Cancelled")
		doc = self.result(
			kind,
			deliverable_responsibles=assignments,
			table_xuct=[
				{"source_element_key": "main", "element": task.name},
				{"source_element_key": "cancelled", "element": cancelled.name},
			],
		)
		self._workflow_vote(doc, "Request Acceptance")
		self.assertEqual(doc.reload().status, "Acceptance")
		with self.assertRaises(frappe.ValidationError):
			self._workflow_vote(doc, "Accept Deliverable")
		doc.table_xuct[1].element = None
		doc.save()
		self._workflow_vote(doc, "Accept Deliverable")
		doc.reload()
		self.assertEqual(doc.status, "Completed")
		self.assertEqual(str(doc.actual_end_date), finished_on)
		accepted = frappe.get_doc("Project Deliverable Log", doc.last_acceptance_log)
		self.assertEqual(str(accepted.log_date).split(" ")[0], today())

		task.custom_planned_end_date = add_days(today(), 1)
		task.save()
		doc.reload()
		self.assertEqual(doc.status, "Completed")
		self.assertTrue(doc.requires_recheck)
		self.assertEqual(doc.last_acceptance_log, accepted.name)
		self._workflow_vote(doc, "Reconfirm Acceptance", "Checked the revised plan.")
		doc.reload()
		self.assertFalse(doc.requires_recheck)
		self.assertNotEqual(doc.last_acceptance_log, accepted.name)
		self.assertEqual(
			frappe.db.get_value("Project Deliverable Log", doc.last_acceptance_log, "event_type"),
			"Reconfirmed",
		)

		reconfirmed = doc.last_acceptance_log
		task.custom_planned_end_date = add_days(today(), 2)
		task.save()
		self._workflow_vote(doc, "Return to Acceptance", "Review the updated schedule.")
		doc.reload()
		self.assertEqual(doc.status, "Acceptance")
		self.assertEqual(doc.last_acceptance_log, reconfirmed)
		self.assertTrue(
			frappe.db.exists("Project Deliverable Log", {"deliverable": doc.name, "event_type": "Reopened"})
		)
