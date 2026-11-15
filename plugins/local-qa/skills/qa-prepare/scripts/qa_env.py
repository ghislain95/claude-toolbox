#!/usr/bin/env python3
"""The deterministic half of /local-qa:qa-prepare (Python 3.9+, standard library only).

    qa_env.py inventory                         what runs on the machine, each item with its project and worktree
    qa_env.py plan --spec <file> [--base <ref>] [--pending-migration]
                                                per service of the spec: reuse a running one, or start one on a
                                                port it reserves; opens this QA (its start time, its port locks)
    qa_env.py free-port <preferred>             the first free, unreserved port from <preferred> on (reserves nothing)
    qa_env.py launch --name <n> -- <command…>   run a process for this QA (exec): it becomes an ancestor `record` trusts
    qa_env.py record container --name <n> (--id <id> | --service <compose service>)
    qa_env.py record process --name <n> --port <port>
                                                add what this QA started to .claude/qa/started.json
    qa_env.py cleanup [--dry-run]               stop exactly what started.json lists, nothing else

Every command prints JSON on stdout (`launch` excepted: it becomes the command). `--root <dir>` (default: the
current directory) is the worktree the QA is for. Exit codes: 0 done, 1 done with entries left (failed or
skipped, listed in the JSON and kept in started.json), 2 refused or usage error.

The rule: the QA only ever stops what it provably started.
- Nothing is stopped, restarted or reconfigured except by `cleanup`, and `cleanup` only stops what `record`
  wrote, after checking again that it is still that container or that process.
- `record container` accepts a container only with this worktree's compose labels: its compose project
  (`qa-<project>[-<worktree>]-<hash of the two paths>`) and a compose working directory inside this worktree.
- `record process` accepts a process only when it runs from this very worktree, started after `plan` opened
  this QA, descends from the shell that records it or from a `launch` of this QA, and is not Claude Code, a
  desktop app or an IDE helper.
- Ports are reserved machine-wide by lock files (`$QA_PORT_LOCKS`, default `/tmp/qa-ports-<uid>`), so two
  agents preparing at the same time do not pick the same port; `cleanup` releases them.
"""

import argparse
import datetime
import errno
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

STATE_DIRECTORY = os.path.join(".claude", "qa")
STARTED_FILE = "started.json"
QA_PROJECT_PREFIX = "qa-"
PORT_SEARCH_LIMIT = 200
COMMAND_TIMEOUT_SECONDS = 30
ANCESTRY_LIMIT = 64
START_SLACK_SECONDS = 1
FULL_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
DEFAULT_MIGRATION_ID = r"^(.*?)(?:\.[^./]*)?$"

DOCKER_FIELDS = ("id", "name", "image", "ports", "compose_project", "working_dir", "compose_service")
DOCKER_FORMAT = "\t".join(
    [
        "{{.ID}}",
        "{{.Names}}",
        "{{.Image}}",
        "{{.Ports}}",
        '{{.Label "com.docker.compose.project"}}',
        '{{.Label "com.docker.compose.project.working_dir"}}',
        '{{.Label "com.docker.compose.service"}}',
    ]
)
PORT_MAPPING = re.compile(
    r"^(?:(?P<ip>.*):)?(?P<host>\d+)(?:-(?P<host_end>\d+))?->(?P<container>\d+)(?:-\d+)?/(?P<protocol>\w+)$"
)

# Processes `record` never accepts, whatever their working directory: Claude Code itself (the CLI, its npm
# package, the desktop app's bundled binary), desktop apps, IDEs and their helpers.
TOOL_EXECUTABLES = {
    "claude",
    "idea",
    "pycharm",
    "webstorm",
    "goland",
    "clion",
    "rider",
    "studio",
    "code",
    "cursor",
    "windsurf",
    "zed",
    "fsnotifier",
    "cef_server",
    "copilot-language-server",
    "gopls",
    "rust-analyzer",
}
# Interpreters whose program is their first argument: for them the script's path is the program's path.
INTERPRETERS = {"node", "bun", "deno", "python", "python3", "ruby", "perl", "sh", "bash", "zsh"}
TOOL_FRAGMENTS = (
    "/Claude.app/",
    "/claude.app/",
    "Application Support/Claude/",
    "@anthropic-ai/claude-code",
    "/claude-code/",
    "language-server",
    "tsserver",
    "/Visual Studio Code.app/",
    "/Cursor.app/",
    "/IntelliJ IDEA",
    "/PyCharm",
    "/WebStorm",
    "/Android Studio.app/",
)


class Refused(Exception):
    """A request the script will not carry out; printed as {"error": ...} with exit code 2."""


def stop_grace_seconds():
    """Seconds between SIGTERM and SIGKILL (QA_ENV_STOP_GRACE lowers it in the tests)."""
    try:
        return max(0.5, float(os.environ.get("QA_ENV_STOP_GRACE", "10")))
    except ValueError:
        return 10.0


def run(command, cwd=None, environment=None, timeout=COMMAND_TIMEOUT_SECONDS):
    """(exit code, stdout, stderr) of a command, or None when the executable is missing or hangs."""
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=environment
        )
    except (FileNotFoundError, PermissionError, NotADirectoryError, subprocess.TimeoutExpired):
        return None
    return completed.returncode, completed.stdout, completed.stderr


def _c_locale():
    return dict(os.environ, LC_ALL="C", LANG="C")


# --- Where a path belongs ----------------------------------------------------------------------------


def _read_gitdir(marker, worktree):
    with open(marker, encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content.startswith("gitdir:"):
        return None
    gitdir = content[len("gitdir:"):].strip()
    return os.path.realpath(os.path.join(worktree, gitdir))


def locate(path):
    """The git worktree holding `path` and its project (the main checkout), or None outside any repository."""
    if not path or not os.path.isabs(path) or not os.path.exists(path):
        return None
    current = os.path.realpath(path)
    while True:
        marker = os.path.join(current, ".git")
        if os.path.isdir(marker):
            return {"worktree": current, "project": current}
        if os.path.isfile(marker):
            gitdir = _read_gitdir(marker, current)
            if gitdir is None:
                return {"worktree": current, "project": current}
            commondir_file = os.path.join(gitdir, "commondir")
            if not os.path.isfile(commondir_file):
                # A submodule: its own project.
                return {"worktree": current, "project": current}
            with open(commondir_file, encoding="utf-8") as handle:
                common = os.path.realpath(os.path.join(gitdir, handle.read().strip()))
            project = os.path.dirname(common) if os.path.basename(common) == ".git" else common
            return {"worktree": current, "project": project}
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _slug(text):
    slug = re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-_")
    return slug or "x"


def compose_project_name(here):
    """This worktree's QA compose project: qa-<project>[-<worktree>]-<8 hex of the two real paths>.

    The names are only for reading; the hash tells apart two projects or worktrees whose names collide
    (`a/api` and `b/api`, `api` + worktree `x` and `api-x`)."""
    readable = _slug(os.path.basename(here["project"]))
    if here["worktree"] != here["project"]:
        readable += "-" + _slug(os.path.basename(here["worktree"]))
    digest = hashlib.sha1((here["project"] + "\0" + here["worktree"]).encode("utf-8")).hexdigest()[:8]
    return QA_PROJECT_PREFIX + readable[:40].rstrip("-_") + "-" + digest


def _in_worktree(path, here):
    where = locate(path)
    return bool(where and where["worktree"] == here["worktree"])


def _attribute(item, path, here):
    where = locate(path)
    item["project"] = where["project"] if where else None
    item["worktree"] = where["worktree"] if where else None
    item["same_project"] = bool(where and here and where["project"] == here["project"])
    item["same_worktree"] = bool(where and here and where["worktree"] == here["worktree"])


def _labelled_for_this_qa(container, here):
    """A container of this worktree's QA: its compose project and its compose working directory say so."""
    return container["compose_project"] == compose_project_name(here) and _in_worktree(container["working_dir"], here)


# --- What runs ---------------------------------------------------------------------------------------


def parse_ports(text):
    """Published ports of `docker ps` ("0.0.0.0:5432->5432/tcp, :::5432->5432/tcp"), one entry per host port."""
    ports = []
    seen = set()
    for part in (text or "").split(","):
        match = PORT_MAPPING.match(part.strip())
        if match is None:
            continue
        first = int(match.group("host"))
        last = int(match.group("host_end") or first)
        container = int(match.group("container"))
        for offset, host_port in enumerate(range(first, last + 1)):
            key = (host_port, match.group("protocol"))
            if key in seen:
                continue
            seen.add(key)
            ports.append({"host_port": host_port, "container_port": container + offset, "protocol": key[1]})
    return ports


def docker_containers(filters=(), include_stopped=False):
    """(containers, state): state is "ok" or "unavailable" (no docker, or its daemon does not answer)."""
    command = ["docker", "ps", "--no-trunc", "--format", DOCKER_FORMAT]
    if include_stopped:
        command.insert(2, "-a")
    for item in filters:
        command += ["--filter", item]
    result = run(command)
    if result is None or result[0] != 0:
        return [], "unavailable"
    containers = []
    for line in result[1].splitlines():
        if not line.strip():
            continue
        values = line.split("\t")
        values += [""] * (len(DOCKER_FIELDS) - len(values))
        container = dict(zip(DOCKER_FIELDS, values))
        container["ports"] = parse_ports(container["ports"])
        containers.append(container)
    return containers, "ok"


def _listening_sockets():
    result = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"])
    if result is None:
        return None
    # lsof exits 1 when nothing matches: no listener at all.
    sockets = []
    seen = set()
    pid = None
    command = ""
    for line in result[1].splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            pid = int(value)
            command = ""
        elif field == "c":
            command = value
        elif field == "n" and pid is not None and ":" in value:
            address, port = value.rsplit(":", 1)
            if not port.isdigit() or (pid, int(port)) in seen:
                continue
            seen.add((pid, int(port)))
            sockets.append({"pid": pid, "command": command, "address": address, "port": int(port)})
    return sockets


def _working_directories(pids):
    if not pids:
        return {}
    result = run(["lsof", "-a", "-p", ",".join(str(pid) for pid in sorted(pids)), "-d", "cwd", "-Fpn"])
    if result is None:
        return {}
    directories = {}
    pid = None
    for line in result[1].splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            directories[pid] = line[1:]
    return directories


def listening_processes():
    """(listeners, state): each listening TCP socket with its process, its working directory, "ok" or "unavailable"."""
    sockets = _listening_sockets()
    if sockets is None:
        return [], "unavailable"
    directories = _working_directories({item["pid"] for item in sockets})
    for item in sockets:
        item["cwd"] = directories.get(item["pid"])
    return sockets, "ok"


def context_of(root):
    here = locate(os.path.abspath(root))
    if here is None:
        raise Refused("not inside a git repository: " + os.path.abspath(root))
    return here


def inventory(root):
    here = context_of(root)
    containers, docker_state = docker_containers()
    listeners, lsof_state = listening_processes()
    by_port = {}
    for container in containers:
        _attribute(container, container["working_dir"], here)
        for port in container["ports"]:
            by_port[port["host_port"]] = container
    for listener in listeners:
        container = by_port.get(listener["port"])
        if container is not None:
            # Docker's port forwarder listens for the container: the container's project owns the port.
            listener["container"] = container["name"]
            for key in ("project", "worktree", "same_project", "same_worktree"):
                listener[key] = container[key]
        else:
            _attribute(listener, listener["cwd"], here)
    return {
        "context": dict(here, compose_project=compose_project_name(here)),
        "docker": docker_state,
        "lsof": lsof_state,
        "containers": containers,
        "listeners": listeners,
    }


# --- Processes ---------------------------------------------------------------------------------------


def process_identity(pid):
    """(command, start time) of a running process, or None when it is gone: a reused PID changes both."""
    values = []
    for column in ("command=", "lstart="):
        result = run(["ps", "-ww", "-o", column, "-p", str(pid)], environment=_c_locale())
        if result is None or result[0] != 0 or not result[1].strip():
            return None
        values.append(result[1].strip())
    return values[0], values[1]


def start_epoch(lstart):
    """Seconds since the epoch of a C-locale `ps -o lstart` value ("Sat Nov 14 16:44:01 2026"), or None."""
    try:
        return time.mktime(time.strptime(" ".join(lstart.split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError):
        return None


def parent_of(pid):
    result = run(["ps", "-o", "ppid=", "-p", str(pid)])
    if result is None or result[0] != 0 or not result[1].strip().isdigit():
        return None
    return int(result[1].strip())


def ancestry(pid):
    """`pid` and its ancestors, nearest first, up to the init process."""
    chain = []
    current = pid
    while current and current > 1 and current not in chain and len(chain) < ANCESTRY_LIMIT:
        chain.append(current)
        current = parent_of(current)
    return chain


def process_executable(pid):
    """The executable path of a running process (`ps -o comm=`), or None."""
    result = run(["ps", "-o", "comm=", "-p", str(pid)], environment=_c_locale())
    if result is None or result[0] != 0 or not result[1].strip():
        return None
    return result[1].strip()


def is_tool_process(command, executable=None):
    """Claude Code, a desktop app or an IDE helper: never a process a QA started.

    Only the program's path is judged — the executable, and an interpreter's script — never its other
    arguments (a dev server given a path that happens to contain `Claude.app` is still a dev server)."""
    words = command.split()
    if not words:
        return True
    programs = [path for path in (executable, words[0]) if path]
    if os.path.basename(words[0]) in INTERPRETERS or (executable and os.path.basename(executable) in INTERPRETERS):
        programs.extend(words[1:2])
    for program in programs:
        if os.path.basename(program) in TOOL_EXECUTABLES:
            return True
        if any(fragment in program for fragment in TOOL_FRAGMENTS):
            return True
    return False


BUILD_DAEMONS = ("org.gradle.launcher.daemon", "GradleDaemon", "KotlinCompileDaemon", "kotlin-daemon")


def _is_build_daemon(pid):
    """A build tool's long-lived daemon (Gradle, Kotlin): what it runs is detached from the shell that asked."""
    identity = process_identity(pid)
    return identity is not None and any(marker in identity[0] for marker in BUILD_DAEMONS)


def group_members(group):
    """PIDs of the live processes in process group `group` (zombies excluded; empty when none is left)."""
    result = run(["ps", "-A", "-o", "pid=,pgid=,stat="])
    if result is None or result[0] != 0:
        return None
    members = []
    for line in result[1].splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == str(group) and not fields[2].startswith("Z"):
            members.append(int(fields[0]))
    return members


# --- Ports -------------------------------------------------------------------------------------------


def port_is_free(port):
    """True when nothing on this machine can be listening on `port`: binding it succeeds on every loopback."""
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::1")):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        try:
            probe.bind((address, port))
        except OSError as error:
            if family == socket.AF_INET6 and error.errno not in (errno.EADDRINUSE, errno.EACCES):
                continue  # no IPv6 loopback on this machine: nothing can listen there either
            return False
        finally:
            probe.close()
    return True


def lock_directory():
    return os.environ.get("QA_PORT_LOCKS") or "/tmp/qa-ports-%d" % os.getuid()


def lock_owner(port):
    """The worktree holding the lock of `port`, "" for an unreadable lock, or None when there is none."""
    path = os.path.join(lock_directory(), str(port))
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("worktree") or ""
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError):
        return ""


def _stale(owner):
    """A lock whose worktree no longer exists: its QA is gone, the lock can be reclaimed."""
    return bool(owner) and not os.path.isdir(owner)


def reserve_port(port, here):
    """Take the machine-wide lock of `port` for this worktree; False when another live worktree holds it."""
    directory = lock_directory()
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    except OSError as error:
        raise Refused("cannot create the port lock directory %s (%s): set QA_PORT_LOCKS" % (directory, error))
    path = os.path.join(directory, str(port))
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            owner = lock_owner(port)
            if owner == here["worktree"]:
                return True
            if _stale(owner) and _reclaim(path, owner):
                continue
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"worktree": here["worktree"], "created": time.time()}, handle)
        return True
    return False


def _reclaim(path, stale_owner):
    """Take a stale lock out of the way: only the process whose rename succeeds may remove it, and only when
    what it moved is still that stale lock — a fresh lock another QA put there meanwhile is put back."""
    moved = "%s.stale-%d-%s" % (path, os.getpid(), os.urandom(4).hex())
    try:
        os.rename(path, moved)
    except FileNotFoundError:
        return True  # another QA reclaimed it first: try to create ours
    try:
        with open(moved, encoding="utf-8") as handle:
            owner = json.load(handle).get("worktree") or ""
    except (OSError, ValueError, AttributeError):
        owner = ""
    if owner == stale_owner:
        os.remove(moved)
        return True
    try:
        os.link(moved, path)  # someone else's fresh lock: put it back (fails if a third one exists)
    except FileExistsError:
        pass
    os.remove(moved)
    return False


def release_port(port, here):
    """Remove the lock of `port` when, and only when, this worktree holds it."""
    if lock_owner(port) == here["worktree"]:
        try:
            os.remove(os.path.join(lock_directory(), str(port)))
        except FileNotFoundError:
            pass
        return True
    return False


def free_port(preferred, taken=(), here=None, reserve=False):
    """The first port from `preferred` on that is not in `taken`, not bound, and not reserved by another QA.

    With `reserve`, the port is also locked for `here` before it is returned."""
    for port in range(preferred, min(preferred + PORT_SEARCH_LIMIT, 65536)):
        if port in taken or not port_is_free(port):
            continue
        if reserve:
            if reserve_port(port, here):
                return port
            continue
        owner = lock_owner(port)
        if owner is None or _stale(owner) or (here is not None and owner == here["worktree"]):
            return port
    raise Refused("no free port in %d-%d" % (preferred, preferred + PORT_SEARCH_LIMIT - 1))


def taken_ports(listing):
    """Ports something listens on or a container publishes (a recorded service that still runs is among them)."""
    ports = {listener["port"] for listener in listing["listeners"]}
    ports |= {port["host_port"] for container in listing["containers"] for port in container["ports"]}
    return ports


def occupant(listing, port):
    """Who holds `port`, for the brief: a container or a process, with its project and worktree."""
    for container in listing["containers"]:
        if any(item["host_port"] == port for item in container["ports"]):
            return {
                "kind": "container",
                "name": container["name"],
                "compose_project": container["compose_project"],
                "project": container["project"],
                "worktree": container["worktree"],
            }
    for listener in listing["listeners"]:
        if listener["port"] == port:
            return {
                "kind": "process",
                "pid": listener["pid"],
                "command": listener["command"],
                "project": listener["project"],
                "worktree": listener["worktree"],
            }
    owner = lock_owner(port)
    if owner:
        return {"kind": "reserved", "worktree": owner}
    return None


# --- started.json ------------------------------------------------------------------------------------


def started_path(here):
    return os.path.join(here["worktree"], STATE_DIRECTORY, STARTED_FILE)


def load_started(here):
    path = started_path(here)
    if not os.path.exists(path):
        return {"worktree": here["worktree"], "compose_project": compose_project_name(here), "entries": []}
    with open(path, encoding="utf-8") as handle:
        started = json.load(handle)
    if started.get("worktree") != here["worktree"]:
        raise Refused("%s belongs to another worktree: %s" % (path, started.get("worktree")))
    started.setdefault("entries", [])
    return started


def save_started(here, started):
    path = started_path(here)
    if not started["entries"] and not started.get("ports") and not started.get("prepared_at"):
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(started, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


# --- Migrations --------------------------------------------------------------------------------------


def glob_to_regex(pattern):
    """A path glob as a regex: `**` crosses directories, `*` and `?` do not."""
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            expression += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += "[^/]"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return re.compile("^" + expression + "$")


def _matching(paths, globs):
    patterns = [glob_to_regex(item) for item in globs]
    return sorted(path for path in paths if any(pattern.match(path) for pattern in patterns))


def changed_migrations(worktree, base, globs):
    """Migration files the worktree adds or changes against `base`: committed, staged, unstaged or untracked."""
    if not globs:
        return []
    committed = run(["git", "diff", "--name-only", "--diff-filter=AMR", base + "...HEAD"], cwd=worktree)
    if committed is None or committed[0] != 0:
        reason = "git is missing" if committed is None else committed[2].strip()
        raise Refused("cannot diff the worktree against %s: %s" % (base, reason))
    local = run(["git", "status", "--porcelain", "--untracked-files=all", "--no-renames"], cwd=worktree)
    paths = set(committed[1].splitlines())
    for line in (local[1] if local else "").splitlines():
        if len(line) > 3 and line[:2].strip() != "D":
            paths.add(line[3:])
    return _matching(paths, globs)


def worktree_migrations(worktree, globs):
    """Every migration file of the worktree (tracked or not, ignored files aside)."""
    listed = run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=worktree)
    if listed is None or listed[0] != 0:
        raise Refused("cannot list the worktree's files")
    return [path for path in _matching(set(listed[1].splitlines()), globs) if os.path.isfile(os.path.join(worktree, path))]


def migration_ids(paths, pattern, normalise=False):
    """The migration identifiers of `paths`: group 1 of `pattern` on each file name. With `normalise`
    (a project's own `migration_id`), `_` becomes `.`: Flyway reads V1_1__x.sql as version 1.1."""
    expression = re.compile(pattern)
    ids = set()
    for path in paths:
        match = expression.search(os.path.basename(path))
        if match and match.group(1):
            ids.add(match.group(1).replace("_", ".") if normalise else match.group(1))
    return ids


def applied_migrations(service, port, worktree):
    """(identifiers, None) applied on the running database, or (None, why they could not be read)."""
    command = service.get("applied_migrations")
    if not command:
        return None, "no applied_migrations command to read the database's history"
    environment = dict(os.environ, QA_DB_HOST="127.0.0.1", QA_DB_PORT=str(port))
    result = run(["sh", "-c", command], cwd=worktree, environment=environment)
    if result is None:
        return None, "applied_migrations did not answer"
    if result[0] != 0:
        return None, "applied_migrations failed (exit %d): %s" % (result[0], result[2].strip()[:200])
    return {line.strip() for line in result[1].splitlines() if line.strip()}, None


def database_compatibility(service, port, migrations):
    """(compatible, reason) of a running database with the worktree's migrations: equal sets only."""
    applied, problem = applied_migrations(service, port, migrations["worktree"])
    if applied is None:
        return False, problem + ": cannot compare, never reused"
    missing = sorted(migrations["ids"] - applied)
    ahead = sorted(applied - migrations["ids"])
    if missing:
        return False, "the database lacks the worktree's migrations %s" % ", ".join(missing[:5])
    if ahead:
        return False, "the database has migrations the worktree lacks: %s" % ", ".join(ahead[:5])
    return True, None


# --- Plan --------------------------------------------------------------------------------------------


def _published_port(container, wanted):
    for port in container["ports"]:
        if port["container_port"] == wanted:
            return port["host_port"]
    return container["ports"][0]["host_port"] if container["ports"] else None


def _process_alive(entry):
    identity = process_identity(entry["pid"])
    return identity is not None and identity == (entry.get("command"), entry.get("started"))


def decide(service, listing, started, forced_isolation, here, taken, migrations):
    """Reuse a running service, or start one on a reserved port. A database is reused only when the change
    carries no migration and its applied migrations equal the worktree's; isolation, once required
    (`forced_isolation` says why), holds whatever the service's kind."""
    name = service["name"]
    port = int(service["port"])
    shared = bool(service.get("shared"))
    database = bool(service.get("database"))
    ours = compose_project_name(here)
    kind = service.get("kind", "process")
    isolation_reasons = []
    if database and forced_isolation:
        isolation_reasons.append(forced_isolation)

    def reuse_allowed(candidate_port):
        if not database:
            return True
        if forced_isolation:
            return False
        compatible, reason = database_compatibility(service, candidate_port, migrations)
        if not compatible:
            isolation_reasons.append(reason)
        return compatible

    if kind == "container":
        candidates = [
            container
            for container in listing["containers"]
            if container["compose_service"] == service.get("compose_service", name) and container["same_project"]
        ]
        mine = [container for container in candidates if _labelled_for_this_qa(container, here)]
        if mine and _published_port(mine[0], service.get("container_port", port)):
            return {
                "name": name,
                "action": "reuse",
                "port": _published_port(mine[0], service.get("container_port", port)),
                "started_by_this_qa": True,
                "container": mine[0]["name"],
                "recorded": any(
                    entry["kind"] == "container" and entry.get("id") == mine[0]["id"] for entry in started["entries"]
                ),
            }
        for container in candidates:
            if container["compose_project"].startswith(QA_PROJECT_PREFIX):
                continue  # another worktree's QA: it stops it when its QA ends
            if not (shared or container["same_worktree"]):
                continue
            published = _published_port(container, service.get("container_port", port))
            if published and reuse_allowed(published):
                return {
                    "name": name,
                    "action": "reuse",
                    "port": published,
                    "started_by_this_qa": False,
                    "container": container["name"],
                }
    else:
        for entry in started["entries"]:
            if entry["kind"] == "process" and entry["name"] == name and _process_alive(entry):
                return {"name": name, "action": "reuse", "port": entry["port"], "started_by_this_qa": True, "pid": entry["pid"]}
        for listener in listing["listeners"]:
            if listener["port"] != port or listener.get("container"):
                continue
            if (listener["same_worktree"] or (shared and listener["same_project"])) and reuse_allowed(port):
                return {"name": name, "action": "reuse", "port": port, "started_by_this_qa": False, "pid": listener["pid"]}
    chosen = free_port(port, taken, here, reserve=True)
    decision = {"name": name, "action": "start", "port": chosen}
    if kind == "container":
        decision["compose_project"] = ours
        decision["container_port"] = int(service.get("container_port", port))
    if database:
        decision["isolated"] = True
        decision["reason"] = "; ".join(isolation_reasons) or "no compatible running database of this project"
    if chosen != port:
        decision["default_port_taken_by"] = occupant(listing, port) or {"kind": "unknown", "note": "bound, owner not visible"}
    return decision


def _validate_spec(spec, base):
    services = spec.get("services")
    if not isinstance(services, list) or not services:
        raise Refused("the spec has no services")
    for service in services:
        if not service.get("name") or not isinstance(service.get("port"), int):
            raise Refused("every service needs a name and an integer port: %r" % (service,))
    if spec.get("migrations") and not base:
        raise Refused("the spec declares migrations: --base <ref the change branches from> is required")
    if any(service.get("database") for service in services) and "migrations" not in spec:
        raise Refused(
            "a database service needs the spec's `migrations`: its globs, or [] when the schema is not managed by"
            " migration files (the database is then never reused)"
        )


def plan(root, spec_path, base, force_pending):
    here = context_of(root)
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    _validate_spec(spec, base)
    globs = spec.get("migrations") or []
    listing = inventory(root)
    started = load_started(here)
    changed = changed_migrations(here["worktree"], base, globs) if globs else []
    present = worktree_migrations(here["worktree"], globs) if globs else []
    migrations = {
        "worktree": here["worktree"],
        "ids": migration_ids(present, spec.get("migration_id") or DEFAULT_MIGRATION_ID, bool(spec.get("migration_id"))),
    }
    if force_pending:
        forced = "a migration was declared (--pending-migration)"
    elif changed:
        forced = "the change adds or edits migrations (%s): the shared database is never migrated by a QA" % ", ".join(changed[:5])
    elif "migrations" in spec and not globs:
        forced = "the spec declares no migration files (`migrations: []`, schema managed elsewhere): never reused"
    else:
        forced = None
    started.setdefault("prepared_at", time.time())
    taken = taken_ports(listing)
    decisions = []
    for service in spec["services"]:
        decision = decide(service, listing, started, forced, here, taken, migrations)
        if decision["action"] == "start":
            taken.add(decision["port"])
            started.setdefault("ports", [])
            if decision["port"] not in started["ports"]:
                started["ports"].append(decision["port"])
        decisions.append(decision)
    save_started(here, started)
    return {
        "context": listing["context"],
        "docker": listing["docker"],
        "lsof": listing["lsof"],
        "migrations": changed,
        "forced_isolation": forced,
        "port_locks": lock_directory(),
        "services": decisions,
    }


# --- launch, record and cleanup ----------------------------------------------------------------------


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _identity_key(entry):
    return (entry["kind"], entry.get("pid") if entry["kind"] == "process" else entry.get("id"))


def _add_entry(started, entry):
    """Add an entry; the same process or container recorded again replaces its former entry, never another one."""
    started["entries"] = [item for item in started["entries"] if _identity_key(item) != _identity_key(entry)]
    started["entries"].append(entry)


def _opened(here):
    started = load_started(here)
    if not started.get("prepared_at"):
        raise Refused("this QA is not open: run `plan` first (it records when the QA started)")
    return started


def launch(root, name, command):
    """Write this process as a launcher of the QA, then become `command` (same PID, same start time)."""
    here = context_of(root)
    if not command:
        raise Refused("launch needs a command after --")
    started = _opened(here)
    identity = process_identity(os.getpid())
    if identity is None:
        raise Refused("cannot read this process's start time")
    started.setdefault("launchers", [])
    started["launchers"].append({"name": name, "pid": os.getpid(), "started": identity[1], "command": command, "launched_at": _now()})
    save_started(here, started)
    sys.stdout.flush()
    os.execvp(command[0], command)


def _trusted_anchors(started):
    """PIDs whose descendants this QA started: the shell running `record`, and the live launchers of this QA."""
    anchors = {os.getppid()}
    for launcher in started.get("launchers", []):
        identity = process_identity(launcher["pid"])
        if identity is not None and identity[1] == launcher["started"]:
            anchors.add(launcher["pid"])
    return anchors


def record_container(root, name, container_id, service):
    here = context_of(root)
    ours = compose_project_name(here)
    if container_id:
        filters = ["id=" + container_id]
    elif service:
        filters = ["label=com.docker.compose.project=" + ours, "label=com.docker.compose.service=" + service]
    else:
        raise Refused("record container needs --id or --service")
    containers, state = docker_containers(filters)
    if state != "ok":
        raise Refused("docker does not answer")
    if not containers:
        raise Refused("no running container matches %s" % ", ".join(filters))
    started = load_started(here)
    recorded = []
    for container in containers:
        if not _labelled_for_this_qa(container, here):
            raise Refused(
                "container %s is not this QA's (compose project %r, working directory %r; this QA: %s in %s)"
                % (container["name"], container["compose_project"], container["working_dir"], ours, here["worktree"])
            )
        if not FULL_CONTAINER_ID.fullmatch(container["id"]):
            raise Refused("docker did not give the full id of %s" % container["name"])
        entry = {
            "name": name,
            "kind": "container",
            "id": container["id"],
            "container": container["name"],
            "compose_project": container["compose_project"],
            "working_dir": container["working_dir"],
            "port": container["ports"][0]["host_port"] if container["ports"] else None,
            "recorded_at": _now(),
        }
        _add_entry(started, entry)
        recorded.append(entry)
    save_started(here, started)
    return {"recorded": recorded}


def record_process(root, name, port):
    here = context_of(root)
    started = _opened(here)
    listeners, state = listening_processes()
    if state != "ok":
        raise Refused("lsof is not available")
    matching = [listener for listener in listeners if listener["port"] == port]
    if not matching:
        raise Refused("nothing listens on port %d" % port)
    listener = matching[0]
    pid = listener["pid"]
    cwd = listener.get("cwd")
    if not _in_worktree(cwd, here):
        raise Refused(
            "the process on port %d (pid %d, %s) runs from %r, not from this worktree: not started by this QA"
            % (port, pid, listener["command"], cwd)
        )
    identity = process_identity(pid)
    if identity is None:
        raise Refused("process %d is gone" % pid)
    if is_tool_process(identity[0], process_executable(pid)):
        raise Refused("pid %d is Claude Code, a desktop app or an IDE helper (%s): never a QA service" % (pid, identity[0][:120]))
    began = start_epoch(identity[1])
    if began is None or began < started["prepared_at"] - START_SLACK_SECONDS:
        raise Refused("pid %d started before this QA was prepared (%s): not started by this QA" % (pid, identity[1]))
    anchors = _trusted_anchors(started)
    chain = ancestry(pid)
    if not anchors.intersection(chain):
        daemons = [ancestor for ancestor in chain[1:] if _is_build_daemon(ancestor)]
        hint = ""
        if daemons:
            hint = (
                "; it was started by a build daemon (pid %d): launch it without one, e.g. `./gradlew bootRun --no-daemon`"
                % daemons[0]
            )
        raise Refused(
            "pid %d descends neither from the shell recording it nor from a `launch` of this QA: not started by this QA%s"
            % (pid, hint)
        )
    try:
        group = os.getpgid(pid)
    except OSError:
        group = None
    entry = {
        "name": name,
        "kind": "process",
        "pid": pid,
        "process_group": group,
        "command": identity[0],
        "started": identity[1],
        "cwd": os.path.realpath(cwd),
        "port": port,
        "recorded_at": _now(),
    }
    _add_entry(started, entry)
    save_started(here, started)
    return {"recorded": [entry]}


def _still_running(entry, identity, as_group):
    if as_group:
        members = group_members(entry["pid"])
        return members is None or bool(members)
    return process_identity(entry["pid"]) == identity


def _signal(entry, as_group, number):
    try:
        if as_group:
            os.killpg(entry["pid"], number)
        else:
            os.kill(entry["pid"], number)
    except ProcessLookupError:
        pass


def _stop_process(entry, dry_run):
    identity = process_identity(entry["pid"])
    if identity is None:
        return "gone"
    if identity != (entry["command"], entry["started"]):
        return "skipped: pid %d now runs another process (%s); left running, kept in started.json" % (
            entry["pid"],
            identity[0][:80],
        )
    if dry_run:
        return "would stop"
    as_group = entry.get("process_group") == entry["pid"]
    _signal(entry, as_group, signal.SIGTERM)
    grace = stop_grace_seconds()
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _still_running(entry, identity, as_group):
            return "stopped"
        time.sleep(0.1)
    _signal(entry, as_group, signal.SIGKILL)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _still_running(entry, identity, as_group):
            return "stopped (killed after %gs)" % grace
        time.sleep(0.1)
    return "failed: still running after SIGKILL"


def _stop_container(entry, here, dry_run):
    if not FULL_CONTAINER_ID.fullmatch(entry.get("id") or ""):
        return "skipped: %r is not a full container id; left running, kept in started.json" % entry.get("id")
    found, state = docker_containers(["id=" + entry["id"]], include_stopped=True)
    if state != "ok":
        return "failed: docker does not answer"
    if not found:
        return "gone"
    if not _labelled_for_this_qa(found[0], here):
        return "skipped: container %s is no longer labelled for this QA; left running, kept in started.json" % found[0]["name"]
    if dry_run:
        return "would stop"
    for command in (["docker", "stop", entry["id"]], ["docker", "rm", "-v", entry["id"]]):
        result = run(command)
        if result is None or result[0] != 0:
            return "failed: " + " ".join(command[:2])
    return "stopped"


def _remove_compose_leftovers(project, dry_run):
    """Volumes and networks of this QA's own compose project, once its containers are gone."""
    removed = []
    for kind in ("volume", "network"):
        listed = run(["docker", kind, "ls", "-q", "--filter", "label=com.docker.compose.project=" + project])
        if listed is None or listed[0] != 0:
            continue
        for item in listed[1].split():
            if dry_run:
                removed.append("%s %s (would remove)" % (kind, item))
                continue
            result = run(["docker", kind, "rm", item])
            if result is not None and result[0] == 0:
                removed.append("%s %s" % (kind, item))
    return removed


def cleanup(root, dry_run):
    here = context_of(root)
    started = load_started(here)
    ours = compose_project_name(here)
    outcomes = []
    remaining = []
    for entry in started["entries"]:
        if entry["kind"] == "process":
            outcome = _stop_process(entry, dry_run)
        else:
            outcome = _stop_container(entry, here, dry_run)
        outcomes.append({"name": entry["name"], "kind": entry["kind"], "outcome": outcome})
        if outcome.startswith("failed") or outcome.startswith("skipped"):
            remaining.append(entry)
    leftovers = []
    started_containers_of_ours = any(
        entry["kind"] == "container" and entry.get("compose_project") == ours for entry in started["entries"]
    )
    containers_left = any(entry["kind"] == "container" for entry in remaining)
    if started_containers_of_ours and not containers_left:
        leftovers = _remove_compose_leftovers(ours, dry_run)
    released = []
    if not dry_run:
        still_used = {entry.get("port") for entry in remaining}
        for port in started.get("ports", []):
            if port not in still_used and release_port(port, here):
                released.append(port)
        started["entries"] = remaining
        started["ports"] = [port for port in started.get("ports", []) if port in still_used]
        if not remaining:
            started.pop("prepared_at", None)
            started.pop("launchers", None)
        save_started(here, started)
    return {
        "dry_run": dry_run,
        "stopped": outcomes,
        "removed": leftovers,
        "released_ports": released,
        "left_in_started_json": len(remaining),
    }


# --- Command line ------------------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="the worktree the QA is for (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    planning = commands.add_parser("plan")
    planning.add_argument("--spec", required=True)
    planning.add_argument("--base", help="the ref the change branches from (origin/main): required with migrations")
    planning.add_argument("--pending-migration", action="store_true", help="isolate every database service")
    finding = commands.add_parser("free-port")
    finding.add_argument("preferred", type=int)
    launching = commands.add_parser("launch")
    launching.add_argument("--name", required=True)
    launching.add_argument("program", nargs=argparse.REMAINDER)
    recording = commands.add_parser("record")
    kinds = recording.add_subparsers(dest="kind", required=True)
    container = kinds.add_parser("container")
    container.add_argument("--name", required=True)
    container.add_argument("--id")
    container.add_argument("--service")
    process = kinds.add_parser("process")
    process.add_argument("--name", required=True)
    process.add_argument("--port", type=int, required=True)
    cleaning = commands.add_parser("cleanup")
    cleaning.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "inventory":
            output = inventory(arguments.root)
        elif arguments.command == "plan":
            output = plan(arguments.root, arguments.spec, arguments.base, arguments.pending_migration)
        elif arguments.command == "free-port":
            here = context_of(arguments.root)
            output = {"port": free_port(arguments.preferred, taken_ports(inventory(arguments.root)), here)}
        elif arguments.command == "launch":
            program = arguments.program[1:] if arguments.program[:1] == ["--"] else arguments.program
            launch(arguments.root, arguments.name, program)
            return 2  # not reached: launch execs
        elif arguments.command == "record" and arguments.kind == "container":
            output = record_container(arguments.root, arguments.name, arguments.id, arguments.service)
        elif arguments.command == "record":
            output = record_process(arguments.root, arguments.name, arguments.port)
        else:
            output = cleanup(arguments.root, arguments.dry_run)
    except Refused as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(output, indent=2))
    if arguments.command == "cleanup" and output["left_in_started_json"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
