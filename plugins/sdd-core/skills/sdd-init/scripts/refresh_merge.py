#!/usr/bin/env python3
"""Three-way merge of `/sdd-core:sdd-init --refresh` (Python 3.9+, standard library and git only).

    refresh_merge.py install-sha --skill-dir <sdd-init base directory> [--config-dir <dir>]
        the toolbox commit this sdd-init comes from, for the install marker: Claude Code's record of the
        installed plugin (installed_plugins.json, `gitCommitSha`), else a clean git checkout of the kit;
        {"sha": null, "reason": …} when neither proves it (the next refresh then merges two ways).

    refresh_merge.py read-marker <CLAUDE.md> [<.claude/CLAUDE.md>]
        the install marker: {"version", "sha" (null for markers written before 0.4.0), "options", "file"};
        "conflict" lists both files when each carries a marker. Exit 3 when there is none.

    refresh_merge.py fetch-base --sha <40 hex> --dest <empty dir> [--repository <url>]
        the sdd-init templates of that toolbox commit, into <dest>. Exit 0 {"status": "fetched"}; exit 3
        {"status": "missing-commit"} or {"status": "unreachable"}: the refresh falls back to two ways.
        `--repository` (or SDD_TOOLBOX_REPOSITORY) is for tests only: it is reported in the JSON and on stderr.

    refresh_merge.py merge --manifest <file.json> [--old-version <label>] [--new-version <label>]
        each {"path", "base", "theirs"}: `path` the project's file (ours), `base` the recorded commit's template
        filled with the project's values (null when there is no base commit), `theirs` the new template
        filled the same way. Every entry is checked and merged in memory first; files are written only when
        all of them could be merged. Exit 0 nothing left to settle; 1 conflicts (diff3 markers written, for
        the owner); 4 two-way entries (no base: nothing written, differences listed); 2 usage error, nothing
        written.
"""

import argparse
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

DEFAULT_REPOSITORY = "https://github.com/ghislain95/claude-toolbox"
TEMPLATES_PATH = "plugins/sdd-core/skills/sdd-init/templates"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA = re.compile(r"[0-9a-f]{40}")
MARKER = re.compile(
    r"<!--\s*(?:claude-toolbox|sdd-kit): installed (?P<version>\S+)(?: \((?P<sha>[^)]*)\))? on (?P<date>\S+)"
    r"(?: — options: (?P<options>.*?))?(?: — autonomy: [^ ]+)?\s*-->"
)
CONFLICT_LINE = re.compile(rb"^(?:<<<<<<<|>>>>>>>)(?: |\r?$)", re.MULTILINE)
NETWORK_TIMEOUT_SECONDS = 120


class UsageError(Exception):
    pass


def git(*arguments, cwd=None, binary=False):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        capture_output=True,
        text=not binary,
        env=environment,
        timeout=NETWORK_TIMEOUT_SECONDS,
    )


# --- The install marker's commit ---------------------------------------------------------------------


def _inside(path, directory):
    path = os.path.realpath(path)
    directory = os.path.realpath(directory)
    return path == directory or path.startswith(directory + os.sep)


def install_sha(skill_dir, config_dir=None):
    """The toolbox commit `skill_dir` was installed from, with how it is known, or why it is not."""
    config_dir = config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    record = os.path.join(config_dir, "plugins", "installed_plugins.json")
    try:
        with open(record, encoding="utf-8") as handle:
            installed = json.load(handle).get("plugins", {})
    except (OSError, ValueError, AttributeError):
        installed = {}
    for key, installs in installed.items():
        if not key.startswith("sdd-core@") or not isinstance(installs, list):
            continue
        for install in installs:
            if not isinstance(install, dict):
                continue
            path = install.get("installPath")
            sha = install.get("gitCommitSha")
            if path and _inside(skill_dir, path) and isinstance(sha, str) and SHA.fullmatch(sha):
                return {"sha": sha, "source": "installed_plugins.json", "version": install.get("version")}
    try:
        head = git("rev-parse", "HEAD", cwd=skill_dir)
        dirty = git("status", "--porcelain", "--", ".", cwd=skill_dir)
    except (OSError, subprocess.TimeoutExpired):
        head = dirty = None
    if head is not None and head.returncode == 0 and SHA.fullmatch(head.stdout.strip()):
        if dirty.returncode == 0 and not dirty.stdout.strip():
            return {"sha": head.stdout.strip(), "source": "git checkout"}
        return {"sha": None, "reason": "the kit's checkout has uncommitted changes: no commit describes these templates"}
    return {"sha": None, "reason": "no record of the installed plugin's commit and not a git checkout"}


def read_marker(paths):
    """The install marker of the first file that has one (the root CLAUDE.md first)."""
    found = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                matches = list(MARKER.finditer(handle.read()))
        except (OSError, UnicodeDecodeError):
            continue
        if matches:
            found.append((path, matches[-1]))
    if not found:
        return None
    path, match = found[0]
    version = match.group("version")
    sha = match.group("sha")
    result = {
        "file": path,
        "version": version if VERSION.fullmatch(version) else None,
        "sha": sha if sha and SHA.fullmatch(sha) else None,
        "date": match.group("date"),
        "options": [item.strip() for item in (match.group("options") or "").split(",") if item.strip()],
    }
    if len(found) > 1:
        result["conflict"] = [item[0] for item in found]
    return result


# --- The base templates ------------------------------------------------------------------------------


def fetch_base(sha, destination, repository, overridden):
    """The templates of toolbox commit `sha`, in `destination`; or why they could not be had."""
    if not SHA.fullmatch(sha or ""):
        raise UsageError("not a full commit sha: %r" % sha)
    if os.path.exists(destination) and os.listdir(destination):
        raise UsageError("destination is not empty: " + destination)
    report = {"sha": sha}
    if overridden:
        report["repository_override"] = repository
        sys.stderr.write("WARNING: base templates fetched from %s, not from %s\n" % (repository, DEFAULT_REPOSITORY))
    work = tempfile.mkdtemp(prefix="sdd-refresh-base-")
    try:
        git("init", "-q", work)
        try:
            fetched = git("fetch", "-q", "--depth", "1", repository, sha, cwd=work)
        except subprocess.TimeoutExpired:
            return dict(report, status="unreachable", reason="fetch timed out")
        if fetched.returncode != 0:
            try:
                reachable = git("ls-remote", repository, "HEAD", cwd=work).returncode == 0
            except subprocess.TimeoutExpired:
                reachable = False
            if not reachable:
                return dict(report, status="unreachable", reason=fetched.stderr.strip() or "git fetch failed")
            return dict(report, status="missing-commit", reason="%s has no commit %s" % (repository, sha))
        resolved = git("rev-parse", "FETCH_HEAD^{commit}", cwd=work)
        if resolved.returncode != 0 or resolved.stdout.strip() != sha:
            return dict(report, status="missing-commit", reason="the fetched commit is not %s" % sha)
        archive = git("archive", "--format=tar", sha, TEMPLATES_PATH, cwd=work, binary=True)
        if archive.returncode != 0:
            return dict(report, status="missing-commit", reason="commit %s has no %s" % (sha, TEMPLATES_PATH))
        os.makedirs(destination, exist_ok=True)
        prefix = TEMPLATES_PATH + "/"
        count = 0
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            for member in bundle.getmembers():
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                relative = os.path.normpath(member.name[len(prefix):])
                if relative.startswith("..") or os.path.isabs(relative):
                    continue
                target = os.path.join(destination, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with bundle.extractfile(member) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                os.chmod(target, member.mode & 0o777)
                count += 1
        return dict(report, status="fetched", files=count, path=os.path.abspath(destination))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --- The merge ---------------------------------------------------------------------------------------


def _read(path, role, entry_path):
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise UsageError("%s of %s is not UTF-8 text: %s" % (role, entry_path, path))
    return data


def _to_line_endings(data, crlf):
    lf = data.replace(b"\r\n", b"\n")
    return lf.replace(b"\n", b"\r\n") if crlf else lf


def _target(path):
    """The real file `path` writes to: a symlink resolved, a file that does not exist yet under its real directory."""
    if os.path.lexists(path):
        return os.path.realpath(path)
    return os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(path))), os.path.basename(path))


def _hunks(path, ours, theirs):
    return "".join(
        difflib.unified_diff(
            ours.decode("utf-8").splitlines(True), theirs.decode("utf-8").splitlines(True), "local/" + path, "kit/" + path
        )
    )


def _three_way(ours, base, theirs, old_label, new_label):
    work = tempfile.mkdtemp(prefix="sdd-refresh-merge-")
    try:
        names = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = os.path.join(work, name)
            with open(path, "wb") as handle:
                handle.write(data)
            names.append(path)
        merged = subprocess.run(
            ["git", "merge-file", "-p", "--diff3", "-L", "local", "-L", old_label, "-L", new_label, *names],
            capture_output=True,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if merged.returncode < 0 or merged.returncode > 127:
        raise UsageError("git merge-file failed: %s" % merged.stderr.decode(errors="replace"))
    return merged.stdout, merged.returncode


def plan_entry(entry, old_label, new_label):
    """The outcome of one manifest entry, computed in memory: (outcome, bytes to write or None)."""
    if not isinstance(entry, dict) or not entry.get("path") or not entry.get("theirs"):
        raise UsageError("each manifest entry is {path, base, theirs}: %r" % (entry,))
    path = entry["path"]
    base_path = entry.get("base")
    if not os.path.isfile(entry["theirs"]):
        raise UsageError("the new template of %s is missing: %s" % (path, entry["theirs"]))
    theirs = _read(entry["theirs"], "the new template", path)
    ours = _read(path, "the project's file", path) if os.path.isfile(path) else None
    if ours is not None and CONFLICT_LINE.search(ours):
        raise UsageError("%s still holds conflict markers: settle them before a new refresh" % path)
    base = _read(base_path, "the base template", path) if base_path is not None and os.path.isfile(base_path) else None
    if ours is None:
        if base_path is None:
            return {"path": path, "status": "two-way", "reason": "no-base-commit", "hunks": _hunks(path, b"", theirs)}, None
        if base is not None:
            return {"path": path, "status": "deleted-locally"}, None
        return {"path": path, "status": "created"}, theirs
    crlf = b"\r\n" in ours
    if base is None:
        if ours == _to_line_endings(theirs, crlf):
            return {"path": path, "status": "unchanged"}, None
        reason = "no-base-commit" if base_path is None else "new-in-kit"
        return {"path": path, "status": "two-way", "reason": reason, "hunks": _hunks(path, ours, theirs)}, None
    result, conflicts = _three_way(ours, _to_line_endings(base, crlf), _to_line_endings(theirs, crlf), old_label, new_label)
    if conflicts > 0:
        return {"path": path, "status": "conflict", "conflicts": conflicts}, result
    if result == ours:
        return {"path": path, "status": "unchanged"}, None
    return {"path": path, "status": "merged"}, result


def merge(manifest_path, old_version, new_version):
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError) as error:
        raise UsageError("cannot read the manifest: %s" % error)
    if not isinstance(entries, list):
        raise UsageError("the manifest is a JSON list of {path, base, theirs}")
    old_label = "kit %s" % (old_version or "recorded version")
    new_label = "kit %s" % (new_version or "new version")
    targets = {}
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        if path:
            target = _target(path)
            if target in targets:
                raise UsageError("%s and %s are the same file (%s)" % (targets[target], path, target))
            targets[target] = path
    planned = [plan_entry(entry, old_label, new_label) for entry in entries]
    for outcome, data in planned:
        if data is None:
            continue
        target = _target(outcome["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".refresh-", dir=os.path.dirname(target))
        with os.fdopen(handle, "wb") as sink:
            sink.write(data)
        if os.path.exists(target):
            shutil.copymode(target, temporary)
        os.replace(temporary, target)
    report = {"merged": [], "unchanged": [], "created": [], "deleted_locally": [], "two_way": [], "conflicts": []}
    keys = {
        "merged": "merged",
        "unchanged": "unchanged",
        "created": "created",
        "deleted-locally": "deleted_locally",
        "two-way": "two_way",
        "conflict": "conflicts",
    }
    for outcome, _ in planned:
        report[keys[outcome["status"]]].append(outcome)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    sha = commands.add_parser("install-sha")
    sha.add_argument("--skill-dir", required=True)
    sha.add_argument("--config-dir")
    marker = commands.add_parser("read-marker")
    marker.add_argument("files", nargs="+")
    fetching = commands.add_parser("fetch-base")
    fetching.add_argument("--sha", required=True)
    fetching.add_argument("--dest", required=True)
    fetching.add_argument("--repository")
    merging = commands.add_parser("merge")
    merging.add_argument("--manifest", required=True)
    merging.add_argument("--old-version")
    merging.add_argument("--new-version")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "install-sha":
            output = install_sha(arguments.skill_dir, arguments.config_dir)
            code = 0
        elif arguments.command == "read-marker":
            found = read_marker(arguments.files)
            output, code = (found, 0) if found else ({"marker": None}, 3)
        elif arguments.command == "fetch-base":
            repository = arguments.repository or os.environ.get("SDD_TOOLBOX_REPOSITORY")
            output = fetch_base(arguments.sha, arguments.dest, repository or DEFAULT_REPOSITORY, bool(repository))
            code = 0 if output["status"] == "fetched" else 3
        else:
            output = merge(arguments.manifest, arguments.old_version, arguments.new_version)
            code = 1 if output["conflicts"] else 4 if output["two_way"] else 0
    except UsageError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(output, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
