# Copyright (c) 2026, Dinext and Contributors
# See license.txt

from contextlib import redirect_stdout
from csv import writer
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import frappe
import frappe.share
from frappe.core.doctype.data_import.importer import INSERT, UPDATE, Importer
from frappe.tests.utils import FrappeTestCase

from dinext_project_scope.deliverable_structure import snapshot
from dinext_project_scope.tests.project_fixture import make_project

SCOPE_DOCTYPES = (
	"Project Requirement",
	"Project Requirement Specification",
	"Project Requirement Specification Template",
	"Project Deliverable",
	"Project Change Request",
)


class TestScopeDataImport(FrappeTestCase):
	def setUp(self):
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.tag = f"SCOPE-IMPORT-TEST-{frappe.generate_hash(length=10)}"

	def make_user(self, key, *roles):
		return (
			frappe.get_doc(
				doctype="User",
				email=f"{self.tag.lower()}-{key}@example.test",
				first_name="Scope Import Test",
				language="en",
				send_welcome_email=0,
				roles=[{"role": role} for role in roles],
			)
			.insert()
			.name
		)

	def test_native_data_import_requires_system_manager_permission(self):
		manager = self.make_user("manager", "System Manager", "Projects Manager")
		participant = self.make_user("participant", "Projects User")
		for doctype in SCOPE_DOCTYPES:
			with self.subTest(doctype=doctype):
				frappe.set_user(manager)
				frappe.get_doc(
					doctype="Data Import",
					reference_doctype=doctype,
					import_type="Insert New Records",
					mute_emails=1,
				).validate_doctype()
				frappe.set_user(participant)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_doc(doctype="Data Import", reference_doctype=doctype).validate_doctype()

	def prepare_project(self):
		self.manager = self.make_user("manager", "System Manager", "Projects Manager")
		self.project = self.make_import_project(self.tag)
		self.author = frappe.get_doc(doctype="Contact", first_name=self.tag).insert().name
		frappe.share.add("Contact", self.author, user=self.manager, read=1, notify=0)
		self.kind = frappe.get_doc(doctype="Requirement Kind", enabled=1).insert(set_name=self.tag).name

	def make_import_project(self, name):
		project = make_project(name, name).name
		frappe.share.add("Project", project, user=self.manager, read=1, write=1, notify=0)
		for permission in ("read", "write"):
			self.assertTrue(frappe.has_permission("Project", permission, doc=project, user=self.manager))
		return project

	def requirement_fields(self, **overrides):
		return {
			"requirement_title": "Provide a delivery schedule",
			"project": self.project,
			"author": self.author,
			"kind": self.kind,
			"requirement_importance": "Must Have",
			"responsible": self.manager,
			**overrides,
		}

	def specification_fields(self, **overrides):
		return {
			"title": "Delivery requirements",
			"author": self.author,
			"responsible": self.manager,
			**overrides,
		}

	def deliverable_fields(self):
		category = frappe.get_doc(doctype="Project Deliverable Category", name=self.tag, enabled=1).insert()
		result_type = frappe.get_doc(
			doctype="Project Deliverable Type",
			name=self.tag,
			enabled=1,
			elements=[
				{"element_key": "prepare", "element_name": "Prepare", "element_type": "Task"},
				{"element_key": "review", "element_name": "Review", "element_type": "Task"},
			],
		).insert()
		return {
			"title": "Delivery schedule",
			"project": self.project,
			"category": category.name,
			"deliverable_type": result_type.name,
		}

	def change_fields(self):
		return {
			"title": "Update the delivery schedule",
			"project": self.project,
			"initiator": self.author,
			"description": "Allow a separate review of the delivery dates.",
		}

	def import_row(self, doctype, values, *, error=None):
		# Seed the job as Administrator so site-specific access to the Data Import form is independent.
		data_import = frappe.get_doc(
			doctype="Data Import",
			reference_doctype=doctype,
			import_type=UPDATE if "name" in values else INSERT,
			mute_emails=1,
			payload_count=1,
		).insert()
		user = frappe.session.user
		frappe.set_user(self.manager)
		try:
			data_import.validate_doctype()
			with TemporaryDirectory() as directory:
				csv_path = Path(directory) / "scope.csv"
				with csv_path.open("w", encoding="utf-8", newline="") as stream:
					csv = writer(stream)
					csv.writerow(values)
					csv.writerow(values.values())
				importer = Importer(doctype, data_import=data_import, file_path=str(csv_path), console=True)
				self.run_in_transaction(importer)
			log = frappe.db.get_value(
				"Data Import Log",
				{"data_import": data_import.name},
				["success", "docname", "exception"],
				as_dict=True,
			)
			self.assertIsNotNone(log, importer.import_file.get_warnings())
			if error:
				self.assertFalse(log.success, log)
				self.assertIn(error, log.exception)
				return None
			self.assertTrue(log.success, log)
			return frappe.get_doc(doctype, log.docname)
		finally:
			frappe.set_user(user)

	def run_in_transaction(self, importer):
		# Keep the core importer's per-row transaction boundaries inside the test transaction.
		db = frappe.db
		rollback = db.rollback
		point = "scope_data_import_row"
		db.savepoint(point)
		with (
			patch.object(db, "commit", side_effect=lambda: db.savepoint(point)),
			patch.object(db, "rollback", side_effect=lambda save_point=None: rollback(save_point=save_point or point)),
			patch.dict(frappe.flags),
			redirect_stdout(StringIO()),
		):
			importer.import_data()

	def test_import_creates_and_updates_the_five_scope_document_types(self):
		self.prepare_project()
		requirement = self.import_row("Project Requirement", self.requirement_fields())
		template_requirement = self.import_row(
			"Project Requirement", self.requirement_fields(project=None, status="Template")
		)
		specification = self.import_row(
			"Project Requirement Specification",
			self.specification_fields(
				project=self.project,
				**{"items.reference_doctype": requirement.doctype, "items.reference_name": requirement.name},
			),
		)
		template = self.import_row(
			"Project Requirement Specification Template",
			self.specification_fields(
				**{
					"items.reference_doctype": template_requirement.doctype,
					"items.reference_name": template_requirement.name,
				}
			),
		)
		deliverable = self.import_row("Project Deliverable", self.deliverable_fields())
		change = self.import_row("Project Change Request", self.change_fields())
		self.assertEqual(specification.items[0].reference_name, requirement.name)
		self.assertEqual(template.items[0].reference_name, template_requirement.name)
		self.assertEqual([row.source_element_key for row in deliverable.table_xuct], ["prepare", "review"])
		self.assertEqual(change.status, "Draft")
		for doc in (requirement, specification, template, deliverable, change):
			with self.subTest(doctype=doc.doctype):
				fieldname = "requirement_title" if doc.doctype == "Project Requirement" else "title"
				updated = self.import_row(
					doc.doctype, {"name": doc.name, fieldname: "Revised delivery schedule"}
				)
				self.assertEqual(updated.get(fieldname), "Revised delivery schedule")

	def test_import_rejects_project_reassignment_and_foreign_composition(self):
		self.prepare_project()
		other = self.make_import_project(f"{self.tag}-OTHER")
		requirement = self.import_row("Project Requirement", self.requirement_fields())
		specification = self.import_row(
			"Project Requirement Specification", self.specification_fields(project=self.project)
		)
		for doc in (requirement, specification):
			with self.subTest(doctype=doc.doctype):
				self.import_row(
					doc.doctype,
					{"name": doc.name, "project": other},
					error="The project of a saved document cannot be changed.",
				)
				self.assertEqual(doc.reload().project, self.project)
		foreign = self.import_row("Project Requirement", self.requirement_fields(project=other))
		self.import_row(
			specification.doctype,
			{
				"name": specification.name,
				"items.reference_doctype": foreign.doctype,
				"items.reference_name": foreign.name,
			},
			error="Every working requirement and specification must belong to the same project.",
		)
		self.assertFalse(specification.reload().items)

	def test_import_rejects_composition_cycles_and_working_requirements_in_templates(self):
		self.prepare_project()
		inner = self.import_row(
			"Project Requirement Specification", self.specification_fields(project=self.project)
		)
		outer = self.import_row(
			inner.doctype,
			self.specification_fields(
				project=self.project,
				**{"items.reference_doctype": inner.doctype, "items.reference_name": inner.name},
			),
		)
		self.import_row(
			inner.doctype,
			{
				"name": inner.name,
				"items.reference_doctype": outer.doctype,
				"items.reference_name": outer.name,
			},
			error="The specification composition contains a cycle.",
		)
		self.assertFalse(inner.reload().items)
		requirement = self.import_row("Project Requirement", self.requirement_fields())
		self.import_row(
			"Project Requirement Specification Template",
			self.specification_fields(
				**{"items.reference_doctype": requirement.doctype, "items.reference_name": requirement.name}
			),
			error="Template and working requirements must be kept in separate compositions.",
		)

	def test_import_can_complete_only_the_responsible_users_requirements(self):
		self.prepare_project()
		other = self.import_row("Project Requirement", self.requirement_fields(responsible="Administrator"))
		self.import_row(
			other.doctype, {"name": other.name, "status": "Done"}, error="Only the assigned responsible user"
		)
		self.assertEqual(other.reload().status, "New")
		assigned = self.import_row("Project Requirement", self.requirement_fields())
		completed = self.import_row(assigned.doctype, {"name": assigned.name, "status": "Done"})
		self.assertEqual(completed.status, "Done")

	def test_import_does_not_remove_mandatory_deliverable_elements(self):
		self.prepare_project()
		deliverable = self.import_row("Project Deliverable", self.deliverable_fields())
		first = snapshot(deliverable.table_xuct)[0]
		self.import_row(
			deliverable.doctype,
			{"name": deliverable.name, **{f"table_xuct.{field}": value for field, value in first.items()}},
			error="Keep all elements of the saved result structure.",
		)
		self.assertEqual(
			[row.source_element_key for row in deliverable.reload().table_xuct], ["prepare", "review"]
		)

	def test_import_cannot_bypass_change_request_workflow(self):
		self.prepare_project()
		change = self.import_row("Project Change Request", self.change_fields())
		self.import_row(
			change.doctype,
			{"name": change.name, "status": "Approved"},
			error="Change status with the workflow actions.",
		)
		self.assertEqual(change.reload().status, "Draft")
		self.assertEqual(change.docstatus, 0)
