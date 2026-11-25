import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.translate import get_translations_from_csv

from dinext_project_scope import hooks

SHIPPED_CATALOGS = (
	"Project Change Relation Type",
	"Project Deliverable Category",
	"Project Deliverable Responsibility",
	"Project Deliverable Type",
	"Project Scope Type",
	"Requirement Kind",
)


def fixture_records(doctype):
	return json.loads(
		Path(frappe.get_app_path("dinext_project_scope", "fixtures", frappe.scrub(doctype) + ".json"))
		.read_text(encoding="utf-8")
	)


class TestScopeCatalogs(TestCase):
	def test_export_uses_only_shipped_catalog_records(self):
		export = {fixture["doctype"]: fixture["filters"] for fixture in hooks.fixtures}
		for doctype in SHIPPED_CATALOGS:
			with self.subTest(doctype=doctype):
				names = {row["name"] for row in fixture_records(doctype)}
				name_filter, = export[doctype]
				self.assertEqual(tuple(name_filter[:2]), ("name", "in"))
				self.assertEqual(set(name_filter[2]), names)

	def test_existing_category_responsibilities_are_kept_on_import(self):
		incoming = frappe.get_doc(fixture_records("Project Deliverable Category")[0])
		installed = frappe.get_doc(fixture_records(incoming.doctype)[0])
		installed.enabled = 0
		setting = installed.append(
			"responsibilities", {"responsibility": "О", "project_role": "Project Manager"}
		)
		with patch.dict(frappe.flags, {"in_fixtures": True}), patch.object(
			frappe.db, "exists", return_value=True
		), patch.object(frappe, "get_doc", return_value=installed):
			incoming.run_method("before_import")
		self.assertEqual(incoming.enabled, 0)
		self.assertEqual(len(incoming.responsibilities), 1)
		self.assertEqual(incoming.responsibilities[0].project_role, setting.project_role)
		self.assertEqual(incoming.responsibilities[0].responsibility, setting.responsibility)

	def test_existing_result_type_settings_and_empty_icon_fallback(self):
		fixture = fixture_records("Project Deliverable Type")[0]
		for icon in (None, "edit"):
			with self.subTest(icon=icon):
				incoming = frappe.get_doc(fixture)
				installed = frappe.get_doc(fixture)
				installed.color = "#112233"
				installed.icon = icon
				installed.elements[0].weight = 3
				with patch.dict(frappe.flags, {"in_fixtures": True}), patch.object(
					frappe.db, "exists", return_value=True
				), patch.object(frappe, "get_doc", return_value=installed):
					incoming.run_method("before_import")
				self.assertEqual(incoming.color, "#112233")
				self.assertEqual(incoming.icon, icon or fixture["icon"])
				self.assertEqual(incoming.elements[0].weight, 3)

	def test_every_shipped_label_and_description_has_english_text(self):
		messages = get_translations_from_csv("en", "dinext_project_scope")
		total_labels = total_descriptions = 0
		for doctype in SHIPPED_CATALOGS:
			for row in fixture_records(doctype):
				label = row.get("responsibility") or row["name"]
				with self.subTest(doctype=doctype, label=label):
					self.assertTrue(messages.get(label))
					self.assertTrue(messages.get(f"{label}:{doctype}"))
					total_labels += 1
					if description := row.get("description"):
						translation = messages.get(f"{description}:{doctype}")
						self.assertTrue(translation)
						self.assertNotIn("ExampleCustomer", translation)
						total_descriptions += 1
		self.assertEqual((total_labels, total_descriptions), (39, 29))
