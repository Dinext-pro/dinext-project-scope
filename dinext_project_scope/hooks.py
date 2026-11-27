from dinext_project_scope.catalogs import SHIPPED_CATALOG_NAMES as _SHIPPED_CATALOG_NAMES

app_name = "dinext_project_scope"
app_title = "Dinext Project Scope"
app_publisher = "Dinext"
app_description = "Dinext Project Scope Management"
app_email = "info@dinext.ru"
app_license = "GNU General Public License (v3)"

# Apps
# ------------------

required_apps = ["erpnext", "dinext_common", "dinext_projects", "dinext_goals"]

fixtures = [
	{"doctype": "Custom Field", "filters": [["module", "=", "Dinext Project Scope"], ["dt", "=", "Project"]]},
	*[
		{"doctype": doctype, "filters": [["name", "in", list(names)]]}
		for doctype, names in _SHIPPED_CATALOG_NAMES.items()
	],
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "dinext_project_scope",
# 		"logo": "/assets/dinext_project_scope/logo.png",
# 		"title": "Dinext Project Scope",
# 		"route": "/dinext_project_scope",
# 		"has_permission": "dinext_project_scope.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/dinext_project_scope/css/dinext_project_scope.css"
# app_include_js = "/assets/dinext_project_scope/js/dinext_project_scope.js"

# include js, css files in header of web template
# web_include_css = "/assets/dinext_project_scope/css/dinext_project_scope.css"
# web_include_js = "/assets/dinext_project_scope/js/dinext_project_scope.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "dinext_project_scope/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "dinext_project_scope/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "dinext_project_scope.utils.jinja_methods",
# 	"filters": "dinext_project_scope.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "dinext_project_scope.install.before_install"
after_install = "dinext_project_scope.install.after_install"
after_sync = [
	"dinext_project_scope.install.ensure_scope_field_order",
	"dinext_project_scope.install.seed_default_result_tree_responsibility",
]
after_migrate = "dinext_project_scope.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "dinext_project_scope.uninstall.before_uninstall"
# after_uninstall = "dinext_project_scope.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "dinext_project_scope.utils.before_app_install"
# after_app_install = "dinext_project_scope.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "dinext_project_scope.utils.before_app_uninstall"
# after_app_uninstall = "dinext_project_scope.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "dinext_project_scope.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"dinext_project_scope.tasks.all"
# 	],
# 	"daily": [
# 		"dinext_project_scope.tasks.daily"
# 	],
# 	"hourly": [
# 		"dinext_project_scope.tasks.hourly"
# 	],
# 	"weekly": [
# 		"dinext_project_scope.tasks.weekly"
# 	],
# 	"monthly": [
# 		"dinext_project_scope.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "dinext_project_scope.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "dinext_project_scope.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "dinext_project_scope.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["dinext_project_scope.utils.before_request"]
# after_request = ["dinext_project_scope.utils.after_request"]

# Job Events
# ----------
# before_job = ["dinext_project_scope.utils.before_job"]
# after_job = ["dinext_project_scope.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"dinext_project_scope.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


doctype_js = {
	"Project": "public/js/project_scope.js",
	**{doctype: "public/js/scope_catalogs.js" for doctype in _SHIPPED_CATALOG_NAMES},
}
doctype_list_js = {doctype: "public/js/scope_catalogs.js" for doctype in _SHIPPED_CATALOG_NAMES}

doc_events = {
	"Project": {
		"validate": [
			"dinext_project_scope.project_scope.validate_project",
			"dinext_project_scope.requirements.validate_project",
		],
		"on_update": "dinext_project_scope.deliverable_workflow.on_project_team_change",
	},
	"Task": {
		"validate": "dinext_project_scope.deliverables.before_task_change",
		"on_change": "dinext_project_scope.deliverables.on_task_change",
		"before_change": "dinext_project_scope.deliverables.before_task_change",
		"after_delete": "dinext_project_scope.deliverables.on_task_change",
	},
}

override_doctype_class = {"Task": "dinext_project_scope.deliverables.DeliverableTask"}

has_permission = {
	name: "dinext_project_scope.access.project_document_permission"
	for name in (
		"Project Requirement",
		"Project Requirement Specification",
		"Project Deliverable",
		"Project Change Request",
	)
}
has_permission.update(
	{
		name: "dinext_project_scope.access.journal_permission"
		for name in (
			"Project Scope Approval",
			"Project Scope Template Application",
			"Project Deliverable Log",
		)
	}
)

permission_query_conditions = {
	"Project Requirement": "dinext_project_scope.access.requirement_queries",
	"Project Requirement Specification": "dinext_project_scope.access.specification_queries",
	"Project Deliverable": "dinext_project_scope.access.deliverable_queries",
	"Project Change Request": "dinext_project_scope.access.change_request_queries",
	"Project Scope Approval": "dinext_project_scope.access.journal_queries",
	"Project Scope Template Application": "dinext_project_scope.access.journal_queries",
	"Project Deliverable Log": "dinext_project_scope.access.journal_queries",
}

final_has_permission = {"Project Deliverable": has_permission["Project Deliverable"]}
final_permission_query_conditions = {
	"Project Deliverable": permission_query_conditions["Project Deliverable"],
}
standard_queries = {"Project Deliverable": "dinext_project_scope.access.deliverable_link_query"}

workflow_approval_lock_dependencies = [
	"dinext_project_scope.requirement_approval.lock_dependencies",
	"dinext_project_scope.deliverable_workflow.workflow_lock_dependencies",
	"dinext_project_scope.changes.lock_dependencies",
]
workflow_approval_round_opened = [
	"dinext_project_scope.requirement_approval.round_opened",
	"dinext_project_scope.changes.round_opened",
]
workflow_approval_vote_completed = ["dinext_project_scope.deliverable_workflow.capture_workflow_vote"]
workflow_approval_domain_handlers = {
	name: {"validate_vote": "dinext_project_scope.requirement_approval.validate_vote"}
	for name in (
		"Project Requirement",
		"Project Requirement Specification",
		"Project Requirement Specification Template",
	)
}
workflow_approval_domain_handlers.update(
	{
		"Project Deliverable": {
			"vote_context": "dinext_project_scope.deliverable_workflow.workflow_vote_context",
			"validate_vote": "dinext_project_scope.deliverable_workflow.validate_workflow_vote",
		},
		"Project Change Request": {
			"vote_context": "dinext_project_scope.changes.workflow_vote_context",
			"validate_vote": "dinext_project_scope.changes.validate_workflow_vote",
		},
	}
)
workflow_approval_fingerprint_excluded_fields = [
	{
		"Project Requirement": ["status", "responsible", "responsible_type", "lft", "rgt", "old_parent"],
		"Project Requirement Specification": ["responsible"],
		"Project Requirement Specification Template": ["responsible"],
		"Project Deliverable": ["last_acceptance_log", "progress", "plan_incomplete", "forecast_incomplete"],
		"Project Change Request": [
			"approval_approver",
			"implementation_responsible",
			"implementation_date",
			"implementation_note",
			"implementation_items",
			"implemented_at",
			"implemented_by",
		],
	}
]
