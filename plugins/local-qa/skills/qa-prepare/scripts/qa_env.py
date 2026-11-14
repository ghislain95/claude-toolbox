#!/usr/bin/env python3
"""The deterministic half of /local-qa:qa-prepare (Python 3.9+, standard library only).

    qa_env.py inventory                         what runs on the machine, each item with its project and worktree
    qa_env.py plan --spec <file> [--base <ref>] [--pending-migration]
                                                per service of the spec: reuse a running one, or start one on a port
    qa_env.py free-port <preferred>             the first free port from <preferred> on
    qa_env.py record container --name <n> (--id <id> | --service <compose service>)
    qa_env.py record process --name <n> --port <port>
                                                add what this QA started to .claude/qa/started.json
    qa_env.py cleanup [--dry-run]               stop exactly what started.json lists, nothing else

Every command prints JSON on stdout. `--root <dir>` (default: the current directory) is the worktree the
QA is for. Exit codes: 0 done, 1 done with failures (listed in the JSON), 2 refused or usage error.

Rules it enforces, so that a mistake of the agent cannot disturb another project or agent:
- it never stops, restarts or reconfigures anything; only `cleanup` stops, and only what `record` wrote;
- `record` accepts a container only under this worktree's compose project (`qa-<project>-<worktree>`),
  and a process only when it runs from inside this worktree;
- `cleanup` checks that a recorded process is still the one it started (command and start time) before
  signalling it, so a reused PID is never killed.
"""

import argparse
import datetime
import errno
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
STOP_GRACE_SECONDS = 10
COMMAND_TIMEOUT_SECONDS = 30

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


class Refused(Exception):
    """A request the script will not carry out; printed as {"error": ...} with exit code 2."""


def run(command, cwd=None):
    """(exit code, stdout, stderr) of a command, or None when the executable is missing or hangs."""
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return None
    return completed.returncode, completed.stdout, completed.stderr


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
    """The compose project this worktree's QA starts its containers under: qa-<project>[-<worktree>]."""
    project = _slug(os.path.basename(here["project"]))
    if here["worktree"] == here["project"]:
        return QA_PROJECT_PREFIX + project
    return QA_PROJECT_PREFIX + project + "-" + _slug(os.path.basename(here["worktree"]))


def _attribute(item, path, here):
    where = locate(path)
    item["project"] = where["project"] if where else None
    item["worktree"] = where["worktree"] if where else None
    item["same_project"] = bool(where and here and where["project"] == here["project"])
    item["same_worktree"] = bool(where and here and where["worktree"] == here["worktree"])


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


def free_port(preferred, taken=()):
    """The first port from `preferred` on that is neither in `taken` nor bound on this machine."""
    for port in range(preferred, min(preferred + PORT_SEARCH_LIMIT, 65536)):
        if port not in taken and port_is_free(port):
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
    return started


def save_started(here, started):
    path = started_path(here)
    if not started["entries"]:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(started, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def process_identity(pid):
    """(command, start time) of a running process, or None when it is gone: a reused PID changes both."""
    values = []
    for column in ("command=", "lstart="):
        result = run(["ps", "-ww", "-o", column, "-p", str(pid)])
        if result is None or result[0] != 0 or not result[1].strip():
            return None
        values.append(result[1].strip())
    return values[0], values[1]


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
    patterns = [glob_to_regex(item) for item in globs]
    return sorted(path for path in paths if any(pattern.match(path) for pattern in patterns))


# --- Plan --------------------------------------------------------------------------------------------


def _published_port(container, wanted):
    for port in container["ports"]:
        if port["container_port"] == wanted:
            return port["host_port"]
    return container["ports"][0]["host_port"] if container["ports"] else None


def _process_alive(entry):
    identity = process_identity(entry["pid"])
    return identity is not None and identity == (entry.get("command"), entry.get("started"))


def decide(service, listing, started, pending, ours, taken):
    name = service["name"]
    port = int(service["port"])
    shared = bool(service.get("shared"))
    isolated_database = bool(service.get("database")) and bool(pending)
    if service.get("kind", "process") == "container":
        candidates = [
            container
            for container in listing["containers"]
            if container["compose_service"] == service.get("compose_service", name) and container["same_project"]
        ]
        mine = [container for container in candidates if container["compose_project"] == ours]
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
        if not isolated_database:
            for container in candidates:
                if container["compose_project"].startswith(QA_PROJECT_PREFIX):
                    continue  # another worktree's QA: it stops it when its QA ends
                if not (shared or container["same_worktree"]):
                    continue
                published = _published_port(container, service.get("container_port", port))
                if published:
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
            if listener["same_worktree"] or (shared and listener["same_project"]):
                return {"name": name, "action": "reuse", "port": port, "started_by_this_qa": False, "pid": listener["pid"]}
    chosen = free_port(port, taken)
    decision = {"name": name, "action": "start", "port": chosen}
    if service.get("kind", "process") == "container":
        decision["compose_project"] = ours
        decision["container_port"] = int(service.get("container_port", port))
    if isolated_database:
        decision["isolated"] = True
        decision["reason"] = "the change adds or edits migrations; the shared database is never migrated by a QA"
    if chosen != port:
        decision["default_port_taken_by"] = occupant(listing, port) or {"kind": "unknown", "note": "bound, owner not visible"}
    return decision


def plan(root, spec_path, base, force_pending):
    here = context_of(root)
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    services = spec.get("services")
    if not isinstance(services, list) or not services:
        raise Refused("the spec has no services")
    for service in services:
        if not service.get("name") or not isinstance(service.get("port"), int):
            raise Refused("every service needs a name and an integer port: %r" % (service,))
    listing = inventory(root)
    started = load_started(here)
    migrations = changed_migrations(here["worktree"], base, spec.get("migrations") or []) if base else []
    is_pending = bool(migrations) or force_pending
    ours = compose_project_name(here)
    taken = taken_ports(listing)
    decisions = []
    for service in services:
        decision = decide(service, listing, started, is_pending, ours, taken)
        if decision["action"] == "start":
            taken.add(decision["port"])
        decisions.append(decision)
    return {
        "context": listing["context"],
        "docker": listing["docker"],
        "lsof": listing["lsof"],
        "pending_migration": is_pending,
        "migrations": migrations,
        "services": decisions,
    }


# --- record and cleanup ------------------------------------------------------------------------------


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _identity_key(entry):
    return (entry["kind"], entry.get("pid") if entry["kind"] == "process" else entry.get("id"))


def _add_entry(started, entry):
    """Add an entry; the same process or container recorded again replaces its former entry, never another one."""
    started["entries"] = [item for item in started["entries"] if _identity_key(item) != _identity_key(entry)]
    started["entries"].append(entry)


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
        labelled_ours = container["compose_project"] == ours
        named_ours = not container["compose_project"] and container["name"].startswith(ours + "-")
        if not (labelled_ours or named_ours):
            raise Refused(
                "container %s is not under this QA's compose project %s (compose project: %r): not started by this QA"
                % (container["name"], ours, container["compose_project"])
            )
        entry = {
            "name": name,
            "kind": "container",
            "id": container["id"],
            "container": container["name"],
            "compose_project": container["compose_project"] or None,
            "port": container["ports"][0]["host_port"] if container["ports"] else None,
            "recorded_at": _now(),
        }
        _add_entry(started, entry)
        recorded.append(entry)
    save_started(here, started)
    return {"recorded": recorded}


def record_process(root, name, port):
    here = context_of(root)
    listeners, state = listening_processes()
    if state != "ok":
        raise Refused("lsof is not available")
    matching = [listener for listener in listeners if listener["port"] == port]
    if not matching:
        raise Refused("nothing listens on port %d" % port)
    listener = matching[0]
    cwd = listener.get("cwd")
    inside = cwd and (os.path.realpath(cwd) + os.sep).startswith(here["worktree"] + os.sep)
    if not inside:
        raise Refused(
            "the process on port %d (pid %d, %s) runs from %r, outside this worktree: not started by this QA"
            % (port, listener["pid"], listener["command"], cwd)
        )
    identity = process_identity(listener["pid"])
    if identity is None:
        raise Refused("process %d is gone" % listener["pid"])
    try:
        group = os.getpgid(listener["pid"])
    except OSError:
        group = None
    entry = {
        "name": name,
        "kind": "process",
        "pid": listener["pid"],
        "process_group": group,
        "command": identity[0],
        "started": identity[1],
        "cwd": os.path.realpath(cwd),
        "port": port,
        "recorded_at": _now(),
    }
    started = load_started(here)
    _add_entry(started, entry)
    save_started(here, started)
    return {"recorded": [entry]}


def _stop_process(entry, dry_run):
    identity = process_identity(entry["pid"])
    if identity is None:
        return "gone"
    if identity != (entry["command"], entry["started"]):
        return "skipped: pid %d now runs another process" % entry["pid"]
    if dry_run:
        return "would stop"
    as_group = entry.get("process_group") == entry["pid"]
    try:
        if as_group:
            os.killpg(entry["pid"], signal.SIGTERM)
        else:
            os.kill(entry["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline:
        if process_identity(entry["pid"]) != identity:
            return "stopped"
        time.sleep(0.1)
    try:
        if as_group:
            os.killpg(entry["pid"], signal.SIGKILL)
        else:
            os.kill(entry["pid"], signal.SIGKILL)
    except ProcessLookupError:
        pass
    return "stopped (killed after %ds)" % STOP_GRACE_SECONDS


def _stop_container(entry, dry_run):
    found, state = docker_containers(["id=" + entry["id"]], include_stopped=True)
    if state != "ok":
        return "failed: docker does not answer"
    if not found:
        return "gone"
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
            outcome = _stop_container(entry, dry_run)
        outcomes.append({"name": entry["name"], "kind": entry["kind"], "outcome": outcome})
        if outcome.startswith("failed"):
            remaining.append(entry)
    leftovers = []
    started_containers_of_ours = any(
        entry["kind"] == "container" and entry.get("compose_project") == ours for entry in started["entries"]
    )
    containers_left = any(entry["kind"] == "container" for entry in remaining)
    if started_containers_of_ours and not containers_left:
        leftovers = _remove_compose_leftovers(ours, dry_run)
    if not dry_run:
        started["entries"] = remaining
        save_started(here, started)
    return {"dry_run": dry_run, "stopped": outcomes, "removed": leftovers, "left_in_started_json": len(started["entries"])}


# --- Command line ------------------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="the worktree the QA is for (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    planning = commands.add_parser("plan")
    planning.add_argument("--spec", required=True)
    planning.add_argument("--base", help="the ref the change branches from, to find its migrations (origin/main)")
    planning.add_argument("--pending-migration", action="store_true", help="the change carries a migration")
    finding = commands.add_parser("free-port")
    finding.add_argument("preferred", type=int)
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
            output = {"port": free_port(arguments.preferred, taken_ports(inventory(arguments.root)))}
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
    if arguments.command == "cleanup" and any(item["outcome"].startswith("failed") for item in output["stopped"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
