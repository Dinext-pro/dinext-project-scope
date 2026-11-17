"""Record a template application and its generated records in the same transaction."""

import json
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime

from dinext_project_scope.access import check_document, check_project, lock_project

APPLICATION = "Project Scope Template Application"
TEMPLATE_TYPES = {
	"Project Requirement Specification Template",
	"Project Constraints Template",
	"Project Deliverables Template",
}


def digest(data):
	return sha256(
		json.dumps(data, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
	).hexdigest()


def operation_key(project, template_doctype, template_name, request_key, user):
	if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
		raise frappe.ValidationError(_("A template application request identifier is required."))
	return f"APP-{digest((user, project, request_key))}"


def apply_once(project, template_doctype, template_name, request_key, payload, create):
	if template_doctype not in TEMPLATE_TYPES:
		raise frappe.ValidationError(_("Invalid project template type."))
	check_project(project, "write")
	check_document(template_doctype, template_name)
	lock_project(project)
	key = operation_key(project, template_doctype, template_name, request_key, frappe.session.user)
	fingerprint = digest((template_doctype, template_name, payload))
	previous = frappe.db.get_value(
		APPLICATION, key, ["request_digest", "created_map"], as_dict=True, for_update=True
	)
	if previous:
		if previous.request_digest != fingerprint:
			raise frappe.ValidationError(_("This request was already used with different template data."))
		result = frappe.parse_json(previous.created_map)
		if template_doctype == "Project Deliverables Template":
			for name in result.values():
				check_document("Project Deliverable", name)
		elif template_doctype == "Project Constraints Template":
			for name in result.get("constraints", {}).values():
				check_document("Project Constraint", name)
		return result
	savepoint = f"scope_template_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(savepoint)
	try:
		result = create()
		frappe.get_doc(
			doctype=APPLICATION,
			project=project,
			template_doctype=template_doctype,
			template=template_name,
			requested_by=frappe.session.user,
			applied_at=now_datetime(),
			request_digest=fingerprint,
			created_map=frappe.as_json(result),
		).insert(ignore_permissions=True, set_name=key)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return result
