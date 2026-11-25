"""Export and import settings for the shipped scope catalogs."""

import frappe
from frappe.model import no_value_fields, table_fields

SHIPPED_CATALOG_NAMES = {
	"Project Change Relation Type": ("Сроки", "Трудозатраты", "Фин. результат", "Качество", "Объем"),
	"Project Deliverable Category": (
		"Управление проектом",
		"Проектирование",
		"Конфигурирование",
		"Техническая архитектура и инфраструктура",
		"Интеграция",
		"Разработка",
		"Отчетность",
		"Орг. изменения",
		"Тестирование",
		"Обучение",
		"Начальная миграция",
		"Поддержка",
	),
	"Project Deliverable Responsibility": ("И", "О", "С", "К", "У", "Д"),
	"Project Deliverable Type": ("Документ", "Работа", "Разработка", "Тестирование", "Миграция данных"),
	"Project Scope Type": ("Географический", "Процессный", "Интеграционный", "Организационный", "Функциональный"),
	"Requirement Kind": ("Организационные", "Регуляторные", "Финансовые", "Функциональные", "Технические", "Стратегические"),
}


def preserve_fixture_settings(doc):
	"""Reuse the configured values before Frappe replaces a shipped fixture."""
	if (
		not frappe.flags.in_fixtures
		or doc.name not in SHIPPED_CATALOG_NAMES[doc.doctype]
		or not frappe.db.exists(doc.doctype, doc.name)
	):
		return
	installed = frappe.get_doc(doc.doctype, doc.name)
	for field in doc.meta.fields:
		if field.is_virtual or (field.fieldtype in no_value_fields and field.fieldtype not in table_fields):
			continue
		value = installed.get(field.fieldname)
		if doc.doctype == "Project Deliverable Type" and field.fieldname == "icon" and not value:
			continue
		doc.set(field.fieldname, value)
