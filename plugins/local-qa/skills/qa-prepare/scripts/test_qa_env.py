#!/usr/bin/env python3
"""Tests of qa_env.py: `python3 test_qa_env.py` (standard library only).

`docker` and `lsof` are stubbed through PATH (a fixture JSON file says what runs and every call is logged);
git, ps and the processes cleanup stops are real, so the PID checks run against the real system.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "qa_env.py")
sys.path.insert(0, HERE)
import qa_env  # noqa: E402

DOCKER_STUB = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    arguments = sys.argv[1:]
    with open(os.environ["QA_STUB_LOG"], "a") as log:
        log.write(json.dumps(["docker"] + arguments) + "\\n")
    with open(os.environ["QA_STUB"]) as handle:
        fixture = json.load(handle)
    if fixture.get("docker") == "down":
        sys.stderr.write("Cannot connect to the Docker daemon\\n")
        sys.exit(1)
    def matches(row, filters):
        for item in filters:
            key, _, value = item.partition("=")
            if key == "id" and not row["id"].startswith(value):
                return False
            if key == "label":
                label, _, wanted = value.partition("=")
                if row.get("labels", {}).get(label) != wanted:
                    return False
        return True
    if arguments[0] == "ps":
        filters = [arguments[index + 1] for index, item in enumerate(arguments) if item == "--filter"]
        for row in fixture.get("containers", []):
            if row.get("state", "running") != "running" and "-a" not in arguments:
                continue
            if not matches(row, filters):
                continue
            labels = row.get("labels", {})
            print("\\t".join([row["id"], row["name"], row.get("image", "image"), row.get("ports", ""),
                             labels.get("com.docker.compose.project", ""),
                             labels.get("com.docker.compose.project.working_dir", ""),
                             labels.get("com.docker.compose.service", "")]))
        sys.exit(0)
    if arguments[0] in ("volume", "network") and arguments[1] == "ls":
        project = arguments[-1].split("=", 2)[-1]
        for item in fixture.get(arguments[0] + "s", {}).get(project, []):
            print(item)
        sys.exit(0)
    if arguments[0] in ("stop", "rm") and arguments[-1] in fixture.get("failing", []):
        sys.exit(1)
    sys.exit(0)
    """
)

LSOF_STUB = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    arguments = sys.argv[1:]
    with open(os.environ["QA_STUB_LOG"], "a") as log:
        log.write(json.dumps(["lsof"] + arguments) + "\\n")
    with open(os.environ["QA_STUB"]) as handle:
        fixture = json.load(handle)
    listeners = fixture.get("listeners", [])
    if "-iTCP" in arguments:
        if not listeners:
            sys.exit(1)
        for item in listeners:
            print("p%d" % item["pid"])
            print("c%s" % item["command"])
            print("f%d" % 3)
            print("n%s:%d" % (item.get("address", "*"), item["port"]))
        sys.exit(0)
    if "cwd" in arguments:
        pids = arguments[arguments.index("-p") + 1].split(",")
        for item in listeners:
            if str(item["pid"]) in pids and "cwd" in item:
                print("p%d" % item["pid"])
                print("fcwd")
                print("n%s" % item["cwd"])
                pids.remove(str(item["pid"]))
        sys.exit(0)
    sys.exit(1)
    """
)


def git(directory, *arguments):
    subprocess.run(
        ["git", "-C", directory, *arguments],
        check=True,
        capture_output=True,
        env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"),
    )


def make_repository(path):
    os.makedirs(path)
    git(path, "init", "-q", "-b", "main")
    with open(os.path.join(path, "README"), "w") as handle:
        handle.write("x\n")
    git(path, "add", "README")
    git(path, "commit", "-q", "-m", "init")


def free_test_port():
    """A port nothing listens on right now, high enough to stay clear of the machine's services."""
    for port in range(41000, 49000, 37):
        if qa_env.port_is_free(port) and qa_env.port_is_free(port + 1) and qa_env.port_is_free(port + 2):
            return port
    raise RuntimeError("no free port")


class Machine(unittest.TestCase):
    """Two projects on one machine: alpha (main checkout + worktree feature-x, the QA's) and beta (another one)."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="qa-env-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.alpha = os.path.join(self.root, "alpha")
        self.beta = os.path.join(self.root, "beta")
        make_repository(self.alpha)
        make_repository(self.beta)
        self.worktree = os.path.join(self.alpha, ".claude", "worktrees", "feature-x")
        git(self.alpha, "worktree", "add", "-q", "-b", "feat/x", "--no-track", self.worktree, "main")
        self.other_worktree = os.path.join(self.alpha, ".claude", "worktrees", "other")
        git(self.alpha, "worktree", "add", "-q", "-b", "feat/other", "--no-track", self.other_worktree, "main")
        for directory in ("infra", "backend", "frontend"):
            for base in (self.alpha, self.worktree, self.other_worktree, self.beta):
                os.makedirs(os.path.join(base, directory), exist_ok=True)
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        for name, body in (("docker", DOCKER_STUB), ("lsof", LSOF_STUB)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as handle:
                handle.write(body.replace("/usr/bin/env python3", sys.executable, 1))
            os.chmod(path, 0o755)
        self.fixture_path = os.path.join(self.root, "fixture.json")
        self.log_path = os.path.join(self.root, "calls.log")
        self.port = free_test_port()
        self.fixture = {"containers": [], "listeners": []}
        self.processes = []

    @staticmethod
    def kill_quietly(pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    @staticmethod
    def running(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    # helpers

    def container(self, identifier, name, project, working_dir, service, ports, state="running"):
        self.fixture["containers"].append(
            {
                "id": identifier,
                "name": name,
                "state": state,
                "ports": ports,
                "labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.project.working_dir": working_dir,
                    "com.docker.compose.service": service,
                },
            }
        )

    def listener(self, pid, command, port, cwd):
        self.fixture["listeners"].append({"pid": pid, "command": command, "port": port, "cwd": cwd})

    def spawn(self, cwd, new_session=True, with_child=False):
        code = "import time; time.sleep(120)"
        if with_child:
            code = (
                "import subprocess, sys, time; child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
                " print(child.pid, flush=True); time.sleep(120)"
            )
        process = subprocess.Popen(
            [sys.executable, "-c", code], cwd=cwd, start_new_session=new_session, stdout=subprocess.PIPE if with_child else None
        )
        if with_child:
            process.child_pid = int(process.stdout.readline())
            self.addCleanup(self.kill_quietly, process.child_pid)
        self.processes.append(process)
        deadline = time.monotonic() + 5
        while qa_env.process_identity(process.pid) is None and time.monotonic() < deadline:
            time.sleep(0.05)
        return process

    def qa(self, *arguments, root=None, expect=0):
        with open(self.fixture_path, "w") as handle:
            json.dump(self.fixture, handle)
        environment = dict(
            os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], QA_STUB=self.fixture_path, QA_STUB_LOG=self.log_path
        )
        completed = subprocess.run(
            [sys.executable, SCRIPT, "--root", root or self.worktree, *arguments],
            capture_output=True,
            text=True,
            env=environment,
            timeout=120,
        )
        self.assertEqual(completed.returncode, expect, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def calls(self, program):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as handle:
            return [json.loads(line) for line in handle if json.loads(line)[0] == program]

    def write_spec(self, migrations=()):
        spec = {
            "services": [
                {"name": "db", "kind": "container", "compose_service": "postgres", "port": self.port, "container_port": 5432, "shared": True, "database": True},
                {"name": "backend", "kind": "process", "port": self.port + 1000},
                {"name": "frontend", "kind": "process", "port": self.port + 2000},
            ],
            "migrations": list(migrations),
        }
        path = os.path.join(self.root, "spec.json")
        with open(path, "w") as handle:
            json.dump(spec, handle)
        return path

    def service(self, result, name):
        return next(item for item in result["services"] if item["name"] == name)

    def started_json(self):
        path = os.path.join(self.worktree, ".claude", "qa", "started.json")
        if not os.path.exists(path):
            return None
        with open(path) as handle:
            return json.load(handle)

    def assert_nothing_stopped(self):
        for call in self.calls("docker"):
            self.assertNotIn(call[1], ("stop", "rm", "restart", "kill", "compose", "start", "update"), call)


class LocateTest(Machine):
    def test_main_checkout_worktree_and_outside(self):
        self.assertEqual(qa_env.locate(os.path.join(self.alpha, "infra")), {"worktree": self.alpha, "project": self.alpha})
        self.assertEqual(
            qa_env.locate(os.path.join(self.worktree, "backend")), {"worktree": self.worktree, "project": self.alpha}
        )
        self.assertIsNone(qa_env.locate(self.root))
        self.assertIsNone(qa_env.locate("relative/path"))
        self.assertIsNone(qa_env.locate(os.path.join(self.root, "missing")))

    def test_compose_project_names_one_per_worktree(self):
        self.assertEqual(qa_env.compose_project_name({"worktree": self.alpha, "project": self.alpha}), "qa-alpha")
        self.assertEqual(
            qa_env.compose_project_name({"worktree": self.worktree, "project": self.alpha}), "qa-alpha-feature-x"
        )
        self.assertEqual(qa_env.compose_project_name({"worktree": "/x/Feat.Y", "project": "/p/My App"}), "qa-my-app-feat-y")


class ParsePortsTest(unittest.TestCase):
    def test_both_families_count_once(self):
        self.assertEqual(
            qa_env.parse_ports("0.0.0.0:5432->5432/tcp, :::5432->5432/tcp"),
            [{"host_port": 5432, "container_port": 5432, "protocol": "tcp"}],
        )

    def test_range_and_unpublished(self):
        self.assertEqual(
            qa_env.parse_ports("0.0.0.0:7000-7001->8000-8001/tcp, 9000/tcp"),
            [
                {"host_port": 7000, "container_port": 8000, "protocol": "tcp"},
                {"host_port": 7001, "container_port": 8001, "protocol": "tcp"},
            ],
        )

    def test_remapped_port(self):
        self.assertEqual(
            qa_env.parse_ports("127.0.0.1:15432->5432/tcp"),
            [{"host_port": 15432, "container_port": 5432, "protocol": "tcp"}],
        )


class GlobTest(unittest.TestCase):
    def test_double_star_crosses_directories_single_does_not(self):
        pattern = qa_env.glob_to_regex("backend/**/db/migration/*.sql")
        self.assertTrue(pattern.match("backend/src/main/resources/db/migration/V2__x.sql"))
        self.assertTrue(pattern.match("backend/db/migration/V2__x.sql"))
        self.assertFalse(pattern.match("backend/db/migration/old/V2__x.sql"))
        self.assertFalse(pattern.match("frontend/db/migration/V2__x.sql"))
        self.assertTrue(qa_env.glob_to_regex("migrations/**").match("migrations/a/b.sql"))
        self.assertFalse(qa_env.glob_to_regex("V?.sql").match("V10.sql"))
        self.assertTrue(qa_env.glob_to_regex("V?.sql").match("V1.sql"))
        self.assertFalse(qa_env.glob_to_regex("a?b").match("a/b"))


class FreePortTest(unittest.TestCase):
    def test_a_bound_port_and_a_taken_port_are_skipped(self):
        start = free_test_port()
        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind(("127.0.0.1", start))
        listening.listen()
        try:
            self.assertFalse(qa_env.port_is_free(start))
            self.assertEqual(qa_env.free_port(start, {start + 1}), start + 2)
        finally:
            listening.close()
        self.assertEqual(qa_env.free_port(start, set()), start)


class InventoryTest(Machine):
    def test_another_projects_container_on_the_default_port_is_reported_as_theirs(self):
        self.container("c-beta", "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.listener(501, "com.docker.backend", self.port, "/")
        result = self.qa("inventory")
        container = result["containers"][0]
        self.assertEqual((container["project"], container["worktree"]), (self.beta, self.beta))
        self.assertFalse(container["same_project"])
        self.assertEqual(result["listeners"][0]["container"], "beta-postgres")
        self.assertEqual(result["listeners"][0]["project"], self.beta)
        self.assertEqual(result["context"]["compose_project"], "qa-alpha-feature-x")
        self.assert_nothing_stopped()

    def test_listeners_are_mapped_to_project_and_worktree(self):
        self.listener(601, "java", self.port, os.path.join(self.worktree, "backend"))
        self.listener(602, "node", self.port + 1, os.path.join(self.alpha, "frontend"))
        self.listener(603, "ControlCenter", self.port + 2, "/")
        listeners = {item["pid"]: item for item in self.qa("inventory")["listeners"]}
        self.assertEqual((listeners[601]["worktree"], listeners[601]["same_worktree"]), (self.worktree, True))
        self.assertEqual(
            (listeners[602]["project"], listeners[602]["same_project"], listeners[602]["same_worktree"]),
            (self.alpha, True, False),
        )
        self.assertEqual((listeners[603]["project"], listeners[603]["same_project"]), (None, False))

    def test_docker_down_is_reported_not_fatal(self):
        self.fixture["docker"] = "down"
        result = self.qa("inventory")
        self.assertEqual((result["docker"], result["containers"]), ("unavailable", []))

    def test_outside_a_repository_is_refused(self):
        self.assertIn("not inside a git repository", self.qa("inventory", root=self.root, expect=2)["error"])


class PlanTest(Machine):
    def test_other_projects_services_on_default_ports_start_ours_on_free_ports(self):
        self.container("c-beta", "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.listener(501, "com.docker.backend", self.port, "/")
        self.listener(502, "node", self.port + 2000, os.path.join(self.beta, "frontend"))
        result = self.qa("plan", "--spec", self.write_spec())
        database = self.service(result, "db")
        self.assertEqual(database["action"], "start")
        self.assertEqual(database["port"], self.port + 1)
        self.assertEqual(database["compose_project"], "qa-alpha-feature-x")
        self.assertEqual(database["default_port_taken_by"]["project"], self.beta)
        frontend = self.service(result, "frontend")
        self.assertEqual((frontend["action"], frontend["port"]), ("start", self.port + 2001))
        self.assertEqual(frontend["default_port_taken_by"]["pid"], 502)
        self.assertEqual(self.service(result, "backend"), {"name": "backend", "action": "start", "port": self.port + 1000})
        self.assert_nothing_stopped()

    def test_shared_services_of_the_same_project_reused_code_services_of_another_worktree_not(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.listener(501, "com.docker.backend", self.port, "/")
        self.listener(601, "java", self.port + 1000, os.path.join(self.alpha, "backend"))
        result = self.qa("plan", "--spec", self.write_spec())
        self.assertEqual(
            self.service(result, "db"),
            {"name": "db", "action": "reuse", "port": self.port, "started_by_this_qa": False, "container": "alpha-postgres"},
        )
        backend = self.service(result, "backend")
        self.assertEqual((backend["action"], backend["port"]), ("start", self.port + 1001))
        self.assertEqual(backend["default_port_taken_by"]["worktree"], self.alpha)
        self.assertFalse(result["pending_migration"])

    def test_the_worktrees_own_backend_is_reused(self):
        self.listener(601, "java", self.port + 1000, os.path.join(self.worktree, "backend"))
        backend = self.service(self.qa("plan", "--spec", self.write_spec()), "backend")
        self.assertEqual(backend, {"name": "backend", "action": "reuse", "port": self.port + 1000, "started_by_this_qa": False, "pid": 601})

    def test_a_shared_container_published_on_another_port_is_reused_there(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (self.port + 5))
        self.assertEqual(self.service(self.qa("plan", "--spec", self.write_spec()), "db")["port"], self.port + 5)

    def test_a_pending_migration_starts_an_isolated_database(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        os.makedirs(os.path.join(self.worktree, "backend", "db", "migration"))
        with open(os.path.join(self.worktree, "backend", "db", "migration", "V2__add.sql"), "w") as handle:
            handle.write("alter table x add y int;\n")
        git(self.worktree, "add", "backend")
        git(self.worktree, "commit", "-q", "-m", "migration")
        result = self.qa("plan", "--spec", self.write_spec(["backend/**/migration/*.sql"]), "--base", "main")
        self.assertTrue(result["pending_migration"])
        self.assertEqual(result["migrations"], ["backend/db/migration/V2__add.sql"])
        database = self.service(result, "db")
        self.assertEqual(
            (database["action"], database["isolated"], database["compose_project"], database["port"]),
            ("start", True, "qa-alpha-feature-x", self.port + 1),
        )
        self.assertNotIn("isolated", self.service(result, "backend"))
        self.assert_nothing_stopped()

    def test_ports_chosen_in_one_plan_do_not_collide(self):
        self.listener(701, "node", self.port, os.path.join(self.beta, "frontend"))
        path = os.path.join(self.root, "two.json")
        with open(path, "w") as handle:
            json.dump({"services": [{"name": "api", "port": self.port}, {"name": "web", "port": self.port + 1}]}, handle)
        result = self.qa("plan", "--spec", path)
        self.assertEqual([item["port"] for item in result["services"]], [self.port + 1, self.port + 2])

    def test_a_container_port_is_never_taken_for_a_process_of_the_worktree(self):
        self.container("c-wt", "alpha-api", "alpha-wt", os.path.join(self.worktree, "infra"), "api", "0.0.0.0:%d->8080/tcp" % (self.port + 1000))
        self.listener(501, "com.docker.backend", self.port + 1000, "/")
        backend = self.service(self.qa("plan", "--spec", self.write_spec()), "backend")
        self.assertEqual((backend["action"], backend["port"]), ("start", self.port + 1001))

    def test_an_uncommitted_migration_is_pending_too_and_other_files_are_not(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        spec = self.write_spec(["backend/**/migration/*.sql"])
        with open(os.path.join(self.worktree, "backend", "Service.java"), "w") as handle:
            handle.write("class Service {}\n")
        self.assertEqual(self.service(self.qa("plan", "--spec", spec, "--base", "main"), "db")["action"], "reuse")
        os.makedirs(os.path.join(self.worktree, "backend", "migration"))
        with open(os.path.join(self.worktree, "backend", "migration", "V3__x.sql"), "w") as handle:
            handle.write("select 1;\n")
        result = self.qa("plan", "--spec", spec, "--base", "main")
        self.assertEqual(result["migrations"], ["backend/migration/V3__x.sql"])
        self.assertEqual(self.service(result, "db")["action"], "start")

    def test_a_declared_migration_isolates_without_a_diff(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        result = self.qa("plan", "--spec", self.write_spec(), "--pending-migration")
        self.assertTrue(self.service(result, "db")["isolated"])

    def test_an_unknown_base_is_refused(self):
        self.qa("plan", "--spec", self.write_spec(["x/**"]), "--base", "no-such-ref", expect=2)

    def test_another_worktrees_qa_database_is_not_reused_ours_is(self):
        self.container("c-other", "qa-alpha-other-postgres-1", "qa-alpha-other", os.path.join(self.other_worktree, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.assertEqual(self.service(self.qa("plan", "--spec", self.write_spec()), "db")["action"], "start")
        self.container("c-ours", "qa-alpha-feature-x-postgres-1", "qa-alpha-feature-x", os.path.join(self.worktree, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (self.port + 1))
        database = self.service(self.qa("plan", "--spec", self.write_spec(), "--pending-migration"), "db")
        self.assertEqual(
            (database["action"], database["port"], database["started_by_this_qa"], database["recorded"]),
            ("reuse", self.port + 1, True, False),
        )

    def test_a_container_running_the_changes_code_is_reused_only_from_this_worktree(self):
        path = os.path.join(self.root, "api.json")
        with open(path, "w") as handle:
            json.dump({"services": [{"name": "api", "kind": "container", "compose_service": "api", "port": self.port}]}, handle)
        self.container("c-main", "alpha-api", "alpha", os.path.join(self.alpha, "infra"), "api", "0.0.0.0:%d->%d/tcp" % (self.port, self.port))
        self.assertEqual(self.service(self.qa("plan", "--spec", path), "api")["action"], "start")
        self.container("c-wt", "feature-x-api", "feature-x", os.path.join(self.worktree, "infra"), "api", "0.0.0.0:%d->%d/tcp" % (self.port + 1, self.port))
        api = self.service(self.qa("plan", "--spec", path), "api")
        self.assertEqual((api["action"], api["container"], api["port"]), ("reuse", "feature-x-api", self.port + 1))

    def test_a_backend_this_qa_started_is_reused_while_it_runs(self):
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port + 1001, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port + 1001))
        backend = self.service(self.qa("plan", "--spec", self.write_spec()), "backend")
        self.assertEqual((backend["action"], backend["port"], backend["started_by_this_qa"]), ("reuse", self.port + 1001, True))
        process.kill()
        process.wait()
        self.fixture["listeners"] = []
        backend = self.service(self.qa("plan", "--spec", self.write_spec()), "backend")
        self.assertEqual((backend["action"], backend["port"]), ("start", self.port + 1000))

    def test_a_spec_without_services_is_refused(self):
        path = os.path.join(self.root, "empty.json")
        with open(path, "w") as handle:
            json.dump({"services": []}, handle)
        self.qa("plan", "--spec", path, expect=2)


class RecordTest(Machine):
    def test_a_container_of_another_compose_project_is_refused(self):
        self.container("c-alpha", "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.assertIn("not started by this QA", self.qa("record", "container", "--name", "db", "--id", "c-alpha", expect=2)["error"])
        self.assertIsNone(self.started_json())

    def test_a_container_of_this_qa_is_recorded_by_service(self):
        self.container("c-ours", "qa-alpha-feature-x-postgres-1", "qa-alpha-feature-x", os.path.join(self.worktree, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.qa("record", "container", "--name", "db", "--service", "postgres")
        entries = self.started_json()["entries"]
        self.assertEqual(
            [(entry["kind"], entry["id"], entry["compose_project"], entry["port"]) for entry in entries],
            [("container", "c-ours", "qa-alpha-feature-x", self.port)],
        )

    def test_a_container_without_compose_labels_needs_this_qas_name(self):
        self.fixture["containers"].append({"id": "c-plain", "name": "postgres-test", "ports": "", "labels": {}})
        self.fixture["containers"].append({"id": "c-named", "name": "qa-alpha-feature-x-db", "ports": "", "labels": {}})
        self.qa("record", "container", "--name", "db", "--id", "c-plain", expect=2)
        self.qa("record", "container", "--name", "db", "--id", "c-named")
        self.assertEqual([entry["id"] for entry in self.started_json()["entries"]], ["c-named"])

    def test_a_process_outside_the_worktree_is_refused(self):
        process = self.spawn(os.path.join(self.alpha, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.alpha, "backend"))
        self.assertIn("outside this worktree", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])
        self.assertIsNone(self.started_json())

    def test_a_process_of_the_worktree_is_recorded_with_its_identity(self):
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        entry = self.started_json()["entries"][0]
        self.assertEqual((entry["pid"], entry["port"], entry["process_group"]), (process.pid, self.port, process.pid))
        self.assertIn("time.sleep(120)", entry["command"])
        self.assertTrue(entry["started"])
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        self.assertEqual(len(self.started_json()["entries"]), 1, "the same process recorded again replaces its entry")


class CleanupTest(Machine):
    def prepare(self):
        """This QA started a backend (own session), a frontend (shared process group) and a database container;
        another dev server of the same worktree and beta's database were already running."""
        ours_backend = self.spawn(os.path.join(self.worktree, "backend"), with_child=True)
        ours_frontend = self.spawn(os.path.join(self.worktree, "frontend"), new_session=False)
        not_ours = self.spawn(os.path.join(self.worktree, "frontend"))
        self.listener(ours_backend.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.listener(ours_frontend.pid, "python3", self.port + 1, os.path.join(self.worktree, "frontend"))
        self.listener(not_ours.pid, "python3", self.port + 2, os.path.join(self.worktree, "frontend"))
        self.container("c-ours", "qa-alpha-feature-x-postgres-1", "qa-alpha-feature-x", os.path.join(self.worktree, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (self.port + 3))
        self.container("c-beta", "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (self.port + 4))
        self.fixture["volumes"] = {"qa-alpha-feature-x": ["qa-alpha-feature-x_data"], "beta": ["beta_data"]}
        self.fixture["networks"] = {"qa-alpha-feature-x": ["qa-alpha-feature-x_default"], "beta": ["beta_default"]}
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        self.qa("record", "process", "--name", "frontend", "--port", str(self.port + 1))
        self.qa("record", "container", "--name", "db", "--service", "postgres")
        return ours_backend, ours_frontend, not_ours

    def test_cleanup_stops_exactly_what_started_json_lists(self):
        ours_backend, ours_frontend, not_ours = self.prepare()
        result = self.qa("cleanup")
        self.assertEqual(ours_backend.wait(timeout=15), -15)
        self.assertEqual(ours_frontend.wait(timeout=15), -15)
        deadline = time.monotonic() + 5
        while self.running(ours_backend.child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.running(ours_backend.child_pid), "the backend's process group is stopped with it")
        self.assertIsNone(not_ours.poll())
        self.assertEqual([item["outcome"][:7] for item in result["stopped"]], ["stopped"] * 3)
        writes = [call[1:] for call in self.calls("docker") if call[1] in ("stop", "rm") or call[2:3] == ["rm"]]
        self.assertEqual(
            writes,
            [
                ["stop", "c-ours"],
                ["rm", "-v", "c-ours"],
                ["volume", "rm", "qa-alpha-feature-x_data"],
                ["network", "rm", "qa-alpha-feature-x_default"],
            ],
        )
        self.assertIsNone(self.started_json())

    def test_a_reused_pid_is_not_signalled(self):
        ours_backend, _, _ = self.prepare()
        path = os.path.join(self.worktree, ".claude", "qa", "started.json")
        with open(path) as handle:
            started = json.load(handle)
        started["entries"][0]["started"] = "Thu Jan  1 00:00:00 1970"
        with open(path, "w") as handle:
            json.dump(started, handle)
        result = self.qa("cleanup")
        self.assertTrue(result["stopped"][0]["outcome"].startswith("skipped"))
        self.assertIsNone(ours_backend.poll())

    def test_dry_run_stops_nothing(self):
        ours_backend, ours_frontend, _ = self.prepare()
        result = self.qa("cleanup", "--dry-run")
        self.assertEqual([item["outcome"] for item in result["stopped"]], ["would stop"] * 3)
        self.assertIsNone(ours_backend.poll())
        self.assertIsNone(ours_frontend.poll())
        self.assertEqual([call for call in self.calls("docker") if call[1] in ("stop", "rm") or call[2:3] == ["rm"]], [])
        self.assertEqual(len(self.started_json()["entries"]), 3)

    def test_a_container_that_fails_to_stop_stays_listed(self):
        self.prepare()
        self.fixture["failing"] = ["c-ours"]
        result = self.qa("cleanup", expect=1)
        self.assertEqual(result["stopped"][2]["outcome"], "failed: docker stop")
        self.assertEqual([entry["id"] for entry in self.started_json()["entries"]], ["c-ours"])
        self.assertEqual([call for call in self.calls("docker") if call[1:3] in (["volume", "rm"], ["network", "rm"])], [])

    def test_gone_entries_are_dropped(self):
        ours_backend, ours_frontend, _ = self.prepare()
        ours_backend.kill()
        ours_backend.wait()
        self.fixture["containers"] = [item for item in self.fixture["containers"] if item["id"] != "c-ours"]
        result = self.qa("cleanup")
        self.assertEqual([item["outcome"] for item in result["stopped"]][0::2], ["gone", "gone"])
        self.assertEqual(ours_frontend.wait(timeout=15), -15)
        self.assertIsNone(self.started_json())

    def test_started_json_of_another_worktree_is_refused(self):
        os.makedirs(os.path.join(self.worktree, ".claude", "qa"))
        with open(os.path.join(self.worktree, ".claude", "qa", "started.json"), "w") as handle:
            json.dump({"worktree": self.alpha, "entries": [{"kind": "process", "name": "x", "pid": 1}]}, handle)
        self.assertIn("another worktree", self.qa("cleanup", expect=2)["error"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
