"""Run Project Scope acceptance on a disposable bench at fixed component revisions."""

import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen

SOURCE = Path(__file__).resolve().parents[2]
WORK = Path(os.environ["RUNNER_TEMP"])
BENCH = WORK / "dinext-test-bench"
RESULTS = WORK / "scope-acceptance"
SITE = "localhost"
URL = "http://127.0.0.1:8000"
APP = "dinext_project_scope"
APP_FIXTURES = Path(APP) / "fixtures"
CATALOG_PROBE = "CI Catalog Roundtrip"
BLANK_ICON_TYPE = "Работа"
CATALOG_IDS = {
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
	"Project Scope Type": (
		"Географический",
		"Процессный",
		"Интеграционный",
		"Организационный",
		"Функциональный",
	),
	"Requirement Kind": (
		"Организационные",
		"Регуляторные",
		"Финансовые",
		"Функциональные",
		"Технические",
		"Стратегические",
	),
}
AUDIT_FIELDS = {"owner", "creation", "modified", "modified_by", "idx", "parent", "parentfield", "parenttype"}
REVISIONS = {
	"frappe": ("dinext_platform", "de9b663eb808e8ffbe7d38a0a3233a45745831a6"),
	"erpnext": ("dinext_erp", "548e80297397ba5d3ca4fb111a923fe784a37f4e"),
	"doctype_permission": ("doctype_permission", "43a18b9611d9a1fdf69a3c8d25bf953f468a146a"),
	"frappe_comment_xt": ("frappe_comment_xt", "9b2e6b44a291f1cbdcf0808ffa34f250dbd0dfc6"),
	"dinext_common": ("dinext-common", "2968d847bd3c896a22c2936ad953a0cf5bea315a"),
	"dinext_projects": ("dinext-projects", "d84952f158d074f6908c7f01c89a10c413436edf"),
	"dinext_goals": ("dinext-goals", "aa99d47783f80ad5e64e71008b913a8cc2af5724"),
}


def run(*args, cwd=BENCH):
	subprocess.run([str(argument) for argument in args], cwd=cwd, check=True, timeout=1800)


def checkout(app):
	repo, revision = REVISIONS[app]
	target = WORK / "scope-inputs" / app
	target.mkdir(parents=True)
	run("git", "init", target, cwd=WORK)
	run(
		"git",
		"fetch",
		"--no-tags",
		"--depth=1",
		f"https://github.com/Dinext-pro/{repo}.git",
		revision,
		cwd=target,
	)
	run("git", "checkout", "-b", "scope-ci-input", "FETCH_HEAD", cwd=target)
	return target


def install():
	framework = checkout("frappe")
	run(
		"bench",
		"init",
		BENCH,
		"--frappe-path",
		framework,
		"--frappe-branch",
		"scope-ci-input",
		"--skip-assets",
		"--skip-redis-config-generation",
		"--python",
		sys.executable,
		cwd=WORK,
	)
	config = BENCH / "sites" / "common_site_config.json"
	settings = json.loads(config.read_text())
	settings.update(
		db_host="127.0.0.1",
		db_port=3306,
		redis_cache="redis://127.0.0.1:6379/0",
		redis_queue="redis://127.0.0.1:6379/1",
		redis_socketio="redis://127.0.0.1:6379/2",
		developer_mode=1,
		server_script_enabled=1,
		enable_parallel_workflow_approval=1,
		pause_scheduler=1,
		mute_emails=True,
	)
	config.write_text(json.dumps(settings))
	for app in REVISIONS:
		if app != "frappe":
			run("bench", "get-app", "--skip-assets", app, checkout(app))
	run("bench", "get-app", "--skip-assets", "dinext_project_scope", SOURCE)
	run(BENCH / "env/bin/python", "-m", "pip", "install", "unittest-xml-reporting~=3.2.0")
	run(
		"bench",
		"new-site",
		SITE,
		"--db-host",
		"127.0.0.1",
		"--no-mariadb-socket",
		"--mariadb-root-password",
		"ci",
		"--admin-password",
		"ci-admin",
	)
	run("bench", "--site", SITE, "set-config", "allow_tests", "True", "--parse")
	run("bench", "--site", SITE, "set-config", "admin_password", "ci-admin")
	run("bench", "--site", SITE, "set-config", "host_name", URL)
	for app in REVISIONS:
		if app != "frappe":
			run("bench", "--site", SITE, "install-app", app)
	run("bench", "--site", SITE, "install-app", "dinext_project_scope")
	setup = {
		"language": "English",
		"email": "scope-test@example.com",
		"full_name": "Scope Test User",
		"password": "ci-admin",
		"country": "United States",
		"timezone": "America/New_York",
		"currency": "USD",
		"company_name": "Dinext Scope Test",
		"company_abbr": "DST",
		"chart_of_accounts": "Standard",
		"fy_start_date": "2026-01-01",
		"fy_end_date": "2026-12-31",
		"setup_demo": 0,
	}
	run(
		"bench",
		"--site",
		SITE,
		"execute",
		"frappe.desk.page.setup_wizard.setup_wizard.setup_complete",
		"--kwargs",
		json.dumps({"args": setup}),
	)
	# Build once for acceptance. The server suite probes repeat migration after its tests.
	run("bench", "use", SITE)
	run("bench", "build")


def read_catalog_data(directory):
	catalogs = {}
	for doctype in CATALOG_IDS:
		filename = f"{doctype.lower().replace(' ', '_')}.json"
		catalogs[doctype] = json.loads((directory / filename).read_text(encoding="utf-8"))
	return catalogs


def assert_catalog_ids(catalogs, stage):
	for doctype, ids in CATALOG_IDS.items():
		actual = sorted(row["name"] for row in catalogs[doctype])
		if actual != sorted(ids):
			raise RuntimeError(f"{stage} has unexpected {doctype} IDs: {actual!r}")


def catalog_values(row, *, child=False):
	ignored = AUDIT_FIELDS | {"doctype", "docstatus", "name"} if child else AUDIT_FIELDS
	return {
		field: [catalog_values(item, child=True) for item in value] if isinstance(value, list) else value
		for field, value in row.items()
		if field not in ignored
	}


def catalog_snapshot_values(catalogs):
	return {
		doctype: {row["name"]: catalog_values(row) for row in rows}
		for doctype, rows in catalogs.items()
	}


def matches_shipped_values(shipped, installed):
	# Import can fill defaults for fields that are absent from fixture JSON.
	for field, expected in shipped.items():
		actual = installed.get(field)
		if isinstance(expected, list):
			if not isinstance(actual, list) or len(expected) != len(actual):
				return False
			children_match = (
				matches_shipped_values(left, right) for left, right in zip(expected, actual, strict=True)
			)
			if not all(children_match):
				return False
		elif expected != actual and (expected not in (None, "") or actual not in (None, "")):
			return False
	return True


def assert_same_catalog_values(expected, actual, stage):
	for doctype in CATALOG_IDS:
		record_names = expected[doctype].keys() | actual[doctype].keys()
		changed = sorted(
			name for name in record_names if expected[doctype].get(name) != actual[doctype].get(name)
		)
		if changed:
			raise RuntimeError(f"{stage} changed values for {doctype}: {changed!r}")


def execute_catalog_probe(method, *args):
	result = subprocess.run(
		[
			"bench",
			"--site",
			SITE,
			"execute",
			f"{APP}.tests.catalog_migration_acceptance.{method}",
			"--args",
			repr([list(CATALOG_IDS), *args]),
		],
		cwd=BENCH,
		check=True,
		text=True,
		stdout=subprocess.PIPE,
		timeout=120,
	)
	return json.loads(result.stdout.strip().splitlines()[-1])


def export_catalog_data():
	fixtures_path = BENCH / "apps" / APP / APP_FIXTURES
	if not fixtures_path.resolve().is_relative_to(BENCH.resolve()):
		raise RuntimeError("The fixture exporter must write to the disposable bench.")
	original = {path.name: path.read_bytes() for path in fixtures_path.glob("*.json")}
	repository = {path.name: path.read_bytes() for path in (SOURCE / APP_FIXTURES).glob("*.json")}
	if not original or original != repository:
		raise RuntimeError("Bench fixtures do not match the checked-out app.")
	try:
		run("bench", "--site", SITE, "export-fixtures", "--app", APP)
		return read_catalog_data(fixtures_path)
	finally:
		for path in fixtures_path.glob("*.json"):
			if path.name not in original:
				path.unlink()
		for name, data in original.items():
			(fixtures_path / name).write_bytes(data)


def run_server_acceptance():
	report = {"site": SITE, "outcome": "failed", "migrations": []}
	try:
		shipped = read_catalog_data(SOURCE / APP_FIXTURES)
		assert_catalog_ids(shipped, "Checked-out fixtures")
		factory = execute_catalog_probe("snapshot")
		report["clean_install"] = catalog_snapshot_values(factory)
		assert_catalog_ids(factory, "Clean installation")
		shipped_values = catalog_snapshot_values(shipped)
		for doctype, records in shipped_values.items():
			for name, row in records.items():
				if not matches_shipped_values(row, report["clean_install"][doctype][name]):
					raise RuntimeError(f"Clean installation changed fixture settings in {doctype} {name!r}.")

		run(
			"bench",
			"--site",
			SITE,
			"run-tests",
			"--app",
			APP,
			"--skip-test-records",
			f"--junit-xml-output={RESULTS}/server.xml",
		)

		prepared = execute_catalog_probe("configure", CATALOG_PROBE, BLANK_ICON_TYPE)
		installed = catalog_snapshot_values(prepared)
		report["before_migrate"] = installed
		expected_export = {
			doctype: {name: installed[doctype][name] for name in ids}
			for doctype, ids in CATALOG_IDS.items()
		}
		for doctype in CATALOG_IDS:
			if CATALOG_PROBE not in installed[doctype]:
				raise RuntimeError(f"Missing extra user record in {doctype}.")
			if expected_export[doctype] == report["clean_install"][doctype]:
				raise RuntimeError(f"No customized shipped record in {doctype}.")

		exported = export_catalog_data()
		report["export"] = catalog_snapshot_values(exported)
		assert_catalog_ids(exported, "Native fixture export")
		assert_same_catalog_values(expected_export, report["export"], "Native fixture export")

		type_doctype = "Project Deliverable Type"
		factory_icon = shipped_values[type_doctype][BLANK_ICON_TYPE]["icon"]
		if not factory_icon:
			raise RuntimeError("The fixture must ship a factory result icon.")
		blank_icon = installed[type_doctype][BLANK_ICON_TYPE]
		if blank_icon["icon"]:
			raise RuntimeError("The fallback test must start with an empty result icon.")
		expected = {
			**installed,
			type_doctype: {
				**installed[type_doctype],
				BLANK_ICON_TYPE: {**blank_icon, "icon": factory_icon},
			},
		}
		for _ in range(2):
			run("bench", "--site", SITE, "migrate", "--skip-search-index")
			migrated = catalog_snapshot_values(execute_catalog_probe("snapshot"))
			report["migrations"].append(migrated)
			assert_same_catalog_values(expected, migrated, "Repeated migrate")
		report["outcome"] = "passed"
	except Exception as error:
		report["error"] = str(error)
		raise
	finally:
		(RESULTS / "catalog-roundtrip.json").write_text(
			json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
		)


def wait_for_site(server):
	for _ in range(60):
		if server.poll() is not None:
			break
		try:
			with urlopen(f"{URL}/api/method/ping", timeout=2) as response:
				if json.load(response)["message"] == "pong":
					return
		except OSError:
			time.sleep(1)
	raise RuntimeError("The disposable test site did not start.")


def run_cypress():
	# The pinned Projects policy references this role without shipping its record.
	run(
		"bench",
		"--site",
		SITE,
		"execute",
		"dinext_project_scope.tests.scope_ui_test_helpers.ensure_data_import_role",
	)
	legacy_task_asset = BENCH / "apps/dinext_common/dinext_common/public/js/form_conflict_merge.js"
	if not legacy_task_asset.is_file():
		# The disposable site can inherit a client script for an asset removed by Common.
		run(
			"bench",
			"--site",
			SITE,
			"execute",
			"frappe.db.set_value",
			"--args",
			json.dumps(
				[
					"Client Script",
					{
						"name": "Utility-FormConflictMerge-Task",
						"dt": "Task",
						"script": ["like", "%/js/form_conflict_merge.js%"],
					},
					"enabled",
					0,
				]
			),
		)
		run("bench", "--site", SITE, "clear-cache")
	with (RESULTS / "web.log").open("w") as output:
		server = subprocess.Popen(
			["bench", "--site", SITE, "serve", "--port", "8000", "--noreload"],
			cwd=BENCH,
			env=dict(os.environ, DEV_SERVER="1"),
			stdout=output,
			stderr=subprocess.STDOUT,
		)
		try:
			wait_for_site(server)
			run(
				"xvfb-run",
				"-a",
				"-s",
				"-screen 0 1600x1000x24",
				"env",
				f"CYPRESS_screenshotsFolder={RESULTS}/screenshots",
				f"CYPRESS_downloadsFolder={RESULTS}/downloads",
				"bench",
				"--site",
				SITE,
				"run-ui-tests",
				"dinext_project_scope",
				"--headless",
				"--browser",
				"electron",
				"--reporter",
				"junit",
				"--reporter-options",
				f"mochaFile={RESULTS}/ui-[hash].xml",
			)
		finally:
			server.terminate()
			server.wait(timeout=10)


def verify_report():
	counts = dict(executed=0, passed=0, failed=0, skipped=0)
	reports = {}
	for path in sorted(RESULTS.glob("*.xml")):
		cases = []
		for case in ET.parse(path).iter("testcase"):
			if case.find("skipped") is not None:
				status = "skipped"
			elif case.find("failure") is not None or case.find("error") is not None:
				status = "failed"
			else:
				status = "passed"
			counts[status] += 1
			cases.append(dict(name=case.get("name"), suite=case.get("classname"), status=status))
		reports[path.name] = cases
	counts["executed"] = counts["passed"] + counts["failed"]
	source_commit = subprocess.check_output(
		["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True, timeout=30
	).strip()
	summary = dict(source_commit=source_commit, counts=counts, reports=reports)
	(RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
	print(f"Acceptance at {source_commit}: {counts}", flush=True)
	if not counts["executed"] or counts["failed"] or counts["skipped"]:
		raise RuntimeError("Acceptance must execute all reported cases and pass without skips.")


if __name__ == "__main__":
	RESULTS.mkdir()
	install()
	try:
		if sys.argv[1] == "server":
			run_server_acceptance()
		else:
			run_cypress()
	finally:
		verify_report()
