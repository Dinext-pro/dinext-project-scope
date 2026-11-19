import re
from secrets import token_urlsafe

import frappe
import frappe.share
from frappe.tests.ui_test_helpers import whitelist_for_tests

from dinext_project_scope.requirements import (
	PROJECT_REQUIREMENTS,
	PROJECT_SPECIFICATIONS,
	REQUIREMENT,
	SPEC_TEMPLATE,
	SPECIFICATION,
)
from dinext_project_scope.tests.project_fixture import make_project, project_user_roles


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
	project = make_project(f"{prefix} A", f"CYPRESS-SCOPE-REQ-{run_id}-A")
	other = make_project(f"{prefix} B", f"CYPRESS-SCOPE-REQ-{run_id}-B", project.project_type)
	contact = frappe.get_doc(doctype="Contact", first_name=prefix).insert()
	kind = frappe.get_doc(doctype="Requirement Kind", enabled=1).insert(set_name=prefix)
	actors = {}
	for role in ("author", "reviewer", "outsider"):
		email = f"scope-{run_id}-{role}@example.test"
		password = f"Qa9!{token_urlsafe(18)}"
		frappe.get_doc(
			doctype="User",
			email=email,
			first_name=f"{prefix} {role}",
			user_type="System User",
			language="en",
			send_welcome_email=0,
			new_password=password,
			roles=project_user_roles(),
		).insert()
		actors[role] = {"email": email, "password": password}
	for user in actors.values():
		frappe.share.add("Contact", contact.name, user["email"], read=1)
	for selected_project, roles in ((project, ("author", "reviewer")), (other, ("author", "outsider"))):
		for role in roles:
			user = actors[role]["email"]
			selected_project.append("users", {"user": user, "welcome_email_sent": 1})
		selected_project.save()
		for role in roles:
			frappe.share.add("Project", selected_project.name, actors[role]["email"], read=1, write=1)
	frappe.get_doc(
		doctype="User Permission",
		user=actors["outsider"]["email"],
		allow="Project",
		for_value=other.name,
		apply_to_all_doctypes=1,
	).insert()
	reviewer = actors["reviewer"]["email"]

	def requirement(label, *, template=False, parent=None, is_group=False, selected_project=project):
		return (
			frappe.get_doc(
				{
					"doctype": REQUIREMENT,
					"project": None if template else selected_project.name,
					"requirement_title": f"{prefix} {label}",
					"author": contact.name,
					"responsible": reviewer,
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

	def specification(label, references, *, template=False, selected_project=project):
		return (
			frappe.get_doc(
				{
					"doctype": SPEC_TEMPLATE if template else SPECIFICATION,
					"project": None if template else selected_project.name,
					"title": f"{prefix} {label}",
					"responsible": reviewer,
					"author": contact.name,
					"items": [
						{"reference_doctype": doctype, "reference_name": name} for doctype, name in references
					],
				}
			)
			.insert()
			.name
		)

	frappe.set_user(actors["author"]["email"])
	try:
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
		working = requirement("working", is_group=True)
		nested_child = requirement("nested child", parent=working)
		replacement = requirement("replacement", parent=working)
		stale_requirement = requirement("review revision")
		stale_addition = requirement("added during review")
		foreign = requirement("working", selected_project=other, is_group=True)
		nested = specification("ordinary nested", [(REQUIREMENT, nested_child), (REQUIREMENT, working)])
		empty = specification("empty", [])
		standalone = specification("standalone empty", [])
		ordinary = specification(
			"ordinary",
			[(REQUIREMENT, working), (SPECIFICATION, empty), (SPECIFICATION, nested)],
		)
		review_set = specification("review set", [(REQUIREMENT, working), (SPECIFICATION, nested)])
		stale_nested = specification("stale nested", [(REQUIREMENT, stale_requirement)])
		stale_set = specification("stale review", [(SPECIFICATION, stale_nested)])
		foreign_spec = specification("foreign", [(REQUIREMENT, foreign)], selected_project=other)
	finally:
		frappe.set_user("Administrator")
	project.reload()
	project.append(PROJECT_REQUIREMENTS, {"project_requirement": working})
	project.append(PROJECT_SPECIFICATIONS, {"specification": ordinary})
	project.save()
	return {
		"prefix": prefix,
		"actors": actors,
		"contact": contact.name,
		"kind": kind.name,
		"project": project.name,
		"other": other.name,
		"template": template,
		"child": child,
		"parent": parent,
		"leaf": leaf,
		"branch": branch,
		"working": working,
		"ordinary": ordinary,
		"empty": empty,
		"standalone": standalone,
		"nested": nested,
		"nested_child": nested_child,
		"replacement": replacement,
		"review_set": review_set,
		"stale_set": stale_set,
		"stale_nested": stale_nested,
		"stale_requirement": stale_requirement,
		"stale_addition": stale_addition,
		"foreign": foreign,
		"foreign_spec": foreign_spec,
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
		("Requirement Kind", "name"),
	):
		for name in frappe.get_all(doctype, filters={title: prefix}, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, delete_permanently=True)
	for name in frappe.get_all(
		"User", filters={"email": ("like", f"scope-{run_id}-%@example.test")}, pluck="name"
	):
		for permission in frappe.get_all("User Permission", filters={"user": name}, pluck="name"):
			frappe.delete_doc("User Permission", permission, delete_permanently=True)
		frappe.delete_doc("User", name, force=True, delete_permanently=True)
	for label in (f"{prefix} A", f"{prefix} B"):
		for name in frappe.get_all("Project", filters={"project_name": label}, pluck="name"):
			frappe.delete_doc("Project", name, force=True, delete_permanently=True)
	for name in frappe.get_all("Project Type", filters={"project_type": f"{prefix} A"}, pluck="name"):
		frappe.delete_doc("Project Type", name, force=True, delete_permanently=True)
