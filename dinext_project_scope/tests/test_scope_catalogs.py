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

	def test_shipped_structure_names_and_responsibility_abbreviations_have_english_text(self):
		messages = get_translations_from_csv("en", "dinext_project_scope")
		names = {
			element["element_name"]
			for row in fixture_records("Project Deliverable Type")
			for element in row["elements"]
		}
		for name in sorted(names):
			with self.subTest(element=name):
				translation = messages.get(f"{name}:Project Deliverable Type Element")
				self.assertTrue(translation)
				self.assertNotEqual(translation, name)
		abbreviations = {"И": "R", "О": "A", "К": "C", "Д": "I", "С": "V", "У": "S"}
		self.assertEqual(
			{
				row["name"]: messages.get(f"{row['name']}:Project Deliverable Responsibility Abbreviation")
				for row in fixture_records("Project Deliverable Responsibility")
			},
			abbreviations,
		)

	def test_scope_fixture_sections_and_field_order_preserve_other_project_fields(self):
		from dinext_project_scope.install import scope_field_order

		fields = {row["fieldname"]: row for row in fixture_records("Custom Field") if row["dt"] == "Project"}
		sections = (
			("custom_scope_items_section", "project_scopes"),
			("custom_scope_requirements_section", "custom_scope_requirements_html"),
			("custom_scope_constraints_section", "project_constraints"),
			("custom_scope_changes_section", "custom_scope_changes_html"),
		)
		for section, _field in sections:
			self.assertEqual(fields[section]["fieldtype"], "Section Break")
			self.assertEqual(fields[section]["collapsible"], 1)
			self.assertEqual(fields[section]["collapsible_depends_on"], "eval:true")

		existing = ["project_scopes", "details", "custom_объем", "project_constraints", "finances"]
		reordered = scope_field_order(existing)
		self.assertEqual([field for field in reordered if field in {"details", "custom_объем", "finances"}],
			["details", "custom_объем", "finances"])
		last = reordered.index("custom_объем")
		for section, field in sections:
			section_index = reordered.index(section)
			self.assertGreater(section_index, last)
			last = reordered.index(field)
			self.assertGreater(last, section_index)
		self.assertLess(last, reordered.index("finances"))
		self.assertEqual(scope_field_order(reordered), reordered)
