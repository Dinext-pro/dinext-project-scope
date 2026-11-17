"""Use the parent project as the access boundary for its scope documents."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

PROJECT_DOCUMENTS = {
	"Project Requirement",
	"Project Requirement Specification",
	"Project Deliverable",
	"Project Change Request",
}
PROJECT_ROWS = {
	"Project Scope": {"project_scopes", "custom_project_scope"},
	"Project Constraint": {"project_constraints", "custom_constraints_and_assumptions"},
	"Project Risk": {"custom_project_risks"},
}
SHARED_TARGETS = {"Account", "Project Role", "Territory", "Goal"}
PROJECT_TARGETS = PROJECT_DOCUMENTS | set(PROJECT_ROWS) | {"Task"}
ASSIGNMENT_TABLES = {
	"User": ("custom_ts_details", "pt_participant", "pt_role"),
	"Contact": ("custom_contact_list", "contact", "project_role"),
}


class OwnedProjectRow(Document):
	def validate(self):
		raise frappe.ValidationError(_("Edit this row from its parent document."))

	def on_trash(self):
		raise frappe.ValidationError(_("Edit this row from its parent document."))


def _required(name):
	if not isinstance(name, str) or not name.strip():
		raise frappe.ValidationError(_("A document identifier is required."))
	return name


def has_project_access(project, ptype="read", user=None):
	if not project or not frappe.db.exists("Project", project):
		return False
	return bool(frappe.has_permission("Project", ptype=ptype, doc=project, user=user, throw=False))


def check_project(project, ptype="read"):
	_required(project)
	if not has_project_access(project, ptype):
		raise frappe.PermissionError(_("You do not have access to the selected project."))
	return frappe.get_doc("Project", project)


def readable_projects(user=None):
	return frappe.get_list("Project", pluck="name", limit_page_length=0, user=user or frappe.session.user)


def lock_project(project):
	"""Serialise writes to a project's aggregate inside the caller's transaction."""
	_required(project)
	if not frappe.db.get_value("Project", project, "name", for_update=True):
		raise frappe.DoesNotExistError(_("The selected project does not exist."))


def _owned_row(doctype, name):
	row = frappe.db.get_value(doctype, name, ["name", "parent", "parenttype", "parentfield"], as_dict=True)
	if not row or row.parenttype != "Project" or row.parentfield not in PROJECT_ROWS[doctype]:
		raise frappe.DoesNotExistError(_("The selected project row does not exist."))
	return row


def check_document(doctype, name, ptype="read"):
	_required(doctype)
	_required(name)
	if doctype in PROJECT_ROWS:
		check_project(_owned_row(doctype, name).parent, ptype)
		return frappe.get_doc(doctype, name)
	if doctype == "Project":
		return check_project(name, ptype)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission(ptype)
	if doctype in PROJECT_DOCUMENTS | {"Task"} and doc.get("project"):
		check_project(doc.project)
	return doc


def validate_project_target(project, doctype, name, *, require_membership=True, check_permission=True):
	_required(project)
	_required(name)
	if doctype in SHARED_TARGETS:
		if check_permission:
			check_document(doctype, name)
		elif not frappe.db.exists(doctype, name):
			raise frappe.DoesNotExistError(_("The selected document does not exist."))
		return
	if doctype not in PROJECT_TARGETS:
		raise frappe.ValidationError(_("This type of document cannot be linked to project scope."))
	if doctype in PROJECT_ROWS:
		row = _owned_row(doctype, name)
		owner_project = row.parent
	else:
		fields = (
			["project", "status"]
			if doctype in {"Project Requirement", "Project Deliverable"}
			else ["project"]
		)
		owner = frappe.db.get_value(doctype, name, fields, as_dict=True)
		if not owner:
			raise frappe.DoesNotExistError(_("The selected document does not exist."))
		owner_project = owner.project if owner.get("status") != "Template" else None
	if owner_project != project:
		raise frappe.ValidationError(_("Select a record from the same project."))
	if check_permission:
		check_document(doctype, name)
	if doctype == "Project Requirement" and require_membership:
		from dinext_project_scope.requirements import project_membership

		if name not in project_membership(project, check_permission=check_permission):
			raise frappe.ValidationError(_("The requirement is outside the current project scope."))


def project_document_permission(doc, ptype="read", user=None, **kwargs):
	"""Deny access outside Project permissions while preserving DocType role checks."""
	project = doc.get("project")
	if project and not has_project_access(project, "read", user):
		return False
	if not project and doc.doctype not in {"Project Requirement", "Project Deliverable"} and not doc.is_new():
		return False
	return None


def scoped_queries(doctype, user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	projects = readable_projects(user)
	table = f"`tab{doctype}`"
	clause = (
		f"{table}.project in ({', '.join(frappe.db.escape(project) for project in projects)})"
		if projects
		else "1=0"
	)
	if doctype in {"Project Requirement", "Project Deliverable"}:
		clause = f"({clause} or ({table}.status = 'Template' and coalesce({table}.project, '') = ''))"
	return clause


def requirement_queries(user=None):
	return scoped_queries("Project Requirement", user)


def specification_queries(user=None):
	return scoped_queries("Project Requirement Specification", user)


def deliverable_queries(user=None):
	return scoped_queries("Project Deliverable", user)


def change_request_queries(user=None):
	return scoped_queries("Project Change Request", user)


def journal_permission(doc, ptype="read", user=None, **kwargs):
	# Service rows can contain hidden dependencies, so only the summary APIs expose them.
	return False


def journal_queries(user=None):
	return "" if (user or frappe.session.user) == "Administrator" else "1=0"


def project_participants(project, doctype=None, *, current=False):
	"""Current declared project roles. Callers control read/write scope independently."""
	doc = frappe.get_doc("Project", _required(project), for_update=current)
	today = getdate()
	participants = set()
	for target, (table, name_field, role_field) in ASSIGNMENT_TABLES.items():
		if doctype and doctype != target:
			continue
		for row in doc.get(table) or []:
			name, role = row.get(name_field), row.get(role_field)
			if not name or not role:
				continue
			if target == "User":
				if row.get("pt_participant_type") not in (None, "", "User"):
					continue
				if row.get("pt_valid_from") and getdate(row.pt_valid_from) > today:
					continue
				if row.get("pt_valid_for") and getdate(row.pt_valid_for) < today:
					continue
				if not frappe.db.get_value("User", name, "enabled"):
					continue
			participants.add((target, name, role))
	return [dict(doctype=target, name=name, role=role) for target, name, role in sorted(participants)]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def project_target_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe._dict(frappe.parse_json(filters) or {})
	project = filters.get("project")
	if doctype not in PROJECT_TARGETS | SHARED_TARGETS:
		raise frappe.ValidationError(_("Invalid project link type."))
	if not project:
		return []
	check_project(project)
	if doctype in PROJECT_ROWS:
		rows = frappe.get_all(
			doctype,
			filters={
				"parent": project,
				"parenttype": "Project",
				"parentfield": ["in", list(PROJECT_ROWS[doctype])],
			},
			fields=[
				"name",
				{"Project Scope": "scope_title", "Project Constraint": "subject", "Project Risk": "subject"}[
					doctype
				],
			],
		)
		matches = [
			tuple(row.values())
			for row in rows
			if any(txt.casefold() in str(value).casefold() for value in row.values())
		]
		return matches[start : start + page_len]
	meta = frappe.get_meta(doctype)
	title = meta.title_field or "name"
	query = {"project": project} if doctype in PROJECT_TARGETS else {}
	if doctype in {"Project Requirement", "Project Deliverable"}:
		query["status"] = ("!=", "Template")
	if doctype == "Project Requirement" and filters.get("current_scope"):
		from dinext_project_scope.requirements import project_membership

		query["name"] = ("in", list(project_membership(project)))
	return frappe.get_list(
		doctype,
		fields=list(dict.fromkeys(("name", title))),
		filters=query,
		or_filters={field: ("like", f"%{txt}%") for field in ("name", title)},
		as_list=True,
		start=start,
		page_length=page_len,
		order_by="name asc",
	)
