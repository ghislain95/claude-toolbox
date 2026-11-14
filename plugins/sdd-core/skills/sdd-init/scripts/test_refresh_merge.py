#!/usr/bin/env python3
"""Tests of refresh_merge.py: `python3 test_refresh_merge.py` (standard library and git only, offline: the
toolbox is a local repository reached through a file:// URL)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "refresh_merge.py")
TEMPLATES = "plugins/sdd-core/skills/sdd-init/templates"

TEMPLATE_V1 = "".join("line %d of the kit\n" % number for number in range(1, 11))


def git(directory, *arguments):
    return subprocess.run(
        ["git", "-C", directory, *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"),
    ).stdout.strip()


def replace_line(text, number, new):
    lines = text.splitlines(True)
    lines[number - 1] = new
    return "".join(lines)


class RefreshCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="refresh-merge-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, relative, text, binary=False):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if binary else "w") as handle:
            handle.write(text)
        return path

    def read(self, relative, binary=False):
        with open(os.path.join(self.root, relative), "rb" if binary else "r") as handle:
            return handle.read()

    def run_script(self, *arguments, expect=0, environment=None):
        completed = subprocess.run(
            [sys.executable, SCRIPT, *arguments], capture_output=True, text=True, cwd=self.root, timeout=120,
            env=dict(os.environ, **(environment or {})),
        )
        self.assertEqual(completed.returncode, expect, completed.stdout + completed.stderr)
        self.stderr = completed.stderr
        return json.loads(completed.stdout)

    def merge(self, entries, expect=0):
        manifest = self.write("manifest.json", json.dumps(entries))
        return self.run_script("merge", "--manifest", manifest, "--old-version", "0.3.0", "--new-version", "0.4.0", expect=expect)

    def base_and_theirs(self, theirs_line=9):
        base = self.write("base/CLAUDE.md", TEMPLATE_V1)
        theirs = self.write("new/CLAUDE.md", replace_line(TEMPLATE_V1, theirs_line, "line %d changed by the kit\n" % theirs_line))
        return base, theirs


class MergeTest(RefreshCase):
    def test_local_edit_and_kit_change_on_different_lines_are_both_kept(self):
        base, theirs = self.base_and_theirs()
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 2, "line 2 edited by the project\n"))
        report = self.merge([{"path": "project/CLAUDE.md", "base": base, "theirs": theirs}])
        merged = self.read("project/CLAUDE.md")
        self.assertIn("line 2 edited by the project\n", merged)
        self.assertIn("line 9 changed by the kit\n", merged)
        self.assertNotIn("<<<<<<<", merged)
        self.assertEqual([item["path"] for item in report["merged"]], ["project/CLAUDE.md"])

    def test_the_same_lines_changed_on_both_sides_is_a_conflict_left_to_the_owner(self):
        base, theirs = self.base_and_theirs(5)
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 5, "line 5 by the project\n"))
        report = self.merge([{"path": "project/CLAUDE.md", "base": base, "theirs": theirs}], expect=1)
        self.assertEqual(report["conflicts"], [{"path": "project/CLAUDE.md", "status": "conflict", "conflicts": 1}])
        self.assertIn(
            "<<<<<<< local\nline 5 by the project\n||||||| kit 0.3.0\nline 5 of the kit\n=======\nline 5 changed by the kit\n>>>>>>> kit 0.4.0\n",
            self.read("project/CLAUDE.md"),
        )

    def test_a_file_still_holding_conflict_markers_is_refused_and_nothing_is_written(self):
        base, theirs = self.base_and_theirs(5)
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 5, "line 5 by the project\n"))
        self.merge([{"path": "project/CLAUDE.md", "base": base, "theirs": theirs}], expect=1)
        conflicted = self.read("project/CLAUDE.md")
        self.write("project/OTHER.md", replace_line(TEMPLATE_V1, 2, "x\n"))
        report = self.merge(
            [{"path": "project/OTHER.md", "base": base, "theirs": theirs}, {"path": "project/CLAUDE.md", "base": base, "theirs": theirs}], expect=2
        )
        self.assertIn("conflict markers", report["error"])
        self.assertEqual(self.read("project/CLAUDE.md"), conflicted)
        self.assertEqual(self.read("project/OTHER.md"), replace_line(TEMPLATE_V1, 2, "x\n"), "nothing written when one entry fails")

    def test_the_same_change_on_both_sides_merges_cleanly(self):
        base = self.write("base/a.md", TEMPLATE_V1)
        changed = replace_line(TEMPLATE_V1, 3, "line 3, both\n")
        theirs = self.write("new/a.md", changed)
        self.write("project/a.md", changed)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}])
        self.assertEqual([item["path"] for item in report["unchanged"]], ["project/a.md"])

    def test_no_base_commit_is_two_way_and_keeps_the_local_file(self):
        theirs = self.write("new/a.md", replace_line(TEMPLATE_V1, 9, "line 9 changed by the kit\n"))
        local = replace_line(TEMPLATE_V1, 2, "line 2 edited by the project\n")
        self.write("project/a.md", local)
        report = self.merge([{"path": "project/a.md", "base": None, "theirs": theirs}], expect=4)
        self.assertEqual(self.read("project/a.md"), local)
        outcome = report["two_way"][0]
        self.assertEqual((outcome["path"], outcome["reason"]), ("project/a.md", "no-base-commit"))
        self.assertIn("-line 2 edited by the project\n", outcome["hunks"])
        self.assertIn("+line 9 changed by the kit\n", outcome["hunks"])

    def test_no_base_and_no_difference_is_unchanged(self):
        theirs = self.write("new/a.md", TEMPLATE_V1)
        self.write("project/a.md", TEMPLATE_V1)
        report = self.merge([{"path": "project/a.md", "base": None, "theirs": theirs}])
        self.assertEqual((len(report["unchanged"]), report["two_way"]), (1, []))

    def test_a_file_new_in_the_kit_is_created_or_two_way_when_the_project_has_its_own(self):
        theirs = self.write("new/new.md", "new template\n")
        self.write("project/existing.md", "the project's own\n")
        absent_base = os.path.join(self.root, "base/new.md")
        report = self.merge(
            [{"path": "project/new.md", "base": absent_base, "theirs": theirs}, {"path": "project/existing.md", "base": absent_base, "theirs": theirs}],
            expect=4,
        )
        self.assertEqual(self.read("project/new.md"), "new template\n")
        self.assertEqual([item["path"] for item in report["created"]], ["project/new.md"])
        self.assertEqual(report["two_way"][0]["reason"], "new-in-kit")
        self.assertEqual(self.read("project/existing.md"), "the project's own\n")

    def test_a_file_the_project_deleted_is_not_created_again(self):
        base, theirs = self.base_and_theirs()
        report = self.merge([{"path": "project/GRAPHIFY.md", "base": base, "theirs": theirs}])
        self.assertEqual([item["path"] for item in report["deleted_locally"]], ["project/GRAPHIFY.md"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "project/GRAPHIFY.md")))
        report = self.merge([{"path": "project/GRAPHIFY.md", "base": None, "theirs": theirs}], expect=4)
        self.assertEqual(report["two_way"][0]["reason"], "no-base-commit")
        self.assertFalse(os.path.exists(os.path.join(self.root, "project/GRAPHIFY.md")))

    def test_nothing_changed_in_the_kit_leaves_the_file_alone(self):
        base = self.write("base/a.md", TEMPLATE_V1)
        theirs = self.write("new/a.md", TEMPLATE_V1)
        local = replace_line(TEMPLATE_V1, 1, "local\n")
        self.write("project/a.md", local)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}])
        self.assertEqual(self.read("project/a.md"), local)
        self.assertEqual(len(report["unchanged"]), 1)

    def test_one_failing_entry_writes_nothing(self):
        base, theirs = self.base_and_theirs()
        local = replace_line(TEMPLATE_V1, 2, "local\n")
        self.write("project/a.md", local)
        self.write("project/b.md", local)
        self.merge(
            [{"path": "project/a.md", "base": base, "theirs": theirs}, {"path": "project/b.md", "base": base, "theirs": os.path.join(self.root, "nope.md")}],
            expect=2,
        )
        self.assertEqual(self.read("project/a.md"), local)

    def test_a_file_that_is_not_utf8_is_a_usage_error(self):
        base, theirs = self.base_and_theirs()
        self.write("project/a.md", b"\xff\xfe binary\n", binary=True)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}], expect=2)
        self.assertIn("not UTF-8", report["error"])

    def test_crlf_files_keep_their_line_endings_and_merge(self):
        base, theirs = self.base_and_theirs()
        local = replace_line(TEMPLATE_V1, 2, "line 2 edited by the project\n").replace("\n", "\r\n")
        self.write("project/a.md", local.encode(), binary=True)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}])
        self.assertEqual(len(report["merged"]), 1, report)
        merged = self.read("project/a.md", binary=True)
        self.assertIn(b"line 2 edited by the project\r\n", merged)
        self.assertIn(b"line 9 changed by the kit\r\n", merged)
        self.assertNotIn(b"\n", merged.replace(b"\r\n", b""))
        unchanged = self.write("new/same.md", TEMPLATE_V1)
        self.write("project/b.md", TEMPLATE_V1.replace("\n", "\r\n").encode(), binary=True)
        self.assertEqual(len(self.merge([{"path": "project/b.md", "base": base, "theirs": unchanged}])["unchanged"]), 1)
        self.write("project/c.md", TEMPLATE_V1.replace("\n", "\r\n").encode(), binary=True)
        self.assertEqual(len(self.merge([{"path": "project/c.md", "base": None, "theirs": unchanged}])["unchanged"]), 1)

    def test_two_entries_on_the_same_file_through_a_symlink_are_refused(self):
        base, theirs = self.base_and_theirs()
        self.write("project/CLAUDE.md", TEMPLATE_V1)
        os.symlink("CLAUDE.md", os.path.join(self.root, "project/AGENTS.md"))
        report = self.merge(
            [{"path": "project/AGENTS.md", "base": base, "theirs": theirs}, {"path": "project/CLAUDE.md", "base": base, "theirs": theirs}], expect=2
        )
        self.assertIn("same file", report["error"])

    def test_a_symlinked_file_is_merged_into_its_target(self):
        base, theirs = self.base_and_theirs()
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 2, "local\n"))
        os.symlink("CLAUDE.md", os.path.join(self.root, "project/AGENTS.md"))
        self.merge([{"path": "project/AGENTS.md", "base": base, "theirs": theirs}])
        self.assertTrue(os.path.islink(os.path.join(self.root, "project/AGENTS.md")))
        self.assertIn("line 9 changed by the kit\n", self.read("project/CLAUDE.md"))

    def test_a_missing_new_template_is_a_usage_error(self):
        self.write("project/a.md", "x\n")
        self.merge([{"path": "project/a.md", "base": None, "theirs": os.path.join(self.root, "nope.md")}], expect=2)


class FetchBaseTest(RefreshCase):
    def setUp(self):
        super().setUp()
        self.toolbox = os.path.join(self.root, "toolbox")
        os.makedirs(os.path.join(self.toolbox, TEMPLATES, "root"))
        git(self.toolbox, "init", "-q", "-b", "main")
        with open(os.path.join(self.toolbox, TEMPLATES, "root", "CLAUDE.md"), "w") as handle:
            handle.write("template at the first release\n")
        with open(os.path.join(self.toolbox, "README.md"), "w") as handle:
            handle.write("not a template\n")
        git(self.toolbox, "add", ".")
        git(self.toolbox, "commit", "-q", "-m", "first")
        self.first = git(self.toolbox, "rev-parse", "HEAD")
        with open(os.path.join(self.toolbox, TEMPLATES, "root", "CLAUDE.md"), "w") as handle:
            handle.write("template later, same version number\n")
        git(self.toolbox, "commit", "-q", "-am", "later")
        self.later = git(self.toolbox, "rev-parse", "HEAD")
        self.url = "file://" + self.toolbox

    def fetch(self, sha, destination="base", expect=0, repository="default", environment=None):
        arguments = ["fetch-base", "--sha", sha, "--dest", os.path.join(self.root, destination)]
        repository = self.url if repository == "default" else repository
        if repository:
            arguments += ["--repository", repository]
        return self.run_script(*arguments, expect=expect, environment=environment)

    def test_each_commit_gives_its_own_templates_even_under_one_version_number(self):
        result = self.fetch(self.first)
        self.assertEqual((result["status"], result["sha"], result["files"]), ("fetched", self.first, 1))
        self.assertEqual(self.read("base/root/CLAUDE.md"), "template at the first release\n")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "base"))), ["root"])
        self.fetch(self.later, "later")
        self.assertEqual(self.read("later/root/CLAUDE.md"), "template later, same version number\n")

    def test_an_overridden_repository_is_reported(self):
        result = self.fetch(self.first)
        self.assertEqual(result["repository_override"], self.url)
        self.assertIn("WARNING", self.stderr)
        result = self.fetch(self.first, "env", repository=None, environment={"SDD_TOOLBOX_REPOSITORY": self.url})
        self.assertEqual(result["repository_override"], self.url)

    def test_an_unknown_commit_falls_back(self):
        result = self.fetch("0" * 40, expect=3)
        self.assertEqual(result["status"], "missing-commit")
        self.assertFalse(os.path.exists(os.path.join(self.root, "base")))

    def test_a_commit_without_the_templates_falls_back(self):
        git(self.toolbox, "rm", "-q", "-r", "plugins")
        git(self.toolbox, "commit", "-q", "-m", "no templates")
        self.assertEqual(self.fetch(git(self.toolbox, "rev-parse", "HEAD"), expect=3)["status"], "missing-commit")

    def test_an_unreachable_repository_falls_back(self):
        result = self.fetch(self.first, expect=3, repository="file://" + os.path.join(self.root, "nowhere"))
        self.assertEqual(result["status"], "unreachable")

    def test_anything_but_a_full_sha_is_refused(self):
        for value in (self.first[:12], self.first + "0", "sdd-core-v0.3.0", self.first.upper()):
            self.fetch(value, expect=2)

    def test_a_non_empty_destination_is_refused(self):
        self.write("base/keep.md", "x\n")
        self.fetch(self.first, expect=2)


class InstallShaTest(RefreshCase):
    def record(self, install_path, sha="a" * 40, key="sdd-core@claude-toolbox"):
        self.write("config/plugins/installed_plugins.json", json.dumps(
            {"version": 2, "plugins": {key: [{"scope": "user", "installPath": install_path, "version": "0.4.0", "gitCommitSha": sha}]}}
        ))

    def test_the_installed_plugins_record_gives_the_commit(self):
        install = os.path.join(self.root, "cache/sdd-core/0.4.0")
        os.makedirs(os.path.join(install, "skills/sdd-init"))
        self.record(install)
        result = self.run_script("install-sha", "--skill-dir", os.path.join(install, "skills/sdd-init"), "--config-dir", os.path.join(self.root, "config"))
        self.assertEqual((result["sha"], result["source"]), ("a" * 40, "installed_plugins.json"))

    def test_another_plugin_another_path_or_a_bad_sha_is_not_taken(self):
        install = os.path.join(self.root, "cache/sdd-core/0.4.0")
        os.makedirs(os.path.join(install, "skills/sdd-init"))
        skill = os.path.join(install, "skills/sdd-init")
        for path, sha, key in ((install, "a" * 40, "handoff@claude-toolbox"), (install + "-other", "a" * 40, "sdd-core@claude-toolbox"), (install, "abc", "sdd-core@claude-toolbox")):
            self.record(path, sha, key)
            result = self.run_script("install-sha", "--skill-dir", skill, "--config-dir", os.path.join(self.root, "config"))
            self.assertIsNone(result["sha"], (path, sha, key))
        sibling = install + "-other"
        os.makedirs(os.path.join(sibling, "skills/sdd-init"))
        self.record(install)
        result = self.run_script("install-sha", "--skill-dir", os.path.join(sibling, "skills/sdd-init"), "--config-dir", os.path.join(self.root, "config"))
        self.assertIsNone(result["sha"], "a sibling directory sharing the install path's prefix is not inside it")

    def test_a_clean_git_checkout_gives_its_head_a_dirty_one_nothing(self):
        kit = os.path.join(self.root, "kit")
        self.write("kit/skills/sdd-init/SKILL.md", "x\n")
        git(kit, "init", "-q", "-b", "main")
        git(kit, "add", ".")
        git(kit, "commit", "-q", "-m", "kit")
        skill = os.path.join(kit, "skills/sdd-init")
        result = self.run_script("install-sha", "--skill-dir", skill, "--config-dir", os.path.join(self.root, "none"))
        self.assertEqual((result["sha"], result["source"]), (git(kit, "rev-parse", "HEAD"), "git checkout"))
        self.write("kit/skills/sdd-init/SKILL.md", "edited\n")
        self.assertIsNone(self.run_script("install-sha", "--skill-dir", skill, "--config-dir", os.path.join(self.root, "none"))["sha"])


class ReadMarkerTest(RefreshCase):
    def test_new_and_former_markers(self):
        sha = "b" * 40
        self.write("p/CLAUDE.md", "# P\n<!-- claude-toolbox: installed 0.4.0 (%s) on 2026-11-14 — options: github, ui -->\n" % sha)
        result = self.run_script("read-marker", os.path.join(self.root, "p/CLAUDE.md"))
        self.assertEqual((result["version"], result["sha"], result["options"]), ("0.4.0", sha, ["github", "ui"]))
        self.write("q/CLAUDE.md", "<!-- sdd-kit: installed 0.2.0 on 2026-11-07 — options: lean — autonomy: autonomy-pr -->\n")
        result = self.run_script("read-marker", os.path.join(self.root, "q/CLAUDE.md"))
        self.assertEqual((result["version"], result["sha"], result["options"]), ("0.2.0", None, ["lean"]))

    def test_a_malformed_version_or_sha_is_not_taken(self):
        self.write("p/CLAUDE.md", "<!-- claude-toolbox: installed 0.4.0x (abc) on 2026-11-14 -->\n")
        result = self.run_script("read-marker", os.path.join(self.root, "p/CLAUDE.md"))
        self.assertEqual((result["version"], result["sha"]), (None, None))

    def test_both_files_with_a_marker_is_a_conflict_root_first(self):
        self.write("p/CLAUDE.md", "<!-- claude-toolbox: installed 0.3.0 on 2026-11-12 -->\n")
        self.write("p/.claude/CLAUDE.md", "<!-- claude-toolbox: installed 0.4.0 on 2026-11-14 -->\n")
        files = [os.path.join(self.root, "p/CLAUDE.md"), os.path.join(self.root, "p/.claude/CLAUDE.md")]
        result = self.run_script("read-marker", *files)
        self.assertEqual((result["version"], result["conflict"]), ("0.3.0", files))
        self.run_script("read-marker", os.path.join(self.root, "nothing.md"), expect=3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
