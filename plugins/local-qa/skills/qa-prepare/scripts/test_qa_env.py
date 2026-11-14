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
        if all(qa_env.port_is_free(port + offset) for offset in range(4)):
            return port
    raise RuntimeError("no free port")


def full_id(character):
    return character * 64


class Machine(unittest.TestCase):
    """Two projects on one machine: alpha (main checkout + worktrees feature-x, the QA's, and other) and beta."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="qa-env-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.locks = os.path.join(self.root, "locks")
        previous = os.environ.get("QA_PORT_LOCKS")
        os.environ["QA_PORT_LOCKS"] = self.locks
        self.addCleanup(lambda: os.environ.__setitem__("QA_PORT_LOCKS", previous) if previous else os.environ.pop("QA_PORT_LOCKS", None))
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
        self.here = {"worktree": self.worktree, "project": self.alpha}
        self.ours = qa_env.compose_project_name(self.here)
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

    def our_container(self, identifier, service, port):
        self.container(identifier, self.ours + "-" + service + "-1", self.ours, os.path.join(self.worktree, "infra"), service, "0.0.0.0:%d->5432/tcp" % port)

    def listener(self, pid, command, port, cwd):
        self.fixture["listeners"].append({"pid": pid, "command": command, "port": port, "cwd": cwd})

    def wait_identity(self, pid):
        deadline = time.monotonic() + 5
        while qa_env.process_identity(pid) is None and time.monotonic() < deadline:
            time.sleep(0.05)

    def spawn(self, cwd, new_session=True, with_child=False, name=None, ignore_term=False):
        code = "import time; time.sleep(120)"
        if ignore_term:
            code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(120)"
        if with_child:
            code = (
                "import subprocess, sys, time; child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
                " print(child.pid, flush=True); time.sleep(120)"
            )
        arguments = [sys.executable, "-c", code]
        if name:
            # A program called `name` (a link to sleep): what ps shows for Claude Code's own binary.
            tools = os.path.join(self.root, "tools")
            os.makedirs(tools, exist_ok=True)
            link = os.path.join(tools, name)
            if not os.path.exists(link):
                os.symlink(shutil.which("sleep"), link)
            arguments = [link, "120"]
        process = subprocess.Popen(
            arguments, cwd=cwd, start_new_session=new_session, stdout=subprocess.PIPE if (with_child or ignore_term) else None
        )
        if with_child:
            process.child_pid = int(process.stdout.readline())
            self.addCleanup(self.kill_quietly, process.child_pid)
        if ignore_term:
            process.stdout.readline()
        self.processes.append(process)
        self.wait_identity(process.pid)
        return process

    def spawn_orphan(self, cwd, *command):
        """A process that does not descend from this test (its parent shell exits at once)."""
        line = subprocess.run(
            ["sh", "-c", '"$@" >/dev/null 2>&1 & echo $!', "sh", *command], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()
        pid = int(line)
        self.addCleanup(self.kill_quietly, pid)
        self.wait_identity(pid)
        return pid

    def qa(self, *arguments, root=None, expect=0, environment=None):
        with open(self.fixture_path, "w") as handle:
            json.dump(self.fixture, handle)
        variables = dict(
            os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], QA_STUB=self.fixture_path, QA_STUB_LOG=self.log_path
        )
        variables.update(environment or {})
        completed = subprocess.run(
            [sys.executable, SCRIPT, "--root", root or self.worktree, *arguments],
            capture_output=True,
            text=True,
            env=variables,
            timeout=120,
        )
        self.assertEqual(completed.returncode, expect, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def calls(self, program):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as handle:
            return [json.loads(line) for line in handle if json.loads(line)[0] == program]

    def docker_writes(self):
        return [call[1:] for call in self.calls("docker") if call[1] in ("stop", "rm") or call[2:3] == ["rm"]]

    def write_spec(self, migrations=(), applied=None, database_kind="container", extra=None):
        database = {"name": "db", "kind": database_kind, "compose_service": "postgres", "port": self.port, "container_port": 5432, "shared": True, "database": True}
        if applied is not None:
            database["applied_migrations"] = applied
        spec = {
            "services": [database, {"name": "backend", "kind": "process", "port": self.port + 1000}, {"name": "frontend", "kind": "process", "port": self.port + 2000}],
            "migrations": list(migrations) or ["backend/migration/*.sql"],
        }
        spec.update(extra or {})
        path = os.path.join(self.root, "spec.json")
        with open(path, "w") as handle:
            json.dump(spec, handle)
        return path

    def simple_spec(self, *services):
        path = os.path.join(self.root, "simple.json")
        with open(path, "w") as handle:
            json.dump({"services": list(services)}, handle)
        return path

    def open_qa(self, root=None):
        """`plan` opens the QA: what it records afterwards must have started after this."""
        self.qa("plan", "--spec", self.simple_spec({"name": "x", "port": self.port + 3}), root=root)

    def migration(self, worktree, name):
        directory = os.path.join(worktree, "backend", "migration")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name), "w") as handle:
            handle.write("select 1;\n")

    def shared_database(self, port=None):
        self.container(full_id("a"), "alpha-postgres", "alpha", os.path.join(self.alpha, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (port or self.port))

    def service(self, result, name):
        return next(item for item in result["services"] if item["name"] == name)

    def started_json(self, worktree=None):
        path = os.path.join(worktree or self.worktree, ".claude", "qa", "started.json")
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
        self.assertEqual(qa_env.locate(os.path.join(self.worktree, "backend")), self.here)
        self.assertIsNone(qa_env.locate(self.root))
        self.assertIsNone(qa_env.locate("relative/path"))
        self.assertIsNone(qa_env.locate(os.path.join(self.root, "missing")))

    def test_compose_project_names_never_collide(self):
        self.assertRegex(self.ours, r"^qa-alpha-feature-x-[0-9a-f]{8}$")
        self.assertRegex(qa_env.compose_project_name({"worktree": self.alpha, "project": self.alpha}), r"^qa-alpha-[0-9a-f]{8}$")
        names = {
            qa_env.compose_project_name({"worktree": "/a/api", "project": "/a/api"}),
            qa_env.compose_project_name({"worktree": "/b/api", "project": "/b/api"}),
            qa_env.compose_project_name({"worktree": "/a/api/.claude/worktrees/x", "project": "/a/api"}),
            qa_env.compose_project_name({"worktree": "/c/api-x", "project": "/c/api-x"}),
            qa_env.compose_project_name({"worktree": "/a/api/elsewhere/x", "project": "/a/api"}),
        }
        self.assertEqual(len(names), 5)
        self.assertRegex(qa_env.compose_project_name({"worktree": "/x/Feat.Y", "project": "/p/My App"}), r"^qa-my-app-feat-y-[0-9a-f]{8}$")


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

    def test_migration_ids(self):
        self.assertEqual(qa_env.migration_ids(["m/V1__a.sql", "m/V2__b.sql"], qa_env.DEFAULT_MIGRATION_ID), {"V1__a", "V2__b"})
        self.assertEqual(qa_env.migration_ids(["m/V1_2__a.sql", "m/README"], r"^V([0-9_]+)__"), {"1_2"})


class ToolProcessTest(unittest.TestCase):
    def test_claude_code_apps_and_ide_helpers_are_never_qa_services(self):
        for command in (
            "claude --resume x",
            "/Users/u/Library/Application Support/Claude/claude-code/2.1.325/x/claude.app/Contents/MacOS/claude --output-format stream-json",
            "node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js",
            "/Applications/IntelliJ IDEA.app/Contents/MacOS/idea",
            "/opt/homebrew/bin/copilot-language-server --stdio",
            "node /x/node_modules/typescript/lib/tsserver.js",
            "",
        ):
            self.assertTrue(qa_env.is_tool_process(command), command)
        for command in ("node /w/node_modules/.bin/vite --port 5174", "java -jar backend.jar", "python3 -m http.server"):
            self.assertFalse(qa_env.is_tool_process(command), command)


class FreePortTest(Machine):
    def test_a_bound_port_and_a_taken_port_are_skipped(self):
        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind(("127.0.0.1", self.port))
        listening.listen()
        try:
            self.assertFalse(qa_env.port_is_free(self.port))
            self.assertEqual(qa_env.free_port(self.port, {self.port + 1}), self.port + 2)
        finally:
            listening.close()
        self.assertEqual(qa_env.free_port(self.port, set()), self.port)

    @unittest.skipUnless(socket.has_ipv6, "no IPv6")
    def test_a_listener_on_the_ipv6_loopback_only_is_seen(self):
        try:
            listening = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            listening.bind(("::1", self.port))
        except OSError:
            self.skipTest("no IPv6 loopback")
        listening.listen()
        try:
            self.assertFalse(qa_env.port_is_free(self.port))
        finally:
            listening.close()

    def test_reservations_are_machine_wide_and_stale_ones_reclaimed(self):
        other = {"worktree": self.other_worktree, "project": self.alpha}
        self.assertEqual(qa_env.free_port(self.port, set(), self.here, reserve=True), self.port)
        self.assertEqual(qa_env.free_port(self.port, set(), other, reserve=True), self.port + 1)
        main_checkout = {"worktree": self.alpha, "project": self.alpha}
        self.assertEqual(qa_env.free_port(self.port, set(), main_checkout), self.port + 2, "an unreserved lookup skips others' locks")
        self.assertEqual(qa_env.free_port(self.port, set(), self.here, reserve=True), self.port, "a worktree reuses its own lock")
        self.assertFalse(qa_env.release_port(self.port, other))
        shutil.rmtree(self.worktree)
        self.assertEqual(qa_env.free_port(self.port, set(), other, reserve=True), self.port, "the lock of a deleted worktree is stale")
        with open(os.path.join(self.locks, str(self.port + 5)), "w") as handle:
            handle.write("not json")
        self.assertEqual(qa_env.free_port(self.port + 5, set(), other, reserve=True), self.port + 6, "an unreadable lock is kept")

    def test_no_lock_directory_is_refused(self):
        os.environ["QA_PORT_LOCKS"] = os.path.join(self.root, "README-file")
        with open(os.environ["QA_PORT_LOCKS"], "w") as handle:
            handle.write("a file")
        with self.assertRaisesRegex(qa_env.Refused, "QA_PORT_LOCKS"):
            qa_env.reserve_port(self.port, self.here)


class InventoryTest(Machine):
    def test_another_projects_container_on_the_default_port_is_reported_as_theirs(self):
        self.container(full_id("b"), "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.listener(501, "com.docker.backend", self.port, "/")
        result = self.qa("inventory")
        container = result["containers"][0]
        self.assertEqual((container["project"], container["worktree"], container["same_project"]), (self.beta, self.beta, False))
        self.assertEqual((result["listeners"][0]["container"], result["listeners"][0]["project"]), ("beta-postgres", self.beta))
        self.assertEqual(result["context"]["compose_project"], self.ours)
        self.assert_nothing_stopped()

    def test_listeners_are_mapped_to_project_and_worktree(self):
        self.listener(601, "java", self.port, os.path.join(self.worktree, "backend"))
        self.listener(602, "node", self.port + 1, os.path.join(self.alpha, "frontend"))
        self.listener(603, "ControlCenter", self.port + 2, "/")
        listeners = {item["pid"]: item for item in self.qa("inventory")["listeners"]}
        self.assertEqual((listeners[601]["worktree"], listeners[601]["same_worktree"]), (self.worktree, True))
        self.assertEqual((listeners[602]["project"], listeners[602]["same_project"], listeners[602]["same_worktree"]), (self.alpha, True, False))
        self.assertEqual((listeners[603]["project"], listeners[603]["same_project"]), (None, False))

    def test_docker_down_is_reported_not_fatal(self):
        self.fixture["docker"] = "down"
        result = self.qa("inventory")
        self.assertEqual((result["docker"], result["containers"]), ("unavailable", []))

    def test_outside_a_repository_is_refused(self):
        self.assertIn("not inside a git repository", self.qa("inventory", root=self.root, expect=2)["error"])


class PlanTest(Machine):
    def test_other_projects_services_on_default_ports_start_ours_on_reserved_free_ports(self):
        self.container(full_id("b"), "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % self.port)
        self.listener(501, "com.docker.backend", self.port, "/")
        self.listener(502, "node", self.port + 2000, os.path.join(self.beta, "frontend"))
        result = self.qa("plan", "--spec", self.write_spec(), "--base", "main")
        database = self.service(result, "db")
        self.assertEqual((database["action"], database["port"], database["compose_project"], database["isolated"]), ("start", self.port + 1, self.ours, True))
        self.assertEqual(database["default_port_taken_by"]["project"], self.beta)
        frontend = self.service(result, "frontend")
        self.assertEqual((frontend["action"], frontend["port"], frontend["default_port_taken_by"]["pid"]), ("start", self.port + 2001, 502))
        self.assertEqual(self.service(result, "backend"), {"name": "backend", "action": "start", "port": self.port + 1000})
        for port in (self.port + 1, self.port + 1000, self.port + 2001):
            self.assertEqual(qa_env.lock_owner(port), self.worktree)
        self.assertEqual(sorted(self.started_json()["ports"]), [self.port + 1, self.port + 1000, self.port + 2001])
        self.assertTrue(self.started_json()["prepared_at"])
        self.assert_nothing_stopped()

    def test_a_shared_database_is_reused_only_when_its_history_equals_the_worktrees_migrations(self):
        self.shared_database()
        self.migration(self.worktree, "V1__init.sql")
        spec = self.write_spec(applied="printf 'V1__init\\n'")
        database = self.service(self.qa("plan", "--spec", spec, "--base", "main"), "db")
        self.assertEqual(database, {"name": "db", "action": "reuse", "port": self.port, "started_by_this_qa": False, "container": "alpha-postgres"})
        self.migration(self.worktree, "V2__add.sql")
        database = self.service(self.qa("plan", "--spec", spec, "--base", "main"), "db")
        self.assertEqual((database["action"], database["isolated"]), ("start", True))
        self.assertIn("lacks the worktree's migrations V2__add", database["reason"])
        self.assert_nothing_stopped()

    def test_a_database_ahead_of_the_worktree_is_not_reused(self):
        self.shared_database()
        self.migration(self.worktree, "V1__init.sql")
        spec = self.write_spec(applied="printf 'V1__init\\nV9__later\\n'")
        database = self.service(self.qa("plan", "--spec", spec, "--base", "main"), "db")
        self.assertEqual(database["action"], "start")
        self.assertIn("migrations the worktree lacks: V9__later", database["reason"])

    def test_without_a_readable_history_the_database_is_never_reused(self):
        self.shared_database()
        database = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "db")
        self.assertEqual(database["action"], "start")
        self.assertIn("cannot compare", database["reason"])
        failing = self.service(self.qa("plan", "--spec", self.write_spec(applied="echo nope >&2; exit 3"), "--base", "main"), "db")
        self.assertEqual(failing["action"], "start")
        self.assertIn("failed (exit 3)", failing["reason"])

    def test_the_history_command_reads_the_candidates_port_and_the_id_pattern_applies(self):
        self.shared_database(self.port + 7)
        self.migration(self.worktree, "V1_2__init.sql")
        spec = self.write_spec(
            applied='test "$QA_DB_PORT" = %d && test "$QA_DB_HOST" = 127.0.0.1 && printf "1_2\\n"' % (self.port + 7),
            extra={"migration_id": "^V([0-9_]+)__"},
        )
        database = self.service(self.qa("plan", "--spec", spec, "--base", "main"), "db")
        self.assertEqual((database["action"], database["port"]), ("reuse", self.port + 7))

    def test_a_declared_migration_isolates_even_a_compatible_database(self):
        self.shared_database()
        result = self.qa("plan", "--spec", self.write_spec(applied="true"), "--base", "main", "--pending-migration")
        self.assertEqual(self.service(result, "db")["action"], "start")
        self.assertNotIn("isolated", self.service(result, "backend"))

    def test_a_database_run_as_a_process_follows_the_same_rule(self):
        self.listener(701, "postgres", self.port, os.path.join(self.alpha, "infra"))
        compatible = self.service(self.qa("plan", "--spec", self.write_spec(applied="true", database_kind="process"), "--base", "main"), "db")
        self.assertEqual(compatible["action"], "reuse")
        isolated = self.service(self.qa("plan", "--spec", self.write_spec(applied="true", database_kind="process"), "--base", "main", "--pending-migration"), "db")
        self.assertEqual((isolated["action"], isolated["isolated"]), ("start", True))
        unknown = self.service(self.qa("plan", "--spec", self.write_spec(database_kind="process"), "--base", "main"), "db")
        self.assertEqual(unknown["action"], "start")

    def test_migrations_without_a_base_and_a_database_without_migrations_are_refused(self):
        self.assertIn("--base", self.qa("plan", "--spec", self.write_spec(), expect=2)["error"])
        path = os.path.join(self.root, "nomigrations.json")
        with open(path, "w") as handle:
            json.dump({"services": [{"name": "db", "port": self.port, "database": True}]}, handle)
        self.assertIn("migrations", self.qa("plan", "--spec", path, "--base", "main", expect=2)["error"])

    def test_the_changes_own_migrations_are_listed(self):
        self.migration(self.worktree, "V3__x.sql")
        result = self.qa("plan", "--spec", self.write_spec(), "--base", "main")
        self.assertEqual(result["migrations"], ["backend/migration/V3__x.sql"])

    def test_an_unknown_base_is_refused(self):
        self.qa("plan", "--spec", self.write_spec(), "--base", "no-such-ref", expect=2)

    def test_shared_code_services_of_another_worktree_are_not_reused(self):
        self.listener(601, "java", self.port + 1000, os.path.join(self.alpha, "backend"))
        backend = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "backend")
        self.assertEqual((backend["action"], backend["port"], backend["default_port_taken_by"]["worktree"]), ("start", self.port + 1001, self.alpha))

    def test_the_worktrees_own_backend_is_reused(self):
        self.listener(601, "java", self.port + 1000, os.path.join(self.worktree, "backend"))
        backend = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "backend")
        self.assertEqual(backend, {"name": "backend", "action": "reuse", "port": self.port + 1000, "started_by_this_qa": False, "pid": 601})

    def test_ports_chosen_in_one_plan_do_not_collide(self):
        self.listener(701, "node", self.port, os.path.join(self.beta, "frontend"))
        result = self.qa("plan", "--spec", self.simple_spec({"name": "api", "port": self.port}, {"name": "web", "port": self.port + 1}))
        self.assertEqual([item["port"] for item in result["services"]], [self.port + 1, self.port + 2])

    def test_two_worktrees_preparing_at_once_get_different_ports(self):
        spec = self.simple_spec({"name": "web", "port": self.port})
        self.assertEqual(self.qa("plan", "--spec", spec)["services"][0]["port"], self.port)
        self.assertEqual(self.qa("plan", "--spec", spec, root=self.other_worktree)["services"][0]["port"], self.port + 1)
        self.assertEqual(self.qa("plan", "--spec", spec)["services"][0]["port"], self.port, "a plan again keeps its own port")
        self.assertEqual(self.qa("free-port", str(self.port), root=self.alpha)["port"], self.port + 2)

    def test_a_container_port_is_never_taken_for_a_process_of_the_worktree(self):
        self.container(full_id("c"), "alpha-api", "alpha-wt", os.path.join(self.worktree, "infra"), "api", "0.0.0.0:%d->8080/tcp" % (self.port + 1000))
        self.listener(501, "com.docker.backend", self.port + 1000, "/")
        backend = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "backend")
        self.assertEqual((backend["action"], backend["port"]), ("start", self.port + 1001))

    def test_qa_containers_of_another_worktree_or_misplaced_are_not_reused_ours_is(self):
        spec = self.simple_spec({"name": "cache", "kind": "container", "compose_service": "redis", "port": self.port, "container_port": 6379, "shared": True})
        other = qa_env.compose_project_name({"worktree": self.other_worktree, "project": self.alpha})
        self.container(full_id("d"), other + "-redis-1", other, os.path.join(self.other_worktree, "infra"), "redis", "0.0.0.0:%d->6379/tcp" % self.port)
        self.assertEqual(self.service(self.qa("plan", "--spec", spec), "cache")["action"], "start")
        self.container(full_id("e"), self.ours + "-redis-1", self.ours, os.path.join(self.other_worktree, "infra"), "redis", "0.0.0.0:%d->6379/tcp" % (self.port + 1))
        self.assertEqual(self.service(self.qa("plan", "--spec", spec), "cache")["action"], "start", "our name, another worktree's compose file")
        self.container(full_id("f"), self.ours + "-redis-2", self.ours, os.path.join(self.worktree, "infra"), "redis", "0.0.0.0:%d->6379/tcp" % (self.port + 2))
        cache = self.service(self.qa("plan", "--spec", spec), "cache")
        self.assertEqual((cache["action"], cache["port"], cache["started_by_this_qa"], cache["recorded"]), ("reuse", self.port + 2, True, False))

    def test_a_container_running_the_changes_code_is_reused_only_from_this_worktree(self):
        spec = self.simple_spec({"name": "api", "kind": "container", "compose_service": "api", "port": self.port})
        self.container(full_id("1"), "alpha-api", "alpha", os.path.join(self.alpha, "infra"), "api", "0.0.0.0:%d->%d/tcp" % (self.port, self.port))
        self.assertEqual(self.service(self.qa("plan", "--spec", spec), "api")["action"], "start")
        self.container(full_id("2"), "feature-x-api", "feature-x", os.path.join(self.worktree, "infra"), "api", "0.0.0.0:%d->%d/tcp" % (self.port + 1, self.port))
        api = self.service(self.qa("plan", "--spec", spec), "api")
        self.assertEqual((api["action"], api["container"], api["port"]), ("reuse", "feature-x-api", self.port + 1))

    def test_a_backend_this_qa_started_is_reused_while_it_runs(self):
        self.open_qa()
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port + 1001, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port + 1001))
        backend = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "backend")
        self.assertEqual((backend["action"], backend["port"], backend["started_by_this_qa"]), ("reuse", self.port + 1001, True))
        process.kill()
        process.wait()
        self.fixture["listeners"] = []
        backend = self.service(self.qa("plan", "--spec", self.write_spec(), "--base", "main"), "backend")
        self.assertEqual((backend["action"], backend["port"]), ("start", self.port + 1000))

    def test_a_spec_without_services_is_refused(self):
        path = os.path.join(self.root, "empty.json")
        with open(path, "w") as handle:
            json.dump({"services": []}, handle)
        self.qa("plan", "--spec", path, expect=2)


class RecordContainerTest(Machine):
    def test_a_container_of_another_compose_project_is_refused(self):
        self.shared_database()
        self.assertIn("not this QA's", self.qa("record", "container", "--name", "db", "--id", full_id("a"), expect=2)["error"])
        self.assertIsNone(self.started_json())

    def test_our_compose_name_from_another_worktree_is_refused(self):
        self.container(full_id("e"), self.ours + "-postgres-1", self.ours, os.path.join(self.other_worktree, "infra"), "postgres", "")
        self.qa("record", "container", "--name", "db", "--id", full_id("e"), expect=2)

    def test_a_container_without_compose_labels_is_refused_whatever_its_name(self):
        for identifier, name in ((full_id("7"), self.ours + "-db"), (full_id("8"), self.ours + "db")):
            self.fixture["containers"].append({"id": identifier, "name": name, "ports": "", "labels": {}})
            self.qa("record", "container", "--name", "db", "--id", identifier, expect=2)
        self.assertIsNone(self.started_json())

    def test_a_container_of_this_qa_is_recorded_by_service_with_its_full_id(self):
        self.our_container(full_id("c"), "postgres", self.port)
        self.qa("record", "container", "--name", "db", "--service", "postgres")
        entries = self.started_json()["entries"]
        self.assertEqual(
            [(entry["kind"], entry["id"], entry["compose_project"], entry["port"]) for entry in entries],
            [("container", full_id("c"), self.ours, self.port)],
        )

    def test_a_short_id_from_docker_is_refused(self):
        self.our_container("c0ffee", "postgres", self.port)
        self.assertIn("full id", self.qa("record", "container", "--name", "db", "--id", "c0ffee", expect=2)["error"])


class RecordProcessTest(Machine):
    def test_recording_needs_an_open_qa(self):
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.assertIn("run `plan` first", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])

    def test_a_process_outside_the_worktree_is_refused(self):
        self.open_qa()
        process = self.spawn(os.path.join(self.alpha, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.alpha, "backend"))
        self.assertIn("not from this worktree", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])

    def test_from_the_main_checkout_a_process_of_a_nested_worktree_is_refused(self):
        self.open_qa(root=self.alpha)
        process = self.spawn(os.path.join(self.worktree, "frontend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "frontend"))
        self.assertIn("not from this worktree", self.qa("record", "process", "--name", "frontend", "--port", str(self.port), root=self.alpha, expect=2)["error"])
        self.assertEqual(self.started_json(self.alpha)["entries"], [])

    def test_the_reviewers_case_claude_code_sessions_at_the_project_root_are_refused(self):
        """From the main checkout: a Claude Code session of the project (cwd = the project root) and one of a
        worktree listen on ports; neither is ever recorded, so cleanup can never stop them."""
        early = self.spawn(self.alpha, name="claude")
        time.sleep(1.2)
        self.open_qa(root=self.alpha)
        late = self.spawn(self.alpha, name="claude")
        nested = self.spawn(self.worktree, name="claude")
        self.listener(early.pid, "claude", self.port, self.alpha)
        self.listener(late.pid, "claude", self.port + 1, self.alpha)
        self.listener(nested.pid, "claude", self.port + 2, self.worktree)
        for port, reason in ((self.port, "Claude Code"), (self.port + 1, "Claude Code"), (self.port + 2, "not from this worktree")):
            self.assertIn(reason, self.qa("record", "process", "--name", "frontend", "--port", str(port), root=self.alpha, expect=2)["error"])
        self.assertEqual(self.started_json(self.alpha)["entries"], [])
        self.assertEqual(self.qa("cleanup", root=self.alpha)["stopped"], [])
        for process in (early, late, nested):
            self.assertIsNone(process.poll())

    def test_a_process_started_before_the_qa_is_refused(self):
        process = self.spawn(os.path.join(self.worktree, "backend"))
        time.sleep(1.2)
        self.open_qa()
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.assertIn("before this QA", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])

    def test_a_process_descending_neither_from_the_recording_shell_nor_a_launch_is_refused(self):
        self.open_qa()
        pid = self.spawn_orphan(os.path.join(self.worktree, "backend"), sys.executable, "-c", "import time; time.sleep(120)")
        self.listener(pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.assertIn("descends neither", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])

    def test_a_process_started_through_launch_is_accepted_wherever_its_parent(self):
        self.open_qa()
        environment = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], QA_STUB=self.fixture_path, QA_STUB_LOG=self.log_path)
        line = subprocess.run(
            ["sh", "-c", '"$@" >/dev/null 2>&1 & echo $!', "sh", sys.executable, SCRIPT, "--root", self.worktree, "launch", "--name", "backend", "--",
             sys.executable, "-c", "import time; time.sleep(120)"],
            cwd=os.path.join(self.worktree, "backend"), capture_output=True, text=True, check=True, env=environment,
        ).stdout.strip()
        pid = int(line)
        self.addCleanup(self.kill_quietly, pid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "qa_env.py" in ((qa_env.process_identity(pid) or ("qa_env.py",))[0]):
            time.sleep(0.05)
        self.listener(pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        entry = self.qa("record", "process", "--name", "backend", "--port", str(self.port))["recorded"][0]
        self.assertEqual(entry["pid"], pid)
        self.assertEqual([launcher["pid"] for launcher in self.started_json()["launchers"]], [pid])

    def test_a_launcher_whose_pid_was_reused_is_no_anchor(self):
        self.open_qa()
        pid = self.spawn_orphan(os.path.join(self.worktree, "backend"), sys.executable, "-c", "import time; time.sleep(120)")
        path = os.path.join(self.worktree, ".claude", "qa", "started.json")
        with open(path) as handle:
            started = json.load(handle)
        started["launchers"] = [{"name": "backend", "pid": pid, "started": "Thu Jan  1 00:00:00 1970", "command": ["x"]}]
        with open(path, "w") as handle:
            json.dump(started, handle)
        self.listener(pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.assertIn("descends neither", self.qa("record", "process", "--name", "backend", "--port", str(self.port), expect=2)["error"])

    def test_a_second_plan_keeps_the_qas_start_time(self):
        self.open_qa()
        process = self.spawn(os.path.join(self.worktree, "backend"))
        time.sleep(1.2)
        self.open_qa()
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))

    def test_launch_needs_an_open_qa(self):
        self.qa("launch", "--name", "backend", "--", "true", expect=2)

    def test_a_process_of_the_worktree_is_recorded_with_its_identity_once(self):
        self.open_qa()
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        entry = self.started_json()["entries"][0]
        self.assertEqual((entry["pid"], entry["port"], entry["process_group"]), (process.pid, self.port, process.pid))
        self.assertIn("time.sleep(120)", entry["command"])
        self.assertTrue(qa_env.start_epoch(entry["started"]))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        self.assertEqual(len(self.started_json()["entries"]), 1, "the same process recorded again replaces its entry")


class CleanupTest(Machine):
    def prepare(self):
        """This QA started a backend (own session, with a child), a frontend (shared process group) and a database
        container; another dev server of the same worktree and beta's database were already running."""
        self.qa("plan", "--spec", self.simple_spec({"name": "x", "port": self.port + 3}))
        ours_backend = self.spawn(os.path.join(self.worktree, "backend"), with_child=True)
        ours_frontend = self.spawn(os.path.join(self.worktree, "frontend"), new_session=False)
        not_ours = self.spawn(os.path.join(self.worktree, "frontend"))
        self.listener(ours_backend.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.listener(ours_frontend.pid, "python3", self.port + 1, os.path.join(self.worktree, "frontend"))
        self.listener(not_ours.pid, "python3", self.port + 2, os.path.join(self.worktree, "frontend"))
        self.our_container(full_id("c"), "postgres", self.port + 4)
        self.container(full_id("b"), "beta-postgres", "beta", os.path.join(self.beta, "infra"), "postgres", "0.0.0.0:%d->5432/tcp" % (self.port + 5))
        self.fixture["volumes"] = {self.ours: [self.ours + "_data"], "beta": ["beta_data"]}
        self.fixture["networks"] = {self.ours: [self.ours + "_default"], "beta": ["beta_default"]}
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        self.qa("record", "process", "--name", "frontend", "--port", str(self.port + 1))
        self.qa("record", "container", "--name", "db", "--service", "postgres")
        return ours_backend, ours_frontend, not_ours

    def edit_started(self, change):
        path = os.path.join(self.worktree, ".claude", "qa", "started.json")
        with open(path) as handle:
            started = json.load(handle)
        change(started)
        with open(path, "w") as handle:
            json.dump(started, handle)

    def test_cleanup_stops_exactly_what_started_json_lists_and_releases_its_ports(self):
        ours_backend, ours_frontend, not_ours = self.prepare()
        self.assertEqual(qa_env.lock_owner(self.port + 3), self.worktree)
        result = self.qa("cleanup")
        self.assertEqual(ours_backend.wait(timeout=15), -15)
        self.assertEqual(ours_frontend.wait(timeout=15), -15)
        deadline = time.monotonic() + 5
        while self.running(ours_backend.child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.running(ours_backend.child_pid), "the backend's process group is stopped with it")
        self.assertIsNone(not_ours.poll())
        self.assertEqual([item["outcome"] for item in result["stopped"]], ["stopped"] * 3)
        self.assertEqual(
            self.docker_writes(),
            [["stop", full_id("c")], ["rm", "-v", full_id("c")], ["volume", "rm", self.ours + "_data"], ["network", "rm", self.ours + "_default"]],
        )
        self.assertEqual(result["released_ports"], [self.port + 3])
        self.assertIsNone(qa_env.lock_owner(self.port + 3))
        self.assertIsNone(self.started_json())

    def test_a_reused_pid_is_not_signalled_and_stays_listed(self):
        ours_backend, _, _ = self.prepare()
        self.edit_started(lambda started: started["entries"][0].__setitem__("started", "Thu Jan  1 00:00:00 1970"))
        result = self.qa("cleanup", expect=1)
        self.assertTrue(result["stopped"][0]["outcome"].startswith("skipped"))
        self.assertIsNone(ours_backend.poll())
        self.assertEqual([entry["name"] for entry in self.started_json()["entries"]], ["backend"])

    def test_a_process_ignoring_sigterm_is_killed_after_the_grace_period(self):
        self.qa("plan", "--spec", self.simple_spec({"name": "x", "port": self.port + 3}))
        stubborn = self.spawn(os.path.join(self.worktree, "backend"), ignore_term=True)
        self.listener(stubborn.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        result = self.qa("cleanup", environment={"QA_ENV_STOP_GRACE": "0.5"})
        self.assertTrue(result["stopped"][0]["outcome"].startswith("stopped (killed after"), result)
        self.assertEqual(stubborn.wait(timeout=10), -9)

    def test_a_group_member_ignoring_sigterm_is_killed_with_the_group(self):
        self.qa("plan", "--spec", self.simple_spec({"name": "x", "port": self.port + 3}))
        code = (
            "import subprocess, sys, time; child = subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(1, flush=True); time.sleep(120)'], stdout=subprocess.PIPE);"
            " child.stdout.readline(); print(child.pid, flush=True); time.sleep(120)"
        )
        leader = subprocess.Popen([sys.executable, "-c", code], cwd=os.path.join(self.worktree, "backend"), start_new_session=True, stdout=subprocess.PIPE)
        self.processes.append(leader)
        child = int(leader.stdout.readline())
        self.addCleanup(self.kill_quietly, child)
        self.wait_identity(leader.pid)
        self.listener(leader.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        result = self.qa("cleanup", environment={"QA_ENV_STOP_GRACE": "0.5"})
        self.assertTrue(result["stopped"][0]["outcome"].startswith("stopped (killed after"), result)
        leader.wait(timeout=10)
        deadline = time.monotonic() + 5
        while self.running(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.running(child))

    def test_dry_run_stops_nothing(self):
        ours_backend, ours_frontend, _ = self.prepare()
        result = self.qa("cleanup", "--dry-run")
        self.assertEqual([item["outcome"] for item in result["stopped"]], ["would stop"] * 3)
        self.assertIsNone(ours_backend.poll())
        self.assertIsNone(ours_frontend.poll())
        self.assertEqual(self.docker_writes(), [])
        self.assertEqual(len(self.started_json()["entries"]), 3)
        self.assertEqual(qa_env.lock_owner(self.port + 3), self.worktree)

    def test_a_container_that_fails_to_stop_stays_listed(self):
        self.prepare()
        self.fixture["failing"] = [full_id("c")]
        result = self.qa("cleanup", expect=1)
        self.assertEqual(result["stopped"][2]["outcome"], "failed: docker stop")
        self.assertEqual([entry["id"] for entry in self.started_json()["entries"]], [full_id("c")])
        self.assertEqual([call for call in self.docker_writes() if call[0] in ("volume", "network")], [])

    def test_a_container_entry_with_a_short_id_or_other_labels_is_left_alone(self):
        self.prepare()
        self.edit_started(lambda started: started["entries"][2].__setitem__("id", "c" * 12))
        result = self.qa("cleanup", expect=1)
        self.assertTrue(result["stopped"][2]["outcome"].startswith("skipped"))
        self.assertEqual([call for call in self.docker_writes() if call[0] in ("stop", "rm")], [])
        self.edit_started(lambda started: started["entries"][0].__setitem__("id", full_id("b")))
        result = self.qa("cleanup", expect=1)
        self.assertIn("no longer labelled for this QA", result["stopped"][0]["outcome"])
        self.assertEqual([call for call in self.docker_writes() if call[0] in ("stop", "rm")], [])

    def test_volumes_and_networks_are_removed_only_after_a_container_of_this_qa(self):
        self.qa("plan", "--spec", self.simple_spec({"name": "x", "port": self.port + 3}))
        process = self.spawn(os.path.join(self.worktree, "backend"))
        self.listener(process.pid, "python3", self.port, os.path.join(self.worktree, "backend"))
        self.fixture["volumes"] = {self.ours: [self.ours + "_data"]}
        self.qa("record", "process", "--name", "backend", "--port", str(self.port))
        self.qa("cleanup")
        self.assertEqual(self.docker_writes(), [])

    def test_gone_entries_are_dropped(self):
        ours_backend, ours_frontend, _ = self.prepare()
        ours_backend.kill()
        ours_backend.wait()
        self.fixture["containers"] = [item for item in self.fixture["containers"] if item["id"] != full_id("c")]
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
