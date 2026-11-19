"""Create a reproducible, synthetic Project Scope demonstration on localhost."""
# ruff: noqa: RUF001

import os
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import frappe
from dinext_common.workflow_approval import engine
from frappe.utils import add_days, today

from dinext_project_scope.requirements import (
	PROJECT_REQUIREMENTS,
	PROJECT_SPECIFICATIONS,
	apply_specification_template,
	preview_specification_template,
)
from dinext_project_scope.tests.project_fixture import (
	goal_project_parameter,
	make_goal,
	make_project,
	project_user_roles,
)

PORTAL = "SCOPE-DEMO-PORTAL"
INTEGRATION = "SCOPE-DEMO-INTEGRATION"
ANALYST = "scope-demo-analyst@example.test"
MANAGER = "scope-demo-manager@example.test"
ENGINEER = "scope-demo-engineer@example.test"
USERS = (ANALYST, MANAGER, ENGINEER)
GOAL_SUBJECT = "Сократить задержку передачи обращений из цифровых каналов"

REQ = "Project Requirement"
SPEC = "Project Requirement Specification"
SPEC_TEMPLATE = "Project Requirement Specification Template"
RESULT = "Project Deliverable"
CHANGE = "Project Change Request"

OPTIONAL_ASSIGNMENTS_BY_RESULT = {
	"Правила маршрутизации и SLA": ("Получает информацию (демо)",),
	"Личный кабинет и единый вход": ("Согласует требования (демо)", "Получает информацию (демо)"),
	"Отчётность службы поддержки": ("Согласует требования (демо)",),
	"Канал обращений из мессенджера": ("Выполняет работы (демо)", "Согласует требования (демо)"),
}

REQUIREMENTS = (
	("intake", "Единый приём сервисных заявок", None),
	("form", "Форма заявки с каталогом услуг", "intake"),
	("attachment", "Вложения с проверкой формата и размера", "intake"),
	("identity", "Корпоративный вход в личный кабинет", "intake"),
	("tracking", "История обращений заявителя", "intake"),
	("routing", "Назначение и обработка обращений", None),
	("queue", "Распределение по очередям поддержки", "routing"),
	("sla", "Сроки реакции по классу услуги", "routing"),
	("shift", "Передача незакрытых заявок между сменами", "routing"),
	("escalation", "Эскалация заявок с нарушенным SLA", "routing"),
	("exchange", "Обмен данными с учётной системой", None),
	("directory", "Синхронизация справочника подразделений", "exchange"),
	("api", "Передача закрытых заявок в ERP", "exchange"),
	("duplicates", "Повтор доставки без дублирования заявки", "exchange"),
	("access", "Журнал доступа к передаваемым данным", "exchange"),
	("analytics", "Аналитика и приёмка сервиса", None),
	("chart", "Панель нагрузки и просроченных обращений", "analytics"),
	("export", "Выгрузка отчёта по соблюдению SLA", "analytics"),
	("checklist", "Сценарии приёмки первой очереди", "analytics"),
	("chat", "Приём обращений из корпоративного мессенджера", "analytics"),
)


def insert(doctype, name=None, **fields):
	return frappe.get_doc(doctype=doctype, **fields).insert(set_name=name)


def catalog(doctype, name, **fields):
	return (
		frappe.get_doc(doctype, name) if frappe.db.exists(doctype, name) else insert(doctype, name, **fields)
	)


@contextmanager
def actor(user):
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


def share(doc):
	for user in USERS:
		frappe.share.add(doc.doctype, doc.name, user=user, read=1, write=1, notify=0)


def vote(doc, action, user, comment=None):
	task = frappe.db.get_value(
		"Workflow Task",
		dict(
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			approver=user,
			round_status="Open",
			status="Working",
		),
		"name",
	)
	if not task:
		frappe.throw(f"Missing Workflow task for {doc.doctype} {doc.name}: {action}")
	with actor(user):
		outcome = engine.cast_vote(task, action=action, comment=comment)
	if not outcome.get("transitioned"):
		frappe.throw(f"Workflow did not transition {doc.name}: {action}")
	doc.reload()


def requirement(title, contact, kind, project=None, parent=None, group=False):
	return insert(
		REQ,
		project=project.name if project else None,
		requirement_title=title,
		author=contact,
		responsible=ANALYST,
		kind=kind,
		priority="High" if group else "Medium",
		requirement_importance="Must Have",
		parent_project_requirement=parent.name if parent else None,
		status="New" if project else "Template",
		is_group=int(group),
		description=f"{title}. Проверка входит в программу приёмки сервисного портала.",
	)


def specification(title, contact, references, project=None):
	doctype = SPEC if project else SPEC_TEMPLATE
	with actor(ANALYST):
		doc = insert(
			doctype,
			title=title,
			author=contact,
			responsible=MANAGER,
			**({"project": project.name} if project else {}),
			items=[{"reference_doctype": item.doctype, "reference_name": item.name} for item in references],
		)
	share(doc)
	return doc


def create_requirements(project, contact, kind):
	docs = {}
	with actor(ANALYST):
		for key, title, parent in REQUIREMENTS:
			docs[key] = requirement(title, contact, kind, project, docs.get(parent), group=not parent)
		template_items = [
			requirement(title, contact, kind)
			for title in (
				"Документировать контрольные ответы API",
				"Зафиксировать время восстановления обмена",
				"Описать проверку повторной загрузки данных",
			)
		]
	for doc in docs.values():
		share(doc)
	exchange = specification(
		"Обмен и обработка ошибок",
		contact,
		[docs[k] for k in ("exchange", "api", "duplicates", "access")],
		project,
	)
	routing = specification(
		"Очереди поддержки и SLA",
		contact,
		[docs[k] for k in ("routing", "queue", "sla", "shift", "escalation")] + [exchange],
		project,
	)
	portal = specification(
		"Первая очередь сервисного портала",
		contact,
		[docs[k] for k in ("intake", "form", "attachment", "identity", "tracking")] + [routing],
		project,
	)
	analytics = specification(
		"Отчётность и приёмка",
		contact,
		[docs[k] for k in ("analytics", "chart", "export", "checklist")],
		project,
	)
	specification("Подготовка запуска и обучение операторов", contact, [], project)
	template_leaf = specification("Контрольные точки обмена", contact, template_items[:2])
	template = specification("Типовые требования к интеграции", contact, [template_leaf, template_items[2]])
	project.reload()
	for spec in (portal, analytics):
		project.append(PROJECT_SPECIFICATIONS, {"specification": spec.name})
	for key in ("directory", "chat", "form"):
		project.append(PROJECT_REQUIREMENTS, {"project_requirement": docs[key].name})
	project.save()
	for spec in (portal, analytics, template):
		vote(spec, "Submit for Review", ANALYST)
	for spec in (portal, analytics, template):
		vote(spec, "Approve", MANAGER)
	vote(routing, "Submit for Review", ANALYST)
	vote(exchange, "Submit for Review", ANALYST)
	vote(exchange, "Reject", MANAGER, "В первой очереди требуется уточнить SLA повторной доставки.")
	return docs, template


def task(project, subject, progress, day, parent=None, group=False):
	deadline = add_days(today(), day)
	return insert(
		"Task",
		subject=subject,
		project=project.name,
		parent_task=parent,
		is_group=int(group),
		status="Completed" if progress == 100 else "Working" if progress else "Open",
		progress=progress,
		exp_start_date=add_days(deadline, -14),
		exp_end_date=deadline,
		custom_planned_start_date=add_days(deadline, -14),
		custom_planned_end_date=deadline,
		completed_on=add_days(today(), -1) if progress == 100 else None,
	)


def result(project, title, category, requirements, work, assignments):
	kind = catalog(
		"Project Deliverable Type",
		title,
		enabled=1,
		elements=[
			dict(element_key=f"work-{index}", element_name=label, element_type=doc.doctype, weight=weight)
			for index, (label, doc, weight) in enumerate(work)
		],
	)
	doc = insert(
		RESULT,
		title=title,
		project=project.name,
		category=category,
		deliverable_type=kind.name,
		deliverable_requirements=[dict(project_requirement=req.name) for req in requirements],
		table_xuct=[
			dict(
				source_element_key=f"work-{index}",
				element_type=item.doctype,
				element=item.name,
				weight=weight,
			)
			for index, (_, item, weight) in enumerate(work)
		],
		deliverable_responsibles=assignments,
	)
	share(doc)
	return doc


def responsibility_rows(roles, contact):
	rows = []
	for code, title, color, role, person in zip(
		("A", "C", "R", "I"),
		("Принимает результат", "Согласует требования", "Выполняет работы", "Получает информацию"),
		("#DFB856", "#667FBA", "#3B9C81", "#9B83AF"),
		roles,
		(MANAGER, ANALYST, ENGINEER, contact),
		strict=True,
	):
		kind = catalog(
			"Project Deliverable Responsibility",
			f"{title} (демо)",
			responsibility=code,
			enabled=1,
			color=color,
		)
		rows.append(
			dict(
				responsibility=kind.name,
				project_role=role,
				responsible_type="Contact" if person == contact else "User",
				responsible=person,
			)
		)
	assigned = {row["responsibility"] for row in rows}
	for name in frappe.get_all(
		"Project Deliverable Responsibility", filters={"enabled": 1, "required": 1}, pluck="name"
	):
		if name not in assigned:
			rows.append(
				dict(responsibility=name, project_role=roles[0], responsible_type="User", responsible=MANAGER)
			)
	return rows


def create_results(project, requirements, categories, assignments):
	intake = task(project, "Публикация формы и каталога услуг", 100, -4)
	catalogue = task(project, "Настройка полей каталога", 100, -3)
	queue = task(project, "Контур очередей поддержки", 0, -1, group=True)
	task(project, "Правила входящей линии", 80, -2, parent=queue.name)
	task(project, "Матрица эскалаций", 35, -1, parent=queue.name)
	routing = task(project, "Проверка календаря SLA", 55, -1)
	auth = task(project, "Проверка единого входа", 100, 1)
	api = task(project, "Передача закрытых заявок в ERP", 45, 8)
	log = task(project, "Проверка повторных отправок", 20, 9)
	charts = task(project, "Настройка сводки сервиса", 28, 13)
	export = task(project, "Контроль расчёта SLA по выгрузке", 0, 17)
	chat = task(project, "Согласование канала мессенджера", 0, -7)

	def add(title, category, keys, work):
		omit = OPTIONAL_ASSIGNMENTS_BY_RESULT.get(title, ())
		selected = [row for row in assignments if row["responsibility"] not in omit]
		return result(
			project, title, categories[category], [requirements[key] for key in keys], work, selected
		)

	form = add(
		"Карточка заявки и каталог",
		"portal",
		("form", "attachment", "tracking"),
		[("Публикация", intake, 2), ("Каталог", catalogue, 1)],
	)
	queues = add(
		"Правила маршрутизации и SLA",
		"portal",
		("queue", "sla", "shift", "escalation"),
		[("Дежурства", queue, 3), ("Проверка SLA", routing, 2)],
	)
	identity = add("Личный кабинет и единый вход", "portal", ("identity",), [("Вход", auth, 1)])
	exchange = add(
		"Контур обмена с ERP",
		"exchange",
		("api", "duplicates", "access"),
		[("Поток заявок", api, 3), ("Повторы", log, 1)],
	)
	reporting = add(
		"Отчётность службы поддержки",
		"data",
		("chart", "export", "checklist"),
		[("Показатели", charts, 2), ("Выгрузка SLA", export, 1)],
	)
	portal = add(
		"Сервисный портал первой очереди",
		"portal",
		("intake", "routing", "exchange"),
		[
			("Форма", form, 3),
			("Управление потоком", queues, 3),
			("Единый вход", identity, 2),
			("Обмен данными", exchange, 2),
		],
	)
	cancelled = add("Канал обращений из мессенджера", "exchange", ("chat",), [("Согласование", chat, 1)])
	vote(form, "Request Acceptance", ANALYST)
	vote(form, "Accept Deliverable", MANAGER)
	vote(identity, "Request Acceptance", ANALYST)
	for doc in (queues, exchange, reporting, portal):
		vote(doc, "Start Work", ANALYST)
	vote(cancelled, "Cancel", ANALYST, "Подключение канала перенесено во вторую очередь.")
	for doc, progress in ((routing, 72), (api, 63), (charts, 42)):
		doc.reload().update({"progress": progress}).save()
	return (portal, form, queues, identity, exchange, reporting, cancelled)


def create_changes(project, secondary, contact, results):
	kind = catalog(
		"Project Change Relation Type",
		"Влияние на срок результата (демо)",
		enabled=1,
		reqd_explanation=1,
		reqd_estimation=1,
		reqd_link=1,
		link_doctype=RESULT,
	)
	portal, form, queues, _, exchange, _, cancelled = results
	secondary_result = result(secondary, "Шлюз обмена регистрами", exchange.category, [], [], [])

	def add(title, target, links, description):
		with actor(ANALYST):
			doc = insert(
				CHANGE,
				project=target.name,
				title=title,
				initiator=contact,
				description=description,
				reason="Решение рабочей встречи службы поддержки.",
				alternative="Перенести изменение в следующую очередь.",
				implementation_responsible=ANALYST,
				change_relations=[
					dict(
						type=kind.name,
						direction="target",
						level=level,
						estimation=estimate,
						explanation=note,
						link_doctype=RESULT,
						link=item.name,
					)
					for item, level, estimate, note in links
				],
			)
		share(doc)
		vote(doc, "Submit for Review", ANALYST)
		return doc

	add(
		"Добавить ночную эскалацию для критичных заявок",
		project,
		[
			(queues, "Strong", "2–4 дня", "Добавить календарь дежурств."),
			(portal, "Weak", "1 день", "Обновить правила первой очереди."),
		],
		"Критичные заявки переходят к дежурному в нерабочее время.",
	)
	implemented = add(
		"Сократить обязательные поля анкеты",
		project,
		[(form, "Weak", "1 день", "Заменить ввод кода выбором из справочника.")],
		"Заявители на пилоте не знают внутренний код подразделения.",
	)
	rejected = add(
		"Ускорить подключение мессенджера",
		project,
		[(cancelled, "Strong", "4–6 дней", "Отдельное согласование правил доступа.")],
		"Рассмотреть подключение канала в первую очередь.",
	)
	add(
		"Добавить пакетную передачу регистра",
		secondary,
		[(secondary_result, "Weak", "1–2 дня", "Проверить размер пакета с владельцем учётной системы.")],
		"Ежедневная синхронизация выходит за отведённое окно.",
	)
	vote(implemented, "Approve", MANAGER)
	with actor(ANALYST):
		implemented.implementation_date = today()
		implemented.implementation_note = (
			"Подразделение выбирается из справочника. Анкета проверена на стенде."
		)
		implemented.append("implementation_items", dict(reference_doctype=RESULT, reference_name=form.name))
		implemented.save()
	vote(implemented, "Mark Implemented", ANALYST)
	vote(rejected, "Reject", MANAGER, "Интеграция требует отдельного согласования в следующей очереди.")


def add_constraints(project, categories):
	for subject, kind, verification, category, note in (
		(
			"Срок первой очереди ограничен кварталом",
			"Constraint",
			None,
			"portal",
			"Квартальный релиз согласован с владельцем сервиса.",
		),
		(
			"Каталог подразделений доступен через ERP",
			"Assumption",
			"Confirmed",
			"exchange",
			"Обмен проверен на синтетическом справочнике.",
		),
		(
			"Отчёт SLA доступен владельцу сервиса",
			"Assumption",
			"Pending",
			"data",
			"Владелец сервиса проверит полномочия на приёмке.",
		),
		(
			"Чат поддерживает произвольные вложения",
			"Assumption",
			"Disproved",
			"exchange",
			"Стенд показал ограничения по размерам и типам файлов.",
		),
	):
		project.append(
			"project_constraints",
			dict(
				subject=subject,
				record_type=kind,
				category=categories[category],
				status="Approved" if kind == "Constraint" else "New",
				verification_status=verification,
				verification_note=note if verification in {"Confirmed", "Disproved"} else None,
				description=note,
				responsible_type="User",
				responsible=ANALYST,
				review_date=add_days(today(), 5 if verification == "Pending" else -2),
			),
		)
	scope_type = catalog("Project Scope Type", "Граница выпуска (демо)", enabled=1)
	project.append(
		"project_scopes",
		{
			"scope_title": "Первая линия поддержки",
			"scope_type": scope_type.name,
			"description": "Приём и обработка обращений первой линии.",
		},
	)
	project.save()


def snapshot():
	"""Return names and counts used by the acceptance report and browser capture."""
	if not frappe.local.site.endswith(".localhost"):
		frappe.throw("Run the demonstration on a localhost site.")
	project = frappe.get_doc("Project", PORTAL)
	goal = frappe.db.get_value("Goal", {"subject": GOAL_SUBJECT, "goal_owner": MANAGER})
	return {
		"project": project.name,
		"secondary_project": INTEGRATION,
		"shared_goal": {
			"name": goal,
			"subject": GOAL_SUBJECT,
			"projects": frappe.get_all("Goal Project", filters={"parent": goal}, pluck="project"),
			"requirements": frappe.get_all("Project Requirement Goal", filters={"goal": goal}, pluck="parent"),
		}
		if goal
		else None,
		"requirements": frappe.get_all(
			REQ, filters={"project": PORTAL}, fields=["name", "requirement_title", "status", "kind"]
		),
		"specifications": frappe.get_all(
			SPEC, filters={"project": PORTAL}, fields=["name", "title", "workflow_state"]
		),
		"templates": frappe.get_all(
			SPEC_TEMPLATE,
			filters={"title": ("in", ["Типовые требования к интеграции", "Контрольные точки обмена"])},
			fields=["name", "title", "workflow_state"],
		),
		"tasks": frappe.db.count("Task", {"project": PORTAL}),
		"results": frappe.get_all(
			RESULT,
			filters={"project": PORTAL},
			fields=["name", "title", "status", "progress", "planned_end_date"],
		),
		"constraints": len(project.project_constraints),
		"changes": frappe.get_all(
			CHANGE,
			filters={"project": ("in", [PORTAL, INTEGRATION])},
			fields=["name", "title", "project", "status", "creation"],
		),
	}


def add_demo_goal():
	requirements = [
		frappe.db.get_value(REQ, {"project": project, "requirement_title": title, "responsible": ANALYST})
		for project, title in (
			(PORTAL, "Приём обращений из корпоративного мессенджера"),
			(INTEGRATION, "Документировать контрольные ответы API"),
		)
	]
	if not all(requirements):
		frappe.throw("The synthetic demonstration requirements were not found.")
	goal = frappe.db.get_value("Goal", {"subject": GOAL_SUBJECT, "goal_owner": MANAGER})
	if not goal:
		frappe.get_doc("User", MANAGER).add_roles("Goal Owner")
		kind = "Качество обслуживания (демо)"
		catalog("Goal Type", kind, goal_type_name=kind)
		goal = make_goal(GOAL_SUBJECT, kind, MANAGER, (PORTAL, INTEGRATION)).name
	else:
		doc = frappe.get_doc("Goal", goal)
		if not doc.goal_projects and not doc.parameters:
			doc.append("parameters", goal_project_parameter((PORTAL, INTEGRATION)))
			doc.save()
	with actor(MANAGER):
		for name in requirements:
			doc = frappe.get_doc(REQ, name)
			description = f"{doc.requirement_title}. Проверка входит в программу приёмки сервисного портала."
			update_description = doc.description == f"<p>{description}</p>"
			add_link = not any(row.goal == goal for row in doc.goals)
			if update_description:
				doc.description = description
			if add_link:
				doc.append("goals", {"goal": goal})
			if update_description or add_link:
				doc.save()


def add_demo_report_data():
	for title, kind in (
		("Приём обращений из корпоративного мессенджера", "Каналы обращений (демо)"),
		("Синхронизация справочника подразделений", "Интеграции и справочники (демо)"),
	):
		name = frappe.db.get_value(REQ, {"project": PORTAL, "requirement_title": title, "responsible": ANALYST})
		if name:
			catalog("Requirement Kind", kind, enabled=1)
			with actor(ANALYST):
				doc = frappe.get_doc(REQ, name)
				if doc.kind != kind:
					doc.kind = kind
					doc.save()

	add_demo_drafts()


def add_demo_drafts():
	contact = frappe.db.get_value(
		CHANGE,
		{"project": PORTAL, "title": "Сократить обязательные поля анкеты", "owner": ANALYST},
		"initiator",
	)
	start = frappe.db.get_value("Project", PORTAL, "creation")
	plans = (
		(
			"Уточнить сообщение об ошибке при загрузке вложения",
			12,
			"Влияние на качество обслуживания (демо)",
			"Moderate",
			"Карточка заявки и каталог",
			"2 сценария",
			"Проверить подсказки для неподдерживаемого формата и слишком большого файла.",
		),
		(
			"Расширить выборку для проверки маршрутизации",
			7,
			"Влияние на трудозатраты команды (демо)",
			"Weak",
			"Правила маршрутизации и SLA",
			"3–5 часов",
			"Дополнить проверку обращениями второй линии и сменой дежурного.",
		),
	)
	for title, days, kind_title, level, result_title, estimate, explanation in plans:
		if frappe.db.exists(CHANGE, {"project": PORTAL, "title": title, "owner": ANALYST}):
			continue
		kind = catalog(
			"Project Change Relation Type",
			kind_title,
			enabled=1,
			reqd_explanation=1,
			reqd_estimation=1,
			reqd_link=1,
			link_doctype=RESULT,
		)
		target = frappe.db.get_value(RESULT, {"project": PORTAL, "title": result_title})
		# Set the simulated date on insert so Workflow can keep the original document identity.
		created = (start - timedelta(days=days)).replace(microsecond=0).isoformat(" ")
		with actor(ANALYST), patch("frappe.model.document.now", return_value=created):
			request = insert(
				CHANGE,
				project=PORTAL,
				title=title,
				initiator=contact,
				description=explanation,
				implementation_responsible=ANALYST,
				change_relations=[
					dict(
						type=kind.name,
						direction="target",
						level=level,
						estimation=estimate,
						explanation=explanation,
						link_doctype=RESULT,
						link=target,
					)
				],
			)
		share(request)


def seed():
	"""Create the two demonstration projects and their ordinary user accounts."""
	if (
		not frappe.local.site.endswith(".localhost")
		or not frappe.conf.mute_emails
		or not frappe.conf.pause_scheduler
	):
		frappe.throw("The scope demonstration requires a localhost site with email and scheduler disabled.")
	if frappe.db.exists("Project", PORTAL):
		add_demo_goal()
		add_demo_report_data()
		return snapshot()
	if frappe.db.exists("Project", INTEGRATION):
		frappe.throw("The secondary demonstration project identifier is already in use.")

	password = os.environ.get("DINEXT_SCOPE_DEMO_PASSWORD")
	for email, first, last in (
		(ANALYST, "Анна", "Савельева"),
		(MANAGER, "Сергей", "Лапин"),
		(ENGINEER, "Мария", "Рощина"),
	):
		if frappe.db.exists("User", email):
			frappe.throw(f"Demonstration account already exists: {email}")
		user_roles = project_user_roles()
		if email == MANAGER and frappe.db.exists("Role", "Dinext_Project_Manager"):
			user_roles.append({"role": "Dinext_Project_Manager"})
		insert(
			"User",
			email=email,
			first_name=first,
			last_name=last,
			user_type="System User",
			send_welcome_email=0,
			language="ru",
			roles=user_roles,
		)
		if password:
			from frappe.utils.password import update_password

			update_password(email, password)

	contact = insert(
		"Contact", first_name="Олег", last_name="Воронов", designation="Координатор службы поддержки"
	)
	share(contact)
	manager_role = (
		frappe.db.get_single_value("Project Scope Settings", "project_manager_role") or "Project Manager"
	)
	roles = (manager_role, "Аналитик сервиса (демо)", "Инженер интеграций (демо)", "Владелец процесса (демо)")
	for role in roles:
		catalog("Project Role", role, role_name=role, enabled=1)
	project = make_project("Единое окно сервисных заявок", PORTAL)
	secondary = make_project("Интеграция учётных систем", INTEGRATION, project.project_type)
	categories = {
		key: catalog("Project Deliverable Category", title, enabled=1).name
		for key, title in (("portal", "Сервисный портал"), ("exchange", "Интеграции"), ("data", "Отчётность"))
	}
	for target in (project, secondary):
		target.is_active = "Yes"
		for role, user in zip(roles[:3], (MANAGER, ANALYST, ENGINEER), strict=True):
			target.append(
				"custom_ts_details", dict(pt_role=role, pt_participant_type="User", pt_participant=user)
			)
		target.append("custom_contact_list", dict(contact=contact.name, project_role=roles[-1]))
		target.save()
		share(target)

	kind = catalog("Requirement Kind", "Сервисные требования (демо)", enabled=1)
	requirements, template = create_requirements(project, contact.name, kind.name)
	with actor(ANALYST):
		preview = preview_specification_template(secondary.name, template.name)
		apply_specification_template(
			secondary.name, template.name, "scope-demo-integration-v1", preview["digest"]
		)
	add_constraints(project, categories)
	results = create_results(project, requirements, categories, responsibility_rows(roles, contact.name))
	with actor(ANALYST):
		for key, status in (("form", "Done"), ("queue", "In Progress"), ("chat", "Cancelled")):
			requirements[key].reload().update({"status": status}).save()
	create_changes(project, secondary, contact.name, results)
	add_demo_goal()
	add_demo_report_data()
	return snapshot()
