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
REVISIONS = {
	"frappe": ("dinext_platform", "8c05aa33a2aa988ab7088809a1969e8ed84f5cb7"),
	"erpnext": ("dinext_erp", "bf4e2cac9fc015965b32bf49ad9e607da41d2229"),
	"doctype_permission": ("doctype_permission", "27d443d913b05ce029ce00fba0bf0951bf8fb3f1"),
	"frappe_comment_xt": ("frappe_comment_xt", "9b2e6b44a291f1cbdcf0808ffa34f250dbd0dfc6"),
	"dinext_common": ("dinext-common", "2968d847bd3c896a22c2936ad953a0cf5bea315a"),
	"dinext_projects": ("dinext-projects", "4fe48152b40bd91c87599ccbde02719bf76cbdbb"),
	"dinext_goals": ("dinext-goals", "4268a258973853e8ffe34fd890058e54802bb942"),
	# Common refreshes the approvals desk records against Timesheets during migrate.
	"hrms": ("hrms", "1b2060cc91bce2edb20be3f4e3fb08f4188f84a3"),
	"dinext_projects_pl": ("dinext-projects-pl", "996ac70ae1c1470d722d4b6ce2f578453587a0d6"),
	"dinext_timesheets": ("dinext-timesheets", "d1d5e22c2514aa68eb1ea378413cb935b7c98383"),
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
	run("bench", "--site", SITE, "migrate")
	run("bench", "use", SITE)
	run("bench", "build")


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
	total = 0
	failures = 0
	for path in RESULTS.glob("*.xml"):
		for suite in ET.parse(path).iter("testsuite"):
			total += int(suite.get("tests", 0))
			failures += int(suite.get("errors", 0)) + int(suite.get("failures", 0))
	if not total or failures:
		raise RuntimeError(f"Acceptance produced {total} tests with {failures} failures or errors.")


if __name__ == "__main__":
	RESULTS.mkdir()
	install()
	if sys.argv[1] == "server":
		run(
			"bench",
			"--site",
			SITE,
			"run-tests",
			"--app",
			"dinext_project_scope",
			"--skip-test-records",
			f"--junit-xml-output={RESULTS}/server.xml",
		)
	else:
		run_cypress()
	verify_report()
