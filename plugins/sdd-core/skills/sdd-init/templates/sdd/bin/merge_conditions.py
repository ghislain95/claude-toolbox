#!/usr/bin/env python3
"""merge-conditions — trigger matcher and merge-conditions check of the spec-driven workflow.

Subcommands
  match     Classify a pull request's diff against `.sdd/triggers.yaml` and the approved
            `classification.yaml`, both read from the BASE commit, never from the head. Prints JSON.
            Exit 0 when the verdict is clean, 1 on an unaccounted trigger hit or any error of judgement
            (invalid classification, missing triggers file, change folder and branch disagreeing),
            2 when it cannot judge (unknown commit, git failure). The deploy guard runs it with the
            default branch before the merge (the push event's `before`) as `--base` and the merged
            pull request's head as `--head`.
  check     (CI) Judge open pull requests and post the `merge-conditions` commit status on their head
            commit: aggregate CI gate, `review-harness` / `opsx-verify` statuses and the matcher's
            result. `--pr N --head-sha S` judges S and posts only while S is still the head of #N;
            `--sha S` judges the open pull requests whose head is S; `--all-open` re-judges every open
            pull request into the default branch (after a push to it), posting `pending` first.
  deploy-guard
            (deploy pipeline) Decide whether a commit of the default branch may deploy, recomputing
            the verdict instead of reading the `merge-conditions` status, for it and every
            first-parent commit since the last deployed one: the pull request merged as that commit
            (its content exactly the merge of its parent and the pull request's head), the matcher on
            its diff against that parent, and the required CI runs of its head. Exit 0 = deploy,
            1 = refused, 2 = cannot judge (refused too), 3 = nothing under `--paths` changed (skip,
            no alert), 4 = the adoption merge (refused, expected). One line on stdout says why.
            Run through `.sdd/bin/deploy-guard.sh`, which maps the exit code for each platform.
  validate  Check `triggers.yaml` / `classification.yaml` / `revert.yaml` / `deployment.yaml` files
            against their schema; prints the values a deployment profile marks `unconfirmed`.

The status description is `gates: <gates>[ - <reasons>]; base <sha7>` — `base` is the default-branch
commit the verdict was computed against, always last, so the merge rule can compare it with the
current head of the default branch. `error` and the `pending` posted while re-judging carry no gates.

Never executes code from the pull request head: the head commit is only read as data, through git.
Requirements: Python 3.9+, git, PyYAML; `check` also needs the `gh` CLI with a token; `deploy-guard`
needs a read-only token (`DEPLOY_GUARD_TOKEN`, `GH_TOKEN` or `GITHUB_TOKEN`) and no `gh`.
Schemas: docs/OPENSPEC_GUIDE.md ("Classification and triggers"). Copied verbatim by sdd-init from the
sdd-core plugin (templates/sdd/bin/); a local edit is overwritten by `sdd-init --refresh`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, reported plainly
    sys.stderr.write("merge_conditions.py needs PyYAML: pip install pyyaml\n")
    raise

GATES = ("intent", "irreversible")
TRIGGERS_PATH = ".sdd/triggers.yaml"
CHANGES_DIR = "openspec/changes/"
ARCHIVE_DIR = "openspec/changes/archive/"
WORKFLOWS_DIR = ".github/workflows/"
CLASSIFICATION_FILE = "classification.yaml"
# Added by a revert pull request into the change folder it reverts (`revert/<id>` branch): names the
# merged commit whose diff the pull request must exactly invert.
REVERT_FILE = "revert.yaml"
REVERT_BRANCH = "revert/"
DEPLOYMENT_FILE = "deployment.yaml"
SHA = re.compile(r"^[0-9a-f]{40}$")
# Gate machinery that is always protected, even when triggers.yaml omits it: everything that changes
# what CI or this check does.
DEFAULT_MACHINERY = (
    ".github/**",
    ".sdd/**",
    ".claude/hooks/**",
    ".claude/settings.json",
    "**/.gitattributes",
    ".gitmodules",
    "openspec/config.yaml",
    "**/vercel.json",  # wherever Vercel's root directory puts it: it carries the deploy guard
)
# Trigger name reported when a pull request other than a framing one adds, changes or deletes a
# classification (an identical move into the change's archive folder excepted).
CLASSIFICATION_TRIGGER = "openspec/changes/**/classification.yaml"
# An archived change folder: `openspec/changes/archive/YYYY-MM-DD-<change>/` (or `<change>/`).
ARCHIVE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")
# Branch suffixes of the framing and archive pull requests: `<type>/<id>-framing[-<n>]`, `<type>/<id>-archive`.
# A change delivered in several pull requests names each lot `<type>/<id>/<lot>`: the segment after the id
# is ignored, so it can never be read as another change's id.
BRANCH_SUFFIX = re.compile(r"-(?:framing(?:-\d+)?|archive)$")
# Besides the moved change folder, what an archive pull request may touch.
ARCHIVE_ALLOWED = ("openspec/specs/**", "docs/**", "ROADMAP.md", "BACKLOG.md")
# Labels that replace the gates in the description.
LABEL_ONLY = ("framing", "unclassified", "invalid")
REVIEW_STATUSES = ("review-harness", "opsx-verify")
IN_FLIGHT_LABEL = "in-flight"
STATUS_CONTEXT = "merge-conditions"
SELF_WORKFLOW = "merge-conditions.yml"
DESCRIPTION_MAX = 140
PR_RUN_TYPES = {"opened", "synchronize", "reopened"}
# A workflow run whose jobs were all skipped by their `if:` concludes `skipped` (or `neutral`): it ran.
PASSING_CONCLUSIONS = ("success", "skipped", "neutral")
PAGE_SIZE = 100
MAX_PAGES = 50


# --------------------------------------------------------------------------------------------
# Globs — GitHub Actions path-filter syntax: `*` stops at `/`, `**` crosses it, `?` = zero or one
# of the preceding character, `+` = one or more of it, `[...]` = a character class, a leading `!`
# negates (in ordered filter lists only). The whole path must match.
# --------------------------------------------------------------------------------------------

_GLOB_CACHE: dict = {}


def glob_regex(pattern: str):
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    atoms = []  # [regex, quantifiable]
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            atoms.append(["(?:.*/)?", False])
            i += 3
        elif pattern.startswith("**", i):
            atoms.append([".*", False])
            i += 2
        elif pattern[i] == "*":
            atoms.append(["[^/]*", False])
            i += 1
        elif pattern[i] in "?+" and atoms and atoms[-1][1]:
            atoms[-1][0] += pattern[i]
            atoms[-1][1] = False
            i += 1
        elif pattern[i] == "[" and pattern.find("]", i + 2) != -1:
            end = pattern.find("]", i + 2)
            body = pattern[i + 1:end].replace("\\", "\\\\")
            if body.startswith("!"):
                body = "^" + body[1:]
            atoms.append(["[" + body + "]", True])
            i = end + 1
        else:
            atoms.append([re.escape(pattern[i]), True])
            i += 1
    # DOTALL: `**` crosses every character a file name may hold, a newline included.
    compiled = re.compile("".join(atom[0] for atom in atoms), re.DOTALL)
    _GLOB_CACHE[pattern] = compiled
    return compiled


def glob_match(pattern: str, path: str) -> bool:
    return glob_regex(pattern).fullmatch(path) is not None


def filter_includes(patterns, path: str) -> bool:
    """GitHub's ordered filter: the last pattern that matches decides; `!pattern` excludes."""
    included = False
    for pattern in patterns:
        if pattern.startswith("!"):
            if glob_match(pattern[1:], path):
                included = False
        elif glob_match(pattern, path):
            included = True
    return included


# Control characters (and Unicode line breaks) have no business in a file name: they hide a path from
# a reader and forge lines in logs and alerts. Such a name is an error, and is never printed raw.
CONTROL = re.compile("[\x00-\x1f\x7f\x80-\x9f\u2028\u2029]")


def printable(text: str) -> str:
    """`text` with every control character written as an escape (`\n`, `\x1b`, `\u2028`)."""
    return CONTROL.sub(lambda found: json.dumps(found.group(0))[1:-1], text)


# --------------------------------------------------------------------------------------------
# git — read-only helpers. Every call reads objects; none runs anything from the repository.
# --------------------------------------------------------------------------------------------


class GitError(Exception):
    pass


# Settings of the caller's git configuration that would change what is parsed are neutralised;
# pathspecs are literal (a file name is never read as a pattern).
GIT_OPTIONS = ("-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "core.quotePath=false",
               "--literal-pathspecs")


def git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", repo, *GIT_OPTIONS, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout.decode("utf-8", "replace")


def rev_parse(repo: str, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False).strip()


def show_file(repo: str, ref: str, path: str):
    """Content of `path` at `ref`, or None when absent."""
    result = subprocess.run(
        ["git", "-C", repo, *GIT_OPTIONS, "cat-file", "blob", f"{ref}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


def ls_tree(repo: str, ref: str, prefix: str) -> dict:
    """{path: blob sha} of every file under `prefix` at `ref`."""
    output = git(repo, "ls-tree", "-r", "-z", "--full-tree", ref, "--", prefix)
    files = {}
    for record in output.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind == "blob":
            files[path] = sha
    return files


class Entry:
    __slots__ = ("status", "path", "old_blob", "new_blob", "old_mode", "new_mode")

    def __init__(self, status, path, old_blob, new_blob, old_mode="", new_mode=""):
        self.status, self.path, self.old_blob, self.new_blob = status, path, old_blob, new_blob
        self.old_mode, self.new_mode = old_mode, new_mode


def diff_entries(repo: str, base: str, head: str) -> list:
    """Files touched between `base` and `head`; renames are listed as a deletion plus an addition."""
    output = git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", "--no-ext-diff", base, head)
    tokens = output.split("\0")
    entries = []
    i = 0
    while i + 1 < len(tokens):
        meta = tokens[i]
        if not meta.startswith(":"):
            i += 1
            continue
        old_mode, new_mode, old_blob, new_blob, status = meta[1:].split()
        entries.append(Entry(status[0], tokens[i + 1], old_blob, new_blob, old_mode, new_mode))
        i += 2
    return entries


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(repo: str, base: str, head: str, path: str) -> list:
    """[(line number in head, text)] of the lines ADDED to `path` between `base` and `head`.

    One file per call, named by the `-z` list of `diff_entries`, so no header is ever parsed for a
    path. `--text` reads every file as text, whatever `.gitattributes` says (`-diff`, `binary`).
    """
    output = git(
        repo, "diff", "-U0", "--text", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
        "--src-prefix=a/", "--dst-prefix=b/", base, head, "--", path,
    )
    lines = []
    in_hunk = False
    line_number = 0
    for line in output.split("\n"):
        if line.startswith("@@"):
            found = _HUNK.match(line)
            in_hunk = found is not None
            line_number = int(found.group(1)) if found else 0
            continue
        if in_hunk and line.startswith("+"):
            lines.append((line_number, line[1:]))
            line_number += 1
    return lines


# --------------------------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------------------------


def _string_list(value, where: str, errors: list) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        errors.append(f"{where}: expected a list of non-empty strings")
        return []
    return list(value)


def load_triggers(text):
    """Parse triggers.yaml. Returns (triggers, errors); the gate machinery always holds the defaults."""
    errors: list = []
    triggers = {gate: {"paths": [], "content": []} for gate in GATES}
    machinery = list(DEFAULT_MACHINERY)
    triggers["gate_machinery"] = machinery
    if text is None:
        return triggers, errors
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return triggers, [f"triggers.yaml: not valid YAML ({str(exc).splitlines()[0]})"]
    if data is None:
        return triggers, errors
    if not isinstance(data, dict):
        return triggers, ["triggers.yaml: expected a mapping at the top level"]
    for key in sorted(set(data) - {"intent", "irreversible", "gate_machinery"}, key=str):
        errors.append(f"triggers.yaml: unknown key {key!r}")
    for gate in GATES:
        section = data.get(gate)
        if section is None:
            continue
        if not isinstance(section, dict):
            errors.append(f"triggers.yaml: {gate}: expected a mapping with paths and content")
            continue
        for key in sorted(set(section) - {"paths", "content"}, key=str):
            errors.append(f"triggers.yaml: {gate}: unknown key {key!r}")
        triggers[gate]["paths"] = _string_list(section.get("paths"), f"triggers.yaml: {gate}.paths", errors)
        content = section.get("content")
        if content is None:
            continue
        if not isinstance(content, list):
            errors.append(f"triggers.yaml: {gate}.content: expected a list")
            continue
        for index, item in enumerate(content):
            where = f"triggers.yaml: {gate}.content[{index}]"
            if not isinstance(item, dict) or not isinstance(item.get("pattern"), str) or not item["pattern"]:
                errors.append(f"{where}: expected a mapping with a non-empty pattern")
                continue
            for key in sorted(set(item) - {"paths", "pattern"}, key=str):
                errors.append(f"{where}: unknown key {key!r}")
            try:
                regex = re.compile(item["pattern"])
            except re.error as exc:
                errors.append(f"{where}.pattern: invalid regex ({exc})")
                continue
            triggers[gate]["content"].append({
                "paths": _string_list(item.get("paths"), f"{where}.paths", errors),
                "pattern": item["pattern"],
                "regex": regex,
            })
    section = data.get("gate_machinery")
    if section is not None:
        if not isinstance(section, dict):
            errors.append("triggers.yaml: gate_machinery: expected a mapping with paths")
        else:
            for key in sorted(set(section) - {"paths"}, key=str):
                errors.append(f"triggers.yaml: gate_machinery: unknown key {key!r}")
            for glob in _string_list(section.get("paths"), "triggers.yaml: gate_machinery.paths", errors):
                if glob not in machinery:
                    machinery.append(glob)
    return triggers, errors


def load_classification(text, change=None):
    """Parse classification.yaml. Returns (classification or None, errors)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [f"classification.yaml: not valid YAML ({str(exc).splitlines()[0]})"]
    if not isinstance(data, dict):
        return None, ["classification.yaml: expected a mapping at the top level"]
    errors: list = []
    for key in sorted(set(data) - {"change", "intent", "irreversible"}, key=str):
        errors.append(f"classification.yaml: unknown key {key!r}")
    if not isinstance(data.get("change"), str) or not data.get("change"):
        errors.append("classification.yaml: change: expected the change id")
    elif change is not None and data["change"] != change:
        errors.append(f"classification.yaml: change is {data['change']!r}, the folder is {change!r}")
    classification = {"change": data.get("change")}
    for gate in GATES:
        section = data.get(gate)
        where = f"classification.yaml: {gate}"
        if not isinstance(section, dict):
            errors.append(f"{where}: expected a mapping with open and evidence")
            continue
        for key in sorted(set(section) - {"open", "evidence", "waived"}, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        if not isinstance(section.get("open"), bool):
            errors.append(f"{where}.open: expected true or false")
        if not isinstance(section.get("evidence"), str) or not section.get("evidence", "").strip():
            errors.append(f"{where}.evidence: expected the reason for the answer")
        waived = []
        raw_waived = section.get("waived")
        if raw_waived is not None and not isinstance(raw_waived, list):
            errors.append(f"{where}.waived: expected a list")
            raw_waived = []
        for index, item in enumerate(raw_waived or []):
            if (not isinstance(item, dict) or not isinstance(item.get("trigger"), str) or not item["trigger"]
                    or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
                errors.append(f"{where}.waived[{index}]: expected a trigger and a reason")
                continue
            for key in sorted(set(item) - {"trigger", "reason"}, key=str):
                errors.append(f"{where}.waived[{index}]: unknown key {key!r}")
            waived.append({"trigger": item["trigger"], "reason": item["reason"]})
        classification[gate] = {"open": section.get("open") is True, "waived": waived}
    if errors:
        return None, errors
    return classification, errors


def _yaml_mapping(text, name: str):
    """(mapping or None, errors) of a YAML document expected to be a mapping."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [f"{name}: not valid YAML ({str(exc).splitlines()[0]})"]
    if not isinstance(data, dict):
        return None, [f"{name}: expected a mapping at the top level"]
    return data, []


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_revert(text, change=None):
    """Parse revert.yaml. Returns (revert or None, errors)."""
    data, errors = _yaml_mapping(text, REVERT_FILE)
    if data is None:
        return None, errors
    for key in sorted(set(data) - {"revert_of", "merge_commits", "reason"}, key=str):
        errors.append(f"{REVERT_FILE}: unknown key {key!r}")
    if not _text(data.get("revert_of")):
        errors.append(f"{REVERT_FILE}: revert_of: expected the id of the reverted change")
    elif change is not None and data["revert_of"] != change:
        errors.append(f"{REVERT_FILE}: revert_of is {data['revert_of']!r}, the folder is {change!r}")
    commits = data.get("merge_commits")
    if (not isinstance(commits, list) or not commits
            or not all(isinstance(item, str) and SHA.match(item) for item in commits)):
        errors.append(f"{REVERT_FILE}: merge_commits: expected the full shas of the reverted merges, one per lot")
    elif len(set(commits)) != len(commits):
        errors.append(f"{REVERT_FILE}: merge_commits: a merge is listed twice")
    if not _text(data.get("reason")):
        errors.append(f"{REVERT_FILE}: reason: expected the diagnosis of the failed verification")
    if errors:
        return None, errors
    return {"revert_of": data["revert_of"], "merge_commits": list(commits), "reason": data["reason"]}, []


def _globs(value, where: str, errors: list) -> list:
    if not isinstance(value, list) or not value:
        errors.append(f"{where}: expected a non-empty list of globs")
        return []
    return _string_list(value, where, errors)


def _unconfirmed(item, where: str, errors: list, found: list):
    value = item.get("unconfirmed", False)
    if not isinstance(value, bool):
        errors.append(f"{where}.unconfirmed: expected true or false")
    elif value:
        found.append(where)


def _command(item, where: str, errors: list, found: list, keys=("command", "expect", "unconfirmed")):
    """A command with an optional `expect` regex, as a probe or a rollback has."""
    if not isinstance(item, dict):
        errors.append(f"{where}: expected a mapping with a command")
        return
    for key in sorted(set(item) - set(keys), key=str):
        errors.append(f"{where}: unknown key {key!r}")
    if not _text(item.get("command")):
        errors.append(f"{where}.command: expected the command, as run")
    if "expect" in item:
        if not _text(item["expect"]):
            errors.append(f"{where}.expect: expected a regex the output must match")
        else:
            try:
                re.compile(item["expect"])
            except re.error as exc:
                errors.append(f"{where}.expect: invalid regex ({exc})")
    _unconfirmed(item, where, errors, found)


def load_deployment(text):
    """Parse deployment.yaml. Returns (profile or None, errors, unconfirmed value paths)."""
    name = DEPLOYMENT_FILE
    data, errors = _yaml_mapping(text, name)
    found: list = []
    if data is None:
        return None, errors, found
    for key in sorted(set(data) - {"deploys_nothing", "targets", "scheduled_jobs"}, key=str):
        errors.append(f"{name}: unknown key {key!r}")
    nothing = data.get("deploys_nothing", False)
    if not isinstance(nothing, bool):
        errors.append(f"{name}: deploys_nothing: expected true or false")
    targets = data.get("targets")
    if targets is None:
        targets = []
    if not isinstance(targets, list):
        errors.append(f"{name}: targets: expected a list")
        targets = []
    if nothing is True and targets:
        errors.append(f"{name}: deploys_nothing is true, so no target (and no rollback) can be listed")
    if nothing is False and not targets:
        errors.append(f"{name}: no target: list what merging deploys, or set deploys_nothing: true")
    names = set()
    for index, target in enumerate(targets):
        where = f"{name}: targets[{index}]"
        if not isinstance(target, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        if _text(target.get("name")):
            where = f"{name}: targets[{target['name']}]"
            if target["name"] in names:
                errors.append(f"{where}: duplicate target name")
            names.add(target["name"])
        else:
            errors.append(f"{where}.name: expected the target's name")
        for key in sorted(set(target) - {"name", "platform", "trigger", "workflow", "rollback", "probes",
                                         "unconfirmed", "note"}, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        if not _text(target.get("platform")):
            errors.append(f"{where}.platform: expected the platform (cloud-run, vercel, …)")
        if "workflow" in target and not _text(target["workflow"]):
            errors.append(f"{where}.workflow: expected the path of the workflow that deploys it")
        if "note" in target and not _text(target["note"]):
            errors.append(f"{where}.note: expected text")
        trigger = target.get("trigger")
        if not isinstance(trigger, dict) or len(trigger) != 1 or not ({"paths", "every_push"} & set(trigger)):
            errors.append(f"{where}.trigger: expected either `paths: [globs]` or `every_push: true`")
        elif "paths" in trigger:
            _globs(trigger["paths"], f"{where}.trigger.paths", errors)
        elif trigger["every_push"] is not True:
            errors.append(f"{where}.trigger.every_push: expected true")
        if "rollback" not in target:
            errors.append(f"{where}.rollback: expected the platform command that restores the previous deployment")
        else:
            _command(target["rollback"], f"{where}.rollback", errors, found, ("command", "note", "unconfirmed"))
            if isinstance(target["rollback"], dict) and "note" in target["rollback"] \
                    and not _text(target["rollback"]["note"]):
                errors.append(f"{where}.rollback.note: expected text")
        probes = target.get("probes")
        if not isinstance(probes, list) or not probes:
            errors.append(f"{where}.probes: expected at least one probe (command, optional expect)")
        else:
            for number, probe in enumerate(probes):
                _command(probe, f"{where}.probes[{number}]", errors, found)
        _unconfirmed(target, where, errors, found)
    jobs = data.get("scheduled_jobs")
    if jobs is None:
        jobs = []
    if not isinstance(jobs, list):
        errors.append(f"{name}: scheduled_jobs: expected a list")
        jobs = []
    for index, job in enumerate(jobs):
        where = f"{name}: scheduled_jobs[{index}]"
        if not isinstance(job, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        if _text(job.get("name")):
            where = f"{name}: scheduled_jobs[{job['name']}]"
        else:
            errors.append(f"{where}.name: expected the job's name")
        for key in sorted(set(job) - {"name", "schedule", "paths", "runs", "probe", "unconfirmed"}, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        if not _text(job.get("schedule")):
            errors.append(f"{where}.schedule: expected the schedule (cron, with its time zone)")
        _globs(job.get("paths"), f"{where}.paths", errors)
        if "runs" in job and not _text(job["runs"]):
            errors.append(f"{where}.runs: expected what runs the job")
        if "probe" in job:
            _command(job["probe"], f"{where}.probe", errors, found)
        _unconfirmed(job, where, errors, found)
    if errors:
        return None, errors, found
    return data, errors, [item[len(name) + 2:] for item in found]


# --------------------------------------------------------------------------------------------
# Matcher
# --------------------------------------------------------------------------------------------


def _change_folder(path: str):
    """`<id>` when `path` is inside `openspec/changes/<id>/` (archive excluded)."""
    if not path.startswith(CHANGES_DIR):
        return None
    parts = path[len(CHANGES_DIR):].split("/")
    if len(parts) < 2 or parts[0] == "archive":
        return None
    return parts[0]


def _archive_folder(path: str) -> str:
    return path[len(ARCHIVE_DIR):].split("/", 1)[0]


def _archive_folder_of(path: str, change: str) -> bool:
    """Whether `path` is inside `change`'s archive folder: `YYYY-MM-DD-<change>/` or `<change>/`."""
    folder = _archive_folder(path)
    dated = ARCHIVE_FOLDER.match(folder)
    return folder == change or (dated is not None and dated.group(1) == change)


def _branch_candidates(branch):
    """Change ids a branch `<type>/<id>[-framing[-<n>]|-archive][/<lot>]` may belong to."""
    if not branch:
        return []
    parts = branch.split("/")
    name = parts[1] if len(parts) > 1 else parts[0]
    stripped = BRANCH_SUFFIX.sub("", name)
    return [name, stripped] if stripped and stripped != name else [name]


def find_change(files, branch):
    """(change, error) of a pull request: the one change folder it touches, named by its branch too.

    A branch name alone never selects a classification: a pull request that touches no change folder
    is unclassified. Several folders, or a folder the branch does not name, is an error.
    """
    folders = sorted({folder for folder in (_change_folder(path) for path in files) if folder})
    if not folders:
        return None, None
    if len(folders) > 1:
        return None, f"several change folders touched ({', '.join(folders)})"
    if folders[0] not in _branch_candidates(branch):
        return None, f"change folder {folders[0]} does not match the branch {branch or '(none)'}"
    return folders[0], None


def is_framing(change: str, entries) -> bool:
    prefix = f"{CHANGES_DIR}{change}/"
    paths = {entry.path for entry in entries}
    return (
        bool(entries)
        and all(entry.path.startswith(prefix) and entry.status in "AM" for entry in entries)
        and f"{prefix}{CLASSIFICATION_FILE}" in paths
    )


def is_archive(change: str, entries) -> bool:
    """Moves `openspec/changes/<change>/` into ONE archive folder of that change, nothing else but
    `ARCHIVE_ALLOWED`."""
    prefix = f"{CHANGES_DIR}{change}/"
    moved_out = False
    folders = set()
    for entry in entries:
        if entry.path.startswith(prefix):
            if entry.status != "D":
                return False
            moved_out = True
        elif entry.path.startswith(ARCHIVE_DIR):
            if entry.status == "D" or not _archive_folder_of(entry.path, change):
                return False
            folders.add(_archive_folder(entry.path))
        elif not any(glob_match(glob, entry.path) for glob in ARCHIVE_ALLOWED):
            return False
    return moved_out and len(folders) == 1


def classification_edits(repo: str, base: str, entries) -> list:
    """Classifications the pull request adds, changes or deletes, whether or not on the base ref.

    Judged by what the merge would do to the base ref: a file whose head content equals the base
    content is no edit (a branch that already carries the approved version), nor is a deletion absent
    from the base ref. An approved classification moved identically into its change's archive folder
    (archive pull request) is no edit either — both sides of the move.
    """
    on_base = {path: blob for path, blob in ls_tree(repo, base, CHANGES_DIR).items()
               if path.endswith("/" + CLASSIFICATION_FILE)}
    touched = [entry for entry in entries if glob_match(CLASSIFICATION_TRIGGER, entry.path)]
    added = {entry.path: entry.new_blob for entry in touched if entry.status != "D"}
    moved = set()
    for entry in touched:
        change = _change_folder(entry.path)
        blob = on_base.get(entry.path)
        if entry.status != "D" or change is None or blob is None:
            continue
        for path, new_blob in added.items():
            if (new_blob == blob and path.startswith(ARCHIVE_DIR) and _archive_folder_of(path, change)
                    and path == f"{ARCHIVE_DIR}{_archive_folder(path)}/{CLASSIFICATION_FILE}"):
                moved.update((entry.path, path))
                break
    edits = []
    for entry in touched:
        head_blob = None if entry.status == "D" else entry.new_blob
        if entry.path in moved or on_base.get(entry.path) == head_blob:
            continue
        edits.append(entry.path)
    return sorted(edits)


def _transitions(entries, inverse=False) -> set:
    """{(path, old mode, old blob, new mode, new blob)}; `inverse` swaps old and new."""
    if inverse:
        return {(entry.path, entry.new_mode, entry.new_blob, entry.old_mode, entry.old_blob) for entry in entries}
    return {(entry.path, entry.old_mode, entry.old_blob, entry.new_mode, entry.new_blob) for entry in entries}


class PullLookup:
    """The merged pull requests of a commit, through the API — the check and the deploy guard have it;
    the `match` command alone has not (then a revert's merges are judged on git facts only)."""

    def __init__(self, api, slug: str, default_branch: str):
        self.api, self.slug, self.default_branch = api, slug, default_branch

    def merged_as(self, sha: str) -> list:
        return [pull for pull in get_pages(self.api, f"repos/{self.slug}/commits/{sha}/pulls")
                if pull.get("merged_at") and pull.get("merge_commit_sha") == sha
                and (pull.get("base") or {}).get("ref") == self.default_branch]


def _change_of_branch(branch, change: str) -> bool:
    """Whether a pull request branch is one of `change`'s own (`<type>/<id>` or `<type>/<id>/<lot>`),
    not its framing or archive branch."""
    if not branch or "/" not in branch:
        return False
    return branch.split("/")[1] == change


def revert_errors(repo: str, base_sha: str, change: str, entries, branch, text, lookup=None):
    """(errors, in flight) of a pull request adding `<change>/revert.yaml`.

    A revert pull request comes from `revert/<change>` and lists in `revert.yaml` the merges it
    reverts: commits of the base ref's first-parent line that changed `openspec/changes/<change>/`,
    the newest of those among them; with `lookup`, each is the merge commit of a merged pull request
    from one of the change's branches. Its diff, `revert.yaml` aside, is exactly the inverse of those
    merges taken together: every file they touched goes back to the blob and mode it had before the
    first of them, nothing else moves. `in flight`: one of those pull requests carries the label.
    """
    revert, errors = load_revert(text or "", change)
    if branch != f"{REVERT_BRANCH}{change}":
        errors.append(f"a revert of {change} comes from the branch {REVERT_BRANCH}{change}, not {branch or '(none)'}")
    if revert is None:
        return errors, False
    folder = f"{CHANGES_DIR}{change}/"
    line = git(repo, "rev-list", "--first-parent", base_sha).split()
    order = {sha: index for index, sha in enumerate(reversed(line))}
    merges = []
    for listed in revert["merge_commits"]:
        short = listed[:7]
        if listed not in order:
            errors.append(f"revert of {change}: {short} is not a merge on the base ref's first-parent line")
            continue
        original = diff_entries(repo, f"{listed}^1", listed)
        if not any(entry.path.startswith(folder) for entry in original):
            errors.append(f"revert of {change}: {short} did not change {folder}")
            continue
        merges.append((order[listed], listed, original))
    newest = git(repo, "rev-list", "--first-parent", "-n", "1", base_sha, "--", folder).strip()
    if newest and newest not in revert["merge_commits"]:
        errors.append(f"revert of {change}: the newest merge of the change, {newest[:7]}, is not reverted")
    in_flight = False
    if lookup is not None:
        for _, listed, _ in merges:
            pulls = [pull for pull in lookup.merged_as(listed)
                     if _change_of_branch((pull.get("head") or {}).get("ref"), change)]
            if not pulls:
                errors.append(f"revert of {change}: {listed[:7]} is not the merge of a pull request of the change")
            in_flight = in_flight or any(label.get("name") == IN_FLIGHT_LABEL
                                         for pull in pulls for label in pull.get("labels") or [])
    if errors:
        return errors, in_flight
    before, after = {}, {}
    for _, _, original in sorted(merges, key=lambda item: item[0]):
        for entry in original:
            before.setdefault(entry.path, (entry.old_mode, entry.old_blob))
            after[entry.path] = (entry.new_mode, entry.new_blob)
    expected = {(path, *after[path], *before[path]) for path in after if after[path] != before[path]}
    own = f"{folder}{REVERT_FILE}"
    actual = _transitions(entry for entry in entries if entry.path != own)
    differing = sorted({printable(item[0]) for item in expected ^ actual})
    if differing:
        shown = ", ".join(differing[:3]) + (f" (+{len(differing) - 3})" if len(differing) > 3 else "")
        names = "+".join(sha[:7] for sha in revert["merge_commits"])
        errors.append(f"not the exact inverse of {names}: {shown}")
    return errors, in_flight


def revert_gates(classification, hits, in_flight: bool) -> list:
    """An exact revert opens the irreversible gate when the reverted change had it open (fixed forward:
    the owner decides) or the revert touches gate machinery (always gated), and the intent gate when
    the reverted change had it open and is not the change in flight — undoing behaviour the owner
    approved and that passed its verification is the owner's call. Otherwise no gate."""
    gates = []
    if classification["intent"]["open"] and not in_flight:
        gates.append("intent")
    if classification["irreversible"]["open"] or any(hit.get("machinery") for hit in hits):
        gates.append("irreversible")
    return gates


def needs_lines(triggers, path: str) -> bool:
    """Whether a content trigger reads `path`."""
    return any(not content["paths"] or any(glob_match(glob, path) for glob in content["paths"])
               for gate in GATES for content in triggers[gate]["content"])


def compute_hits(triggers, files, lines_by_file, edits) -> list:
    hits = []
    for gate in GATES:
        for glob in triggers[gate]["paths"]:
            for path in files:
                if glob_match(glob, path):
                    hits.append({"gate": gate, "trigger": glob, "file": path})
        for content in triggers[gate]["content"]:
            for path in sorted(lines_by_file):
                if content["paths"] and not any(glob_match(glob, path) for glob in content["paths"]):
                    continue
                for number, text in lines_by_file[path]:
                    if content["regex"].search(text):
                        hits.append({"gate": gate, "trigger": content["pattern"], "file": path, "line": number})
                        break
    for glob in triggers["gate_machinery"]:
        for path in files:
            if glob_match(glob, path):
                hits.append({"gate": "irreversible", "trigger": glob, "file": path, "machinery": True})
    for path in edits:
        hits.append({"gate": "irreversible", "trigger": CLASSIFICATION_TRIGGER, "file": path, "machinery": True})
    return hits


def resolve_gates(kind: str, classification, hits):
    """(gates, unaccounted, waived) of a classified pull request."""
    declared = {gate for gate in GATES if classification[gate]["open"]}
    gates = set(declared) if kind == "change" else set()
    unaccounted, waived = [], []
    for hit in hits:
        gate = hit["gate"]
        if not hit.get("machinery"):
            reason = next((item["reason"] for item in classification[gate]["waived"]
                           if item["trigger"] == hit["trigger"]), None)
            if reason is not None:
                waived.append(dict(hit, reason=reason))
                continue
        gates.add(gate)
        if gate not in declared:
            unaccounted.append(hit)
    return [gate for gate in GATES if gate in gates], unaccounted, waived


def gates_label(gates) -> str:
    if len(gates) == 1 and gates[0] in LABEL_ONLY:
        return f"gates: {gates[0]}"
    return "gates: " + ("+".join(gates) if gates else "none")


def unaccounted_reason(unaccounted) -> str:
    seen = []
    for hit in unaccounted:
        item = f"{hit['gate']} {printable(hit['file'])}" + (f":{hit['line']}" if "line" in hit else "")
        if item not in seen:
            seen.append(item)
    return "unaccounted " + ", ".join(seen)


def match(repo: str, base: str, head: str, branch=None, lookup=None) -> dict:
    """The verdict on a pull request's diff. `lookup` (a PullLookup) lets a revert be tied to the
    pull requests it reverts."""
    base_sha = rev_parse(repo, base)
    head_sha = rev_parse(repo, head)
    if not base_sha or not head_sha:
        raise GitError(f"unknown commit: {base if not base_sha else head}")
    merge_base = git(repo, "merge-base", base_sha, head_sha).strip()
    triggers_text = show_file(repo, base_sha, TRIGGERS_PATH)
    triggers, errors = load_triggers(triggers_text)
    if triggers_text is None:
        errors.append(f"{TRIGGERS_PATH} missing on the base ref")
    entries = diff_entries(repo, merge_base, head_sha)
    files = sorted({entry.path for entry in entries})
    errors.extend(f"file name with a control character: {printable(path)}" for path in files if CONTROL.search(path))
    change, change_error = find_change(files, branch)
    if change_error:
        errors.append(change_error)
    framing = change is not None and is_framing(change, entries)
    revert_path = f"{CHANGES_DIR}{change}/{REVERT_FILE}"
    revert = (not framing and change is not None
              and any(entry.path == revert_path and entry.status == "A" for entry in entries))
    edits = [] if framing else classification_edits(repo, base_sha, entries)
    lines_by_file = {entry.path: added_lines(repo, merge_base, head_sha, entry.path) for entry in entries
                     if entry.status != "D" and needs_lines(triggers, entry.path)}
    hits = compute_hits(triggers, files, lines_by_file, edits)

    classification = None
    if change:
        text = show_file(repo, base_sha, f"{CHANGES_DIR}{change}/{CLASSIFICATION_FILE}")
        if text is not None:
            classification, classification_errors = load_classification(text, change)
            errors.extend(f"approved {message}" for message in classification_errors)
            if classification is None:
                classification = False  # present on the base ref but invalid

    gates, unaccounted, waived = [], [], []
    if framing:
        kind = "framing"
        proposed = show_file(repo, head_sha, f"{CHANGES_DIR}{change}/{CLASSIFICATION_FILE}")
        _, proposed_errors = load_classification(proposed or "", change)
        errors = [message for message in errors if not message.startswith("approved ")]
        errors.extend(f"proposed {message}" for message in proposed_errors)
        gates = ["framing"]
    elif revert:
        kind = "revert"
        problems, in_flight = revert_errors(repo, base_sha, change, entries, branch,
                                            show_file(repo, head_sha, revert_path), lookup)
        errors.extend(problems)
        if classification is None:
            errors.append(f"revert of {change}: no approved classification on the base ref")
            gates = ["invalid"]
        elif classification is False:
            gates = ["invalid"]
        else:
            gates = revert_gates(classification, hits, in_flight)
    elif classification is False:
        kind = "change"
        gates = ["invalid"]
    elif classification:
        kind = "archive" if is_archive(change, entries) else "change"
        gates, unaccounted, waived = resolve_gates(kind, classification, hits)
    else:
        kind = "unclassified"
        gates = ["unclassified"]

    label = gates_label(gates)
    reasons = list(errors)
    if unaccounted:
        reasons.append(unaccounted_reason(unaccounted))
    return {
        "kind": kind,
        "change": change,
        "base": base_sha,
        "head": head_sha,
        "merge_base": merge_base,
        "gates": gates,
        "hits": hits,
        "unaccounted": unaccounted,
        "waived": waived,
        "errors": errors,
        "files": files,
        "label": label,
        "description": label + (" - " + "; ".join(reasons) if reasons else ""),
    }


# --------------------------------------------------------------------------------------------
# Check — aggregate CI gate, review statuses, commit status
# --------------------------------------------------------------------------------------------


def _as_list(value):
    if value is None:
        return None
    return [value] if isinstance(value, str) else [str(item) for item in value]


def workflow_events(document) -> dict:
    if not isinstance(document, dict):
        return {}
    events = document.get("on", document.get(True))  # PyYAML reads a bare `on` key as True
    if isinstance(events, str):
        return {events: None}
    if isinstance(events, list):
        return {event: None for event in events if isinstance(event, str)}
    return events if isinstance(events, dict) else {}


def workflow_required(document, files, base_branch: str) -> bool:
    """Whether a workflow runs on a pull request into `base_branch` touching `files`."""
    events = workflow_events(document)
    if "pull_request" not in events:
        return False
    config = events["pull_request"] if isinstance(events["pull_request"], dict) else {}
    types = _as_list(config.get("types"))
    if types is not None and not PR_RUN_TYPES & set(types):
        return False
    branches = _as_list(config.get("branches"))
    if branches is not None and not filter_includes(branches, base_branch):
        return False
    ignored_branches = _as_list(config.get("branches-ignore"))
    if ignored_branches is not None and filter_includes(ignored_branches, base_branch):
        return False
    paths = _as_list(config.get("paths"))
    if paths is not None:
        return any(filter_includes(paths, path) for path in files)
    ignored = _as_list(config.get("paths-ignore"))
    if ignored is not None:
        return any(not filter_includes(ignored, path) for path in files)
    return True


def is_workflow(path: str) -> bool:
    """GitHub runs the YAML files directly in `.github/workflows/`, not those of its subfolders."""
    return (path.startswith(WORKFLOWS_DIR) and path.count("/") == 2
            and path.endswith((".yml", ".yaml")))


def _load_workflow(repo: str, ref: str, path: str):
    """The workflow document, or None when it is not valid YAML."""
    try:
        return yaml.safe_load(show_file(repo, ref, path) or "")
    except yaml.YAMLError:
        return None


def required_workflows(repo: str, base: str, files, base_branch: str) -> list:
    """Workflows of the base ref that a pull request with these files must have run, by path."""
    required = []
    for path in sorted(ls_tree(repo, base, WORKFLOWS_DIR)):
        if not is_workflow(path) or path.rsplit("/", 1)[1] == SELF_WORKFLOW:
            continue
        document = _load_workflow(repo, base, path)
        if document is None or workflow_required(document, files, base_branch):
            required.append(path)  # unreadable: GitHub cannot run it either, so it never goes green
    return required


def _workflow_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def workflow_problems(repo: str, result: dict, required, base_branch: str) -> dict:
    """{workflow path: reason} of the pull request's own workflow edits that its runs cannot reflect.

    A required workflow the pull request deletes (a rename is a deletion plus an addition) or edits so
    that it no longer runs on it would wait forever for a run; a workflow it adds runs although nothing
    requires it, and can post any status. Each is a reason of its own (such pull requests are gate
    machinery: the owner merges them).
    """
    on_base = {path for path in ls_tree(repo, result["base"], WORKFLOWS_DIR) if is_workflow(path)}
    problems = {}
    for entry in diff_entries(repo, result["merge_base"], result["head"]):
        path = entry.path
        if not is_workflow(path):
            continue
        name = _workflow_name(path)
        if path in required:
            if entry.status == "D":
                problems[path] = f"{name} deleted by the pull request"
            elif not workflow_required(_load_workflow(repo, result["head"], path), result["files"], base_branch):
                problems[path] = f"{name} no longer runs on the pull request"
        elif entry.status != "D" and path not in on_base:
            problems[path] = f"{name} added by the pull request"
    return problems


def truncate(text: str, limit: int = DESCRIPTION_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def describe(label: str, reasons, base_sha: str) -> str:
    """`<label>; base <sha7>`, or `<label> - <reasons>; base <sha7>`, cut inside the reasons so that the
    base always survives."""
    suffix = f"base {base_sha[:7]}"
    reasons = list(reasons)
    if not reasons:
        return f"{label}; {suffix}"
    text = label + " - " + "".join(f"{reason}; " for reason in reasons)
    if len(text) + len(suffix) > DESCRIPTION_MAX:
        text = text[: DESCRIPTION_MAX - len(suffix) - 5] + "...; "
    return text + suffix


def run_verdicts(required, runs, head_sha: str, skip=()):
    """(failures, waiting) of the required workflows: the latest `pull_request` run of each on
    `head_sha` must have completed with success. Workflows in `skip` are not looked at."""
    failures, waiting = [], []
    latest = {}
    for run in runs:
        if run.get("event") != "pull_request" or run.get("head_sha") != head_sha:
            continue
        path = run.get("path", "").split("@", 1)[0]
        if path not in latest or run.get("id", 0) > latest[path].get("id", 0):
            latest[path] = run
    for path in required:
        if path in skip:
            continue
        name = _workflow_name(path)
        run = latest.get(path)
        if run is None:
            waiting.append(f"no run of {name}")
        elif run.get("status") != "completed":
            waiting.append(f"{name} running")
        elif run.get("conclusion") not in PASSING_CONCLUSIONS:
            failures.append(f"{name} {run.get('conclusion')}")
    return failures, waiting


def evaluate(result: dict, required, runs, statuses, problems=None):
    """(state, description) of `merge-conditions` for one head commit."""
    problems = problems or {}
    failures, waiting = list(result["errors"]), []
    if result["unaccounted"]:
        failures.append(unaccounted_reason(result["unaccounted"]))
    run_failures, waiting = run_verdicts(required, runs, result["head"], problems)
    failures.extend(run_failures)
    failures.extend(problems[path] for path in sorted(problems))
    if result["kind"] == "change":
        for context in REVIEW_STATUSES:
            state = statuses.get(context)
            if state is None:
                waiting.append(f"no {context} status")
            elif state == "pending":
                waiting.append(f"{context} pending")
            elif state != "success":
                failures.append(f"{context} {state}")
    if failures:
        state, reasons = "failure", failures + waiting
    elif waiting:
        state, reasons = "pending", waiting
    else:
        state, reasons = "success", []
    return state, describe(result["label"], reasons, result["base"])


class GitHub:
    """`gh api` client; tests replace it with a stub exposing the same two methods."""

    def get(self, path: str):
        result = subprocess.run(["gh", "api", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(f"gh api {path}: {result.stderr.decode('utf-8', 'replace').strip()}")
        return json.loads(result.stdout or b"null")

    def post_status(self, repo: str, sha: str, state: str, description: str, target_url=None):
        command = ["gh", "api", "--method", "POST", f"repos/{repo}/statuses/{sha}",
                   "-f", f"state={state}", "-f", f"context={STATUS_CONTEXT}", "-f", f"description={description}"]
        if target_url:
            command += ["-f", f"target_url={target_url}"]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def get_pages(api, path: str, key=None) -> list:
    """Every item of a paginated list; `key` names the array when the response is an object."""
    items = []
    separator = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        data = api.get(f"{path}{separator}per_page={PAGE_SIZE}&page={page}")
        batch = (data or {}).get(key) or [] if key else data or []
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
    raise RuntimeError(f"{path}: more than {MAX_PAGES} pages")


def fetch_default_branch(repo: str, default_branch: str):
    git(repo, "fetch", "--no-tags", "--quiet", "origin",
        f"+refs/heads/{default_branch}:refs/remotes/origin/{default_branch}")


def fetch_pull_request(repo: str, default_branch: str, number: int, head_sha: str):
    """Fetch the base branch and the pull request head as data (no checkout, nothing executed)."""
    git(repo, "fetch", "--no-tags", "--quiet", "origin",
        f"+refs/heads/{default_branch}:refs/remotes/origin/{default_branch}",
        f"+refs/pull/{number}/head:refs/remotes/origin/pull/{number}")
    if not git(repo, "cat-file", "-t", head_sha, check=False).strip() == "commit":
        git(repo, "fetch", "--no-tags", "--quiet", "origin", head_sha)


def _judgeable(pull, default_branch: str, log) -> bool:
    if pull.get("state") != "open":
        log(f"#{pull['number']}: not open, skipped")
        return False
    if pull["base"]["ref"] != default_branch:
        log(f"#{pull['number']}: targets {pull['base']['ref']}, not {default_branch}; skipped")
        return False
    return True


def _still_head(api, slug: str, number: int, head_sha: str, default_branch: str) -> bool:
    """Whether `head_sha` is still the head of the open pull request #number into the default branch."""
    pull = api.get(f"repos/{slug}/pulls/{number}") or {}
    return (pull.get("state") == "open" and pull.get("head", {}).get("sha") == head_sha
            and pull.get("base", {}).get("ref") == default_branch)


def check(api, repo: str, slug: str, default_branch: str, pr=None, sha=None, all_open: bool = False,
          base_ref=None, fetch: bool = True, post: bool = True, target_url=None, log=None) -> list:
    """Judge open pull requests and post their status.

    `pr` (with `sha`, the head the event named): that pull request, skipped when its head moved;
    `sha` alone: the open pull requests whose head is `sha`; `all_open`: every open pull request into
    the default branch, each first set to `pending`. A status is posted only if the judged commit is
    still the pull request's head at that moment.
    """
    log = log or (lambda message: print(message, file=sys.stderr))
    base_ref = base_ref or f"origin/{default_branch}"
    if all_open:
        if fetch:
            fetch_default_branch(repo, default_branch)
        pulls = [pull for pull in get_pages(api, f"repos/{slug}/pulls?state=open&base={default_branch}")
                 if _judgeable(pull, default_branch, log)]
        moved_to = rev_parse(repo, base_ref)[:7]
        for pull in pulls:
            if post:
                api.post_status(slug, pull["head"]["sha"], "pending",
                                f"re-judging: {default_branch} moved to {moved_to}", target_url)
    elif pr is not None:
        pull = api.get(f"repos/{slug}/pulls/{pr}")
        if sha is not None and pull["head"]["sha"] != sha:
            log(f"#{pr}: head moved from {sha[:12]} to {pull['head']['sha'][:12]}; a newer run judges it")
            return []
        pulls = [pull] if _judgeable(pull, default_branch, log) else []
    else:
        pulls = [pull for pull in get_pages(api, f"repos/{slug}/commits/{sha}/pulls")
                 if pull.get("head", {}).get("sha") == sha and _judgeable(pull, default_branch, log)]
    outcomes = []
    for pull in pulls:
        number, head_sha = pull["number"], pull["head"]["sha"]
        result = None
        required = []
        try:
            if fetch:
                fetch_pull_request(repo, default_branch, number, head_sha)
            result = match(repo, base_ref, head_sha, pull["head"].get("ref"), PullLookup(api, slug, default_branch))
            required = required_workflows(repo, result["base"], result["files"], default_branch)
            problems = workflow_problems(repo, result, required, default_branch)
            runs = get_pages(api, f"repos/{slug}/actions/runs?head_sha={head_sha}&event=pull_request",
                             "workflow_runs")
            statuses = {item["context"]: item["state"]
                        for item in get_pages(api, f"repos/{slug}/commits/{head_sha}/status", "statuses")}
            state, description = evaluate(result, required, runs, statuses, problems)
        except Exception as exc:  # fail closed, with the reason where the owner looks
            state, description = "error", truncate(f"merge-conditions could not judge: {exc}")
        log(f"#{number} {head_sha[:12]}: {state} - {description}")
        if result is not None:
            log(json.dumps({key: result[key] for key in ("kind", "change", "gates", "hits", "unaccounted",
                                                          "waived", "errors")}, indent=2))
            log("required workflows: " + (", ".join(required) or "none"))
        posted = False
        if post:
            if _still_head(api, slug, number, head_sha, default_branch):
                api.post_status(slug, head_sha, state, description, target_url)
                posted = True
            else:
                log(f"#{number}: {head_sha[:12]} is no longer its head; not posted")
        outcomes.append({"number": number, "sha": head_sha, "state": state, "description": description,
                         "posted": posted})
    return outcomes


# --------------------------------------------------------------------------------------------
# Deploy guard — the server-side barrier: recomputes, never reads the `merge-conditions` status
# --------------------------------------------------------------------------------------------
#
# What it enforces, server-side: every commit that reaches production came from a merged pull request
# (its merge commit, not edited during the merge), with every trigger hit accounted for and the CI the
# pull request needed green — for the pushed commit AND every first-parent commit since the last
# deployed one, so a refused commit never ships with the next merge (unless a later merged commit
# undoes it exactly). It does NOT enforce the owner's gates: without another identity for the agent,
# an owner merge and an agent merge look the same to it; the gates are the merge route's (client-side).

GUARD_DEPLOY, GUARD_REFUSED, GUARD_CANNOT_JUDGE, GUARD_NOTHING, GUARD_ADOPTION = 0, 1, 2, 3, 4
GUARD_OUTCOMES = {GUARD_DEPLOY: "deploy", GUARD_REFUSED: "refused", GUARD_CANNOT_JUDGE: "cannot-judge",
                  GUARD_NOTHING: "nothing", GUARD_ADOPTION: "adoption"}
GUARD_REF = "refs/sdd-deploy-guard/"
TOKEN_VARIABLES = ("DEPLOY_GUARD_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
ZERO_SHA = "0" * 40
# Commits judged in one run at most: a longer history since the last deploy is the owner's to review.
CHAIN_MAX = 100


class RestGitHub:
    """GitHub's REST API over HTTPS with a token: a deploy pipeline (Vercel) may have no `gh`."""

    def __init__(self, token: str, api_url=None, timeout: int = 30):
        self.token, self.timeout = token, timeout
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    def get(self, path: str):
        request = urllib.request.Request(f"{self.api_url}/{path}", headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sdd-deploy-guard",
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"null")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"GET {path.split('?', 1)[0]}: {exc}") from None


def guard_token(environment=None):
    environment = os.environ if environment is None else environment
    return next((environment[name] for name in TOKEN_VARIABLES if environment.get(name)), None)


def before_from_push(api, slug: str, default_branch: str, sha: str, attempts: int = 3, delay: float = 5.0):
    """(before, activity type) of the push that moved the default branch to `sha`, from the repository
    activity; asked again when the push is not listed yet. (None, None) when it is not found."""
    for attempt in range(attempts):
        activities = api.get(f"repos/{slug}/activity?ref=refs/heads/{default_branch}&per_page={PAGE_SIZE}") or []
        for activity in activities:
            if activity.get("after") == sha and activity.get("ref") in (f"refs/heads/{default_branch}", default_branch):
                return activity.get("before"), activity.get("activity_type")
        if attempt < attempts - 1:
            time.sleep(delay)
    return None, None


class GuardFetcher:
    """Fetches from the repository on GitHub as data: the token goes in an HTTP header through the
    environment, never on the command line, after any inherited header is reset; a shallow clone is
    deepened."""

    def __init__(self, repo: str, slug: str, token: str, server_url=None):
        self.repo = repo
        server_url = (server_url or os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
        self.url = f"{server_url}/{slug}.git"
        header = "Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self.environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="2",
                                GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0="",
                                GIT_CONFIG_KEY_1="http.extraHeader", GIT_CONFIG_VALUE_1=header)

    def fetch(self, *refspecs: str):
        arguments = ["fetch", "--no-tags", "--quiet"]
        if git(self.repo, "rev-parse", "--is-shallow-repository").strip() == "true":
            arguments.append("--unshallow")
        result = subprocess.run(["git", "-C", self.repo, *arguments, self.url, *refspecs], env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise GitError(f"git fetch: {result.stderr.decode('utf-8', 'replace').strip()}")


def merged_pull_request(api, slug: str, default_branch: str, sha: str, attempts: int, delay: float):
    """The pull requests merged into the default branch AS `sha` (its merge commit). GitHub may list the
    association a few seconds after the push, so an empty answer is asked again."""
    lookup = PullLookup(api, slug, default_branch)
    merged = []
    for attempt in range(attempts):
        merged = lookup.merged_as(sha)
        if merged or attempt == attempts - 1:
            break
        time.sleep(delay)
    return merged


def is_ancestor(repo: str, ancestor: str, descendant: str) -> bool:
    return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", ancestor, descendant],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def merged_tree(repo: str, base: str, head: str):
    """The tree of the merge of `head` into `base`, as GitHub computes it (ort); None on a conflict."""
    result = subprocess.run(["git", "-C", repo, *GIT_OPTIONS, "merge-tree", "--write-tree", base, head],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise GitError(f"git merge-tree: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout.decode().split("\n", 1)[0].strip()


def workflow_renames(repo: str, base: str, head: str) -> dict:
    """{old path: new path} of the workflows a diff renames."""
    output = git(repo, "diff", "--name-status", "-z", "-M", "--no-ext-diff", base, head, "--", WORKFLOWS_DIR)
    tokens, renames, index = output.split("\0"), {}, 0
    while index < len(tokens):
        status = tokens[index]
        if status.startswith("R") and index + 2 < len(tokens):
            renames[tokens[index + 1]] = tokens[index + 2]
            index += 3
        else:
            index += 2 if status else 1
    return renames


def judge_commit(api, repo: str, slug: str, default_branch: str, commit: str, fetcher, attempts, delay):
    """(code, reason) of one first-parent commit of the default branch, judged against its first parent."""
    short = commit[:7]
    parent = rev_parse(repo, f"{commit}^1")
    if not parent:
        return GUARD_REFUSED, f"{short} has no parent"
    merged = merged_pull_request(api, slug, default_branch, commit, attempts, delay)
    if not merged:
        return GUARD_REFUSED, f"no pull request was merged into {default_branch} as {short} (direct push)"
    if len(merged) > 1:
        numbers = ", ".join(f"#{pull.get('number')}" for pull in merged)
        return GUARD_REFUSED, f"several pull requests merged as {short} ({numbers})"
    pull = merged[0]
    number, head = pull.get("number"), pull.get("head") or {}
    head_sha, head_ref = head.get("sha") or "", head.get("ref")
    if fetcher is not None:
        fetcher.fetch(f"+refs/pull/{number}/head:{GUARD_REF}pull/{number}")
    if not SHA.match(head_sha) or rev_parse(repo, head_sha) != head_sha:
        return GUARD_CANNOT_JUDGE, f"#{number}'s head {head_sha[:12]!r} unavailable"
    tree = merged_tree(repo, parent, head_sha)
    if tree is None or git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip() != tree:
        return GUARD_REFUSED, (f"{short} is not the merge of {parent[:7]} and #{number}'s head {head_sha[:7]}: "
                               f"its content was edited during the merge")
    if show_file(repo, parent, TRIGGERS_PATH) is None and show_file(repo, commit, TRIGGERS_PATH) is not None:
        return GUARD_ADOPTION, (f"{short} (#{number}) installs {TRIGGERS_PATH}: the adoption merge deploys "
                                f"nothing, the next merge is the first one guarded")
    result = match(repo, parent, head_sha, head_ref, PullLookup(api, slug, default_branch))
    reasons = list(result["errors"])
    if result["unaccounted"]:
        reasons.append(unaccounted_reason(result["unaccounted"]))
    if reasons:
        return GUARD_REFUSED, f"#{number} ({result['label']}): " + "; ".join(reasons)
    renames = workflow_renames(repo, result["merge_base"], head_sha)
    required = [renames.get(path, path) for path in required_workflows(repo, parent, result["files"], default_branch)]
    deleted = {entry.path for entry in diff_entries(repo, result["merge_base"], head_sha) if entry.status == "D"}
    runs = get_pages(api, f"repos/{slug}/actions/runs?head_sha={head_sha}&event=pull_request", "workflow_runs")
    failures, waiting = run_verdicts(required, runs, head_sha, deleted)
    if failures or waiting:
        return GUARD_REFUSED, (f"#{number}: required CI not green on its head {head_sha[:7]}: "
                               + "; ".join(failures + waiting))
    return GUARD_DEPLOY, f"#{number} ({result['kind']}, {result['label']}), required CI green on {head_sha[:7]}"


def undone_later(repo: str, commit: str, later) -> bool:
    """Whether a later commit that passes the guard is exactly the inverse of `commit`."""
    inverse = _transitions(diff_entries(repo, f"{commit}^1", commit), inverse=True)
    return any(code == GUARD_DEPLOY and _transitions(diff_entries(repo, f"{other}^1", other)) == inverse
               for other, code, _ in later)


def deploy_guard(api, repo: str, slug: str, sha: str, before=None, last_deployed=None, paths=None, ref=None,
                 fetch: bool = True, token=None, server_url=None, attempts: int = 3, delay: float = 5.0,
                 target=None):
    """(exit code, reason) of the deploy guard for the commit `sha` of the default branch.

    `before`: the default branch before the push (the push event's `before`); `last_deployed`: the
    commit the target last deployed — the guard judges every first-parent commit after it (after
    `before` when None). Neither → `before` is read from the repository activity. `ref`: the ref a
    manual run was started on (must be the default branch). `target`: a target of the trusted commit's
    .sdd/deployment.yaml — only the commits that change its trigger paths are judged (`paths` does the
    same, and also skips when none changed). Any failure to judge refuses.
    """
    try:
        return _deploy_guard(api, repo, slug, sha, before, last_deployed, paths, ref, fetch, token, server_url,
                             attempts, delay, target)
    except Exception as exc:  # fail closed, with the reason in the deploy log
        return GUARD_CANNOT_JUDGE, f"cannot judge {str(sha)[:7]}: {exc}"


def _deploy_guard(api, repo, slug, sha, before, last_deployed, paths, ref, fetch, token, server_url, attempts,
                  delay, target):
    if not SHA.match(sha or ""):
        return GUARD_CANNOT_JUDGE, f"cannot judge: {sha!r} is not a full commit sha"
    short = sha[:7]
    default_branch = (api.get(f"repos/{slug}") or {}).get("default_branch")
    if not default_branch:
        return GUARD_CANNOT_JUDGE, f"cannot judge {short}: the default branch of {slug} is unknown"
    if ref is not None and ref != f"refs/heads/{default_branch}":
        return GUARD_REFUSED, f"refused {short}: a manual run deploys {default_branch} only, not {ref}"
    if before is None and last_deployed is None:
        before, activity_type = before_from_push(api, slug, default_branch, sha, attempts, delay)
        if before is None:
            return GUARD_CANNOT_JUDGE, (f"cannot judge {short}: no push of {default_branch} to it in the "
                                        f"repository activity, so the commit before it is unknown")
        if activity_type == "force_push":
            return GUARD_REFUSED, (f"refused {short}: {default_branch} was force-pushed to it; the owner "
                                   f"reviews and deploys it by hand")
    for name, value in (("before", before), ("last deployed", last_deployed)):
        if value is not None and not SHA.match(value):
            return GUARD_CANNOT_JUDGE, f"cannot judge {short}: {name} {value!r} is not a full commit sha"
    if before == ZERO_SHA:
        return GUARD_REFUSED, f"refused {short}: the push created {default_branch}, it has no previous commit"
    fetcher = GuardFetcher(repo, slug, token or "", server_url) if fetch else None
    if fetcher is not None:
        fetcher.fetch(f"+refs/heads/{default_branch}:{GUARD_REF}base")
    for commit in (sha, before, last_deployed):
        if commit is not None and rev_parse(repo, commit) != commit:
            return GUARD_CANNOT_JUDGE, f"cannot judge {short}: commit {commit[:12]!r} unavailable"
    if before is not None and rev_parse(repo, f"{sha}^1") != before:
        return GUARD_REFUSED, (f"refused {short}: its first parent is not {before[:7]}, the {default_branch} "
                               f"before the push, so the push carried more than one merge")
    start = last_deployed or before
    if not is_ancestor(repo, start, sha):
        return GUARD_REFUSED, (f"refused {short}: the last deployed commit {start[:7]} is not in its history "
                               f"({default_branch} was rewritten); the owner reviews and sets the reset variable")
    if start not in git(repo, "rev-list", "--first-parent", sha).split():
        return GUARD_REFUSED, (f"refused {short}: the last deployed commit {start[:7]} is not on its first-parent "
                               f"line (a commit of a merged branch, not of {default_branch}): it is not trusted")
    scope = paths
    if target is not None:
        scope, problem = target_scope(repo, start, target)
        if problem:
            return GUARD_CANNOT_JUDGE, f"cannot judge {short}: {problem}"
    commits = git(repo, "rev-list", "--first-parent", "--reverse", f"{start}..{sha}").split()
    if not commits:
        return GUARD_DEPLOY, f"deploy {short}: it is the last deployed commit"
    if paths is not None:
        changed = [entry.path for entry in diff_entries(repo, start, sha)]
        if not any(filter_includes(paths, path) for path in changed):
            return GUARD_NOTHING, f"skip {short}: nothing changed under {' '.join(paths)} since {start[:7]}"
    if scope is not None:
        commits = [commit for commit in commits
                   if any(filter_includes(scope, entry.path) for entry in diff_entries(repo, f"{commit}^1", commit))]
    outside = len(git(repo, "rev-list", "--first-parent", f"{start}..{sha}").split()) - len(commits)
    note = f"; {outside} commit(s) since {start[:7]} outside the target's paths, not judged" if outside else ""
    if not commits:
        return GUARD_DEPLOY, f"deploy {short}: no commit since {start[:7]} changes the target's paths{note}"
    if len(commits) > CHAIN_MAX:
        return GUARD_REFUSED, (f"refused {short}: {len(commits)} commits since the last deployed {start[:7]}, "
                               f"more than {CHAIN_MAX}; the owner reviews and sets the reset variable")
    verdicts = [(commit, *judge_commit(api, repo, slug, default_branch, commit, fetcher, attempts, delay))
                for commit in commits]
    for index, (commit, code, reason) in enumerate(verdicts):
        if code == GUARD_DEPLOY:
            continue
        if code == GUARD_REFUSED and undone_later(repo, commit, verdicts[index + 1:]):
            continue
        word = {GUARD_REFUSED: "refused", GUARD_CANNOT_JUDGE: "cannot judge", GUARD_ADOPTION: "adoption"}[code]
        if commit == sha:
            return code, f"{word} {short}: {reason}{note}"
        return code, (f"{word} {short}: {commit[:7]}, merged since the last deployed {start[:7]}, is not "
                      f"deployable: {reason}{note}")
    return GUARD_DEPLOY, f"deploy {short}: {verdicts[-1][2]}" + (
        f" (and {len(commits) - 1} earlier commit(s) since {start[:7]})" if len(commits) > 1 else "") + note


def target_scope(repo: str, trusted: str, name: str):
    """(trigger paths or None for every push, problem) of a deploy target, read from the TRUSTED
    commit's .sdd/deployment.yaml (never the pushed one's)."""
    text = show_file(repo, trusted, f".sdd/{DEPLOYMENT_FILE}")
    if text is None:
        return None, f"no .sdd/{DEPLOYMENT_FILE} at the trusted commit {trusted[:7]}"
    profile, errors, _ = load_deployment(text)
    if profile is None:
        return None, f".sdd/{DEPLOYMENT_FILE} at {trusted[:7]} is invalid ({errors[0]})"
    for item in profile.get("targets") or []:
        if item["name"] == name:
            trigger = item["trigger"]
            return (None if trigger.get("every_push") else list(trigger["paths"])), None
    return None, f"no target {name!r} in .sdd/{DEPLOYMENT_FILE} at {trusted[:7]}"


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def validate_files(paths, unconfirmed=None) -> list:
    """Schema errors of each file; `unconfirmed`, a list, receives `<file>: <value>` for every value a
    deployment profile marks `unconfirmed: true` (valid, but to be confirmed by the owner)."""
    errors = []
    for path in paths:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
        if name == "triggers.yaml":
            _, found = load_triggers(text)
        elif name == CLASSIFICATION_FILE:
            _, found = load_classification(text, folder)
        elif name == REVERT_FILE:
            _, found = load_revert(text, folder)
        elif name == DEPLOYMENT_FILE:
            _, found, values = load_deployment(text)
            if unconfirmed is not None:
                unconfirmed.extend(f"{path}: {value}" for value in values)
        else:
            found = [f"not a triggers.yaml, {CLASSIFICATION_FILE}, {REVERT_FILE} or {DEPLOYMENT_FILE} file"]
        errors.extend(f"{path}: {message}" for message in found)
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-C", dest="directory", default=".", help="repository directory (default: .)")
    commands = parser.add_subparsers(dest="command", required=True)

    match_parser = commands.add_parser("match", help="classify a diff; prints JSON; exit 1 when not clean")
    match_parser.add_argument("--base", required=True,
                              help="base commit, e.g. origin/main; in the deploy guard, the default branch before the merge (the push event's `before`), never <merge>^1, which a rebase merge makes wrong")
    match_parser.add_argument("--head", required=True, help="head commit or ref")
    match_parser.add_argument("--branch", required=True, help="pull request branch name, e.g. feat/<change-id>")

    check_parser = commands.add_parser("check", help="judge pull requests and post the merge-conditions status")
    check_parser.add_argument("--repo", required=True, help="owner/name")
    check_parser.add_argument("--default-branch", required=True)
    target = check_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int)
    target.add_argument("--sha")
    target.add_argument("--all-open", action="store_true",
                        help="re-judge every open pull request into the default branch")
    check_parser.add_argument("--head-sha", help="with --pr: the head commit the event named")
    check_parser.add_argument("--dry-run", action="store_true", help="print, do not post the status")

    guard_parser = commands.add_parser(
        "deploy-guard", help="may this commit of the default branch deploy? exit 0 deploy, 1 refused, "
                             "2 cannot judge, 3 nothing under --paths, 4 adoption merge")
    guard_parser.add_argument("--repo", required=True, help="owner/name")
    guard_parser.add_argument("--sha", required=True, help="the pushed commit of the default branch")
    before = guard_parser.add_mutually_exclusive_group()
    before.add_argument("--before", help="the default branch before the push (the push event's `before`)")
    before.add_argument("--before-from-push", action="store_true",
                        help="read `before` from the repository activity (a platform given neither the push "
                             "event nor its last deployment)")
    guard_parser.add_argument("--last-deployed",
                              help="the commit the target last deployed: every first-parent commit after it is judged")
    guard_parser.add_argument("--ref", help="the ref a manual run (workflow_dispatch) was started on")
    guard_parser.add_argument("--target", help="the deploy target (.sdd/deployment.yaml of the trusted commit): only "
                                               "the commits that change its trigger paths are judged")
    guard_parser.add_argument("--paths", nargs="+",
                              help="deploy only when a path matching these globs changed since the last deployed "
                                   "commit (exit 3 otherwise)")
    guard_parser.add_argument("--no-fetch", action="store_true",
                              help="do not fetch the default branch and the pull request heads first")
    guard_parser.add_argument("--verdict-file", help="also write the verdict there, as JSON (code, outcome, reason)")

    validate_parser = commands.add_parser(
        "validate", help="check triggers.yaml / classification.yaml / revert.yaml / deployment.yaml files")
    validate_parser.add_argument("files", nargs="+")

    args = parser.parse_args(argv)
    if args.command == "deploy-guard":
        if args.before is None and args.last_deployed is None and not args.before_from_push:
            parser.error("deploy-guard needs --before, --last-deployed or --before-from-push")
        token = guard_token()
        if token is None:
            code, reason = GUARD_CANNOT_JUDGE, f"cannot judge: no token ({', '.join(TOKEN_VARIABLES)})"
        else:
            code, reason = deploy_guard(RestGitHub(token), args.directory, args.repo, args.sha, before=args.before,
                                        last_deployed=args.last_deployed, paths=args.paths, ref=args.ref,
                                        fetch=not args.no_fetch, token=token, target=args.target)
        reason = printable(reason)
        if args.verdict_file:
            with open(args.verdict_file, "w", encoding="utf-8") as handle:
                json.dump({"code": code, "outcome": GUARD_OUTCOMES.get(code, "cannot-judge"), "sha": args.sha,
                           "reason": reason}, handle)
        print(f"deploy-guard: {reason}")
        return code
    if args.command == "match":
        try:
            result = match(args.directory, args.base, args.head, args.branch)
        except GitError as exc:
            print(f"merge_conditions.py: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 1 if result["errors"] or result["unaccounted"] else 0
    if args.command == "validate":
        unconfirmed: list = []
        errors = validate_files(args.files, unconfirmed)
        for value in unconfirmed:
            print(f"unconfirmed: {value}")
        for message in errors:
            print(message, file=sys.stderr)
        return 1 if errors else 0
    if args.head_sha and args.pr is None:
        parser.error("--head-sha goes with --pr")
    server = os.environ.get("GITHUB_SERVER_URL")
    run_id = os.environ.get("GITHUB_RUN_ID")
    target_url = f"{server}/{args.repo}/actions/runs/{run_id}" if server and run_id else None
    outcomes = check(GitHub(), args.directory, args.repo, args.default_branch, pr=args.pr,
                     sha=args.sha if args.pr is None else args.head_sha, all_open=args.all_open,
                     post=not args.dry_run, target_url=target_url)
    print(json.dumps(outcomes, indent=2))
    return 1 if any(outcome["state"] == "error" for outcome in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
