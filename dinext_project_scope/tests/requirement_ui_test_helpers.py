import re

import frappe
from frappe.tests.ui_test_helpers import whitelist_for_tests

from dinext_project_scope.requirements import (
	PROJECT_SPECIFICATIONS,
	REQUIREMENT,
	SPEC_TEMPLATE,
	SPECIFICATION,
)


def _prefix(run_id):
	if not (
		frappe.conf.allow_tests
		and (frappe.flags.in_test or getattr(frappe.local, "dev_server", False))
		and frappe.session.user == "Administrator"
		and isinstance(run_id, str)
		and re.fullmatch(r"[a-f0-9]{16}", run_id)
	):
		raise frappe.PermissionError
	return f"Cypress requirement {run_id}"


@whitelist_for_tests(methods=["POST"])
def create_fixture(run_id: str) -> dict:
	prefix = _prefix(run_id)
	project_type = frappe.get_doc(doctype="Project Type", project_type=prefix).insert()
	project = frappe.get_doc(doctype="Project", project_name=prefix, project_type=project_type.name).insert(
		set_name=f"CYPRESS-SCOPE-REQ-{run_id}"
	)
	contact = frappe.get_doc(doctype="Contact", first_name=prefix).insert()
	kind = frappe.get_doc(doctype="Requirement Kind", enabled=1).insert(set_name=prefix)

	def requirement(label, *, template=False, parent=None, is_group=False):
		return (
			frappe.get_doc(
				{
					"doctype": REQUIREMENT,
					"project": None if template else project.name,
					"requirement_title": f"{prefix} {label}",
					"author": contact.name,
					"responsible": "Administrator",
					"kind": kind.name,
					"requirement_importance": "Must Have",
					"status": "Template" if template else "New",
					"parent_project_requirement": parent,
					"is_group": int(is_group),
				}
			)
			.insert()
			.name
		)

	def specification(label, references, *, template=False):
		return (
			frappe.get_doc(
				{
					"doctype": SPEC_TEMPLATE if template else SPECIFICATION,
					"project": None if template else project.name,
					"title": f"{prefix} {label}",
					"responsible": "Administrator",
					"author": contact.name,
					"items": [
						{"reference_doctype": doctype, "reference_name": name} for doctype, name in references
					],
				}
			)
			.insert()
			.name
		)

	parent = requirement("template parent", template=True, is_group=True)
	child = requirement("template child", template=True, parent=parent)
	leaf = specification("child level", [(REQUIREMENT, child)], template=True)
	branch = specification("first level", [(SPEC_TEMPLATE, leaf)], template=True)
	template = specification(
		"composed template",
		[
			(REQUIREMENT, parent),
			(REQUIREMENT, child),
			(SPEC_TEMPLATE, branch),
			(SPEC_TEMPLATE, leaf),
		],
		template=True,
	)
	working = requirement("working")
	empty = specification("empty", [])
	ordinary = specification("ordinary", [(REQUIREMENT, working), (SPECIFICATION, empty)])
	project.append(PROJECT_SPECIFICATIONS, {"specification": ordinary})
	project.save()
	return {
		"project": project.name,
		"template": template,
		"child": child,
		"parent": parent,
		"leaf": leaf,
		"branch": branch,
		"working": working,
		"ordinary": ordinary,
		"empty": empty,
	}


@whitelist_for_tests(methods=["POST"])
def remove_fixture(run_id: str) -> None:
	prefix = _prefix(run_id)
	for doctype, title in (
		(SPECIFICATION, "title"),
		(SPEC_TEMPLATE, "title"),
		(REQUIREMENT, "requirement_title"),
	):
		order_by = "lft desc" if doctype == REQUIREMENT else "creation desc"
		for name in frappe.get_all(
			doctype, filters={title: ("like", f"{prefix} %")}, pluck="name", order_by=order_by
		):
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	for doctype, title in (
		("Contact", "first_name"),
		("Project", "project_name"),
		("Requirement Kind", "name"),
		("Project Type", "project_type"),
	):
		for name in frappe.get_all(doctype, filters={title: prefix}, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
