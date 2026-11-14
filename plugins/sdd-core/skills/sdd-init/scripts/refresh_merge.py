#!/usr/bin/env python3
"""Three-way merge of `/sdd-core:sdd-init --refresh` (Python 3.9+, standard library and git only).

    refresh_merge.py fetch-base --version <x.y.z> --dest <empty dir> [--repository <url>]
        the sdd-init templates of the recorded kit version, from the toolbox's tag sdd-core-v<x.y.z>,
        into <dest>. Exit 0 with {"status": "fetched"}; exit 3 with {"status": "missing-tag"} or
        {"status": "unreachable"} when the base cannot be had: the refresh then falls back to two ways.

    refresh_merge.py merge --manifest <file.json>
        for each {"path", "base", "theirs"} of the manifest: `path` is the project's file (ours, merged
        in place), `base` the recorded version's template filled with the project's values (null when
        there is none: two-way fallback), `theirs` the new template filled with the same values.
        Exit 0: merged cleanly or nothing to do; exit 1: conflicts left in the files, with diff3 markers,
        for the owner to settle; exit 2: usage error. The JSON report lists every file by outcome.

The merge itself is `git merge-file --diff3`: a local edit and a kit change on different lines are both
kept, the same lines changed differently on both sides are a conflict. Nothing is ever resolved by
picking a side. In the two-way fallback the project's file is left untouched and the differences with
the new template are listed (`hunks`), for the agent to apply only what plainly comes from the kit.
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
TAG_PREFIX = "sdd-core-v"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
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


def fetch_base(version, destination, repository):
    """The templates of `version` from the tag, in `destination`; or why they could not be had."""
    if not VERSION.match(version):
        raise UsageError("not a version: %r (expected x.y.z)" % version)
    if os.path.exists(destination) and os.listdir(destination):
        raise UsageError("destination is not empty: " + destination)
    tag = TAG_PREFIX + version
    reference = "refs/tags/" + tag
    try:
        listed = git("ls-remote", "--tags", repository, reference)
    except subprocess.TimeoutExpired:
        return {"status": "unreachable", "tag": tag, "reason": "no answer from %s" % repository}
    if listed.returncode != 0:
        return {"status": "unreachable", "tag": tag, "reason": listed.stderr.strip() or "git ls-remote failed"}
    if not any(line.split("\t")[-1] in (reference, reference + "^{}") for line in listed.stdout.splitlines()):
        return {"status": "missing-tag", "tag": tag, "reason": "%s has no tag %s" % (repository, tag)}
    work = tempfile.mkdtemp(prefix="sdd-refresh-base-")
    try:
        git("init", "-q", work)
        try:
            fetched = git("fetch", "-q", "--depth", "1", repository, reference, cwd=work)
        except subprocess.TimeoutExpired:
            return {"status": "unreachable", "tag": tag, "reason": "fetch timed out"}
        if fetched.returncode != 0:
            return {"status": "unreachable", "tag": tag, "reason": fetched.stderr.strip()}
        archive = git("archive", "--format=tar", "FETCH_HEAD", TEMPLATES_PATH, cwd=work, binary=True)
        if archive.returncode != 0:
            return {"status": "missing-tag", "tag": tag, "reason": "the tag has no %s" % TEMPLATES_PATH}
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
        return {"status": "fetched", "tag": tag, "files": count, "path": os.path.abspath(destination)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def merge_one(path, base, theirs, old_label, new_label):
    if not os.path.isfile(theirs):
        raise UsageError("the new template is missing: " + theirs)
    if not os.path.exists(path):
        # A file the kit adds and the project does not have yet.
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        shutil.copyfile(theirs, path)
        return {"path": path, "status": "created"}
    ours_text = _read(path)
    if base is None or not os.path.isfile(base):
        theirs_text = _read(theirs)
        if ours_text == theirs_text:
            return {"path": path, "status": "unchanged"}
        hunks = "".join(
            difflib.unified_diff(
                ours_text.splitlines(True), theirs_text.splitlines(True), "local/" + path, "kit/" + path
            )
        )
        reason = "no base for this file" if base is not None else "no base version"
        return {"path": path, "status": "two-way", "reason": reason, "hunks": hunks}
    merged = subprocess.run(
        ["git", "merge-file", "-p", "--diff3", "-L", "local", "-L", old_label, "-L", new_label, path, base, theirs],
        capture_output=True,
    )
    if merged.returncode < 0 or merged.returncode > 127:
        raise UsageError("git merge-file failed on %s: %s" % (path, merged.stderr.decode(errors="replace")))
    result = merged.stdout.decode("utf-8")
    if merged.returncode > 0:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(result)
        return {"path": path, "status": "conflict", "conflicts": merged.returncode}
    if result == ours_text:
        return {"path": path, "status": "unchanged"}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(result)
    return {"path": path, "status": "merged"}


def merge(manifest_path, old_version, new_version):
    with open(manifest_path, encoding="utf-8") as handle:
        entries = json.load(handle)
    if not isinstance(entries, list):
        raise UsageError("the manifest is a JSON list of {path, base, theirs}")
    old_label = "kit %s" % (old_version or "recorded version")
    new_label = "kit %s" % (new_version or "new version")
    report = {"merged": [], "unchanged": [], "created": [], "two_way": [], "conflicts": []}
    keys = {"merged": "merged", "unchanged": "unchanged", "created": "created", "two-way": "two_way", "conflict": "conflicts"}
    for entry in entries:
        outcome = merge_one(entry["path"], entry.get("base"), entry["theirs"], old_label, new_label)
        report[keys[outcome["status"]]].append(outcome)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fetching = commands.add_parser("fetch-base")
    fetching.add_argument("--version", required=True)
    fetching.add_argument("--dest", required=True)
    fetching.add_argument("--repository", default=os.environ.get("SDD_TOOLBOX_REPOSITORY", DEFAULT_REPOSITORY))
    merging = commands.add_parser("merge")
    merging.add_argument("--manifest", required=True)
    merging.add_argument("--old-version")
    merging.add_argument("--new-version")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "fetch-base":
            output = fetch_base(arguments.version, arguments.dest, arguments.repository)
            print(json.dumps(output, indent=2))
            return 0 if output["status"] == "fetched" else 3
        report = merge(arguments.manifest, arguments.old_version, arguments.new_version)
    except UsageError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
