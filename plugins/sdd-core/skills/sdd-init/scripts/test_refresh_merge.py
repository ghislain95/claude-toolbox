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
    subprocess.run(
        ["git", "-C", directory, *arguments],
        check=True,
        capture_output=True,
        env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"),
    )


def replace_line(text, number, new):
    lines = text.splitlines(True)
    lines[number - 1] = new
    return "".join(lines)


class RefreshCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="refresh-merge-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, relative, text):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def read(self, relative):
        with open(os.path.join(self.root, relative)) as handle:
            return handle.read()

    def run_script(self, *arguments, expect=0):
        completed = subprocess.run([sys.executable, SCRIPT, *arguments], capture_output=True, text=True, cwd=self.root, timeout=120)
        self.assertEqual(completed.returncode, expect, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def merge(self, entries, expect=0):
        manifest = self.write("manifest.json", json.dumps(entries))
        return self.run_script("merge", "--manifest", manifest, "--old-version", "0.3.0", "--new-version", "0.4.0", expect=expect)


class MergeTest(RefreshCase):
    def test_local_edit_and_kit_change_on_different_lines_are_both_kept(self):
        base = self.write("base/CLAUDE.md", TEMPLATE_V1)
        theirs = self.write("new/CLAUDE.md", replace_line(TEMPLATE_V1, 9, "line 9 changed by the kit\n"))
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 2, "line 2 edited by the project\n"))
        report = self.merge([{"path": "project/CLAUDE.md", "base": base, "theirs": theirs}])
        merged = self.read("project/CLAUDE.md")
        self.assertIn("line 2 edited by the project\n", merged)
        self.assertIn("line 9 changed by the kit\n", merged)
        self.assertNotIn("<<<<<<<", merged)
        self.assertEqual([item["path"] for item in report["merged"]], ["project/CLAUDE.md"])
        self.assertEqual(report["conflicts"], [])

    def test_the_same_lines_changed_on_both_sides_is_a_conflict_left_to_the_owner(self):
        base = self.write("base/CLAUDE.md", TEMPLATE_V1)
        theirs = self.write("new/CLAUDE.md", replace_line(TEMPLATE_V1, 5, "line 5 by the kit\n"))
        self.write("project/CLAUDE.md", replace_line(TEMPLATE_V1, 5, "line 5 by the project\n"))
        report = self.merge([{"path": "project/CLAUDE.md", "base": base, "theirs": theirs}], expect=1)
        self.assertEqual(report["conflicts"], [{"path": "project/CLAUDE.md", "status": "conflict", "conflicts": 1}])
        merged = self.read("project/CLAUDE.md")
        self.assertIn(
            "<<<<<<< local\nline 5 by the project\n||||||| kit 0.3.0\nline 5 of the kit\n=======\nline 5 by the kit\n>>>>>>> kit 0.4.0\n",
            merged,
        )

    def test_the_same_change_on_both_sides_merges_cleanly(self):
        base = self.write("base/a.md", TEMPLATE_V1)
        changed = replace_line(TEMPLATE_V1, 3, "line 3, both\n")
        theirs = self.write("new/a.md", changed)
        self.write("project/a.md", changed)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}])
        self.assertEqual([item["path"] for item in report["unchanged"]], ["project/a.md"])
        self.assertEqual(self.read("project/a.md"), changed)

    def test_no_base_falls_back_to_two_ways_and_keeps_the_local_file(self):
        theirs = self.write("new/a.md", replace_line(TEMPLATE_V1, 9, "line 9 changed by the kit\n"))
        local = replace_line(TEMPLATE_V1, 2, "line 2 edited by the project\n")
        self.write("project/a.md", local)
        report = self.merge([{"path": "project/a.md", "base": None, "theirs": theirs}])
        self.assertEqual(self.read("project/a.md"), local)
        outcome = report["two_way"][0]
        self.assertEqual((outcome["path"], outcome["reason"]), ("project/a.md", "no base version"))
        self.assertIn("-line 2 edited by the project\n", outcome["hunks"])
        self.assertIn("+line 9 changed by the kit\n", outcome["hunks"])

    def test_no_base_and_no_difference_is_unchanged(self):
        theirs = self.write("new/a.md", TEMPLATE_V1)
        self.write("project/a.md", TEMPLATE_V1)
        report = self.merge([{"path": "project/a.md", "base": None, "theirs": theirs}])
        self.assertEqual((len(report["unchanged"]), report["two_way"]), (1, []))

    def test_a_file_the_kit_adds_is_created_and_one_the_project_already_has_is_two_way(self):
        theirs = self.write("new/new.md", "new template\n")
        self.write("project/existing.md", "the project's own\n")
        report = self.merge(
            [
                {"path": "project/new.md", "base": os.path.join(self.root, "base/new.md"), "theirs": theirs},
                {"path": "project/existing.md", "base": os.path.join(self.root, "base/new.md"), "theirs": theirs},
            ]
        )
        self.assertEqual(self.read("project/new.md"), "new template\n")
        self.assertEqual([item["path"] for item in report["created"]], ["project/new.md"])
        self.assertEqual(report["two_way"][0]["reason"], "no base for this file")
        self.assertEqual(self.read("project/existing.md"), "the project's own\n")

    def test_nothing_changed_in_the_kit_leaves_the_file_alone(self):
        base = self.write("base/a.md", TEMPLATE_V1)
        theirs = self.write("new/a.md", TEMPLATE_V1)
        local = replace_line(TEMPLATE_V1, 1, "local\n")
        self.write("project/a.md", local)
        report = self.merge([{"path": "project/a.md", "base": base, "theirs": theirs}])
        self.assertEqual(self.read("project/a.md"), local)
        self.assertEqual(len(report["unchanged"]), 1)

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
            handle.write("template at 0.3.0\n")
        with open(os.path.join(self.toolbox, "README.md"), "w") as handle:
            handle.write("not a template\n")
        git(self.toolbox, "add", ".")
        git(self.toolbox, "commit", "-q", "-m", "0.3.0")
        git(self.toolbox, "tag", "-a", "sdd-core-v0.3.0", "-m", "sdd-core 0.3.0")
        with open(os.path.join(self.toolbox, TEMPLATES, "root", "CLAUDE.md"), "w") as handle:
            handle.write("template after 0.3.0\n")
        git(self.toolbox, "commit", "-q", "-am", "later")
        self.url = "file://" + self.toolbox

    def test_the_tag_gives_the_templates_of_that_version(self):
        destination = os.path.join(self.root, "base")
        result = self.run_script("fetch-base", "--version", "0.3.0", "--dest", destination, "--repository", self.url)
        self.assertEqual((result["status"], result["tag"], result["files"]), ("fetched", "sdd-core-v0.3.0", 1))
        self.assertEqual(self.read("base/root/CLAUDE.md"), "template at 0.3.0\n")
        self.assertEqual(sorted(os.listdir(destination)), ["root"])

    def test_a_lightweight_tag_works_too(self):
        git(self.toolbox, "tag", "sdd-core-v0.3.1")
        result = self.run_script("fetch-base", "--version", "0.3.1", "--dest", os.path.join(self.root, "b"), "--repository", self.url)
        self.assertEqual(result["status"], "fetched")
        self.assertEqual(self.read("b/root/CLAUDE.md"), "template after 0.3.0\n")

    def test_a_missing_tag_falls_back(self):
        result = self.run_script(
            "fetch-base", "--version", "0.2.0", "--dest", os.path.join(self.root, "base"), "--repository", self.url, expect=3
        )
        self.assertEqual((result["status"], result["tag"]), ("missing-tag", "sdd-core-v0.2.0"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "base")))

    def test_another_tag_with_the_same_prefix_is_not_taken(self):
        git(self.toolbox, "tag", "sdd-core-v0.3.0-rc1")
        result = self.run_script(
            "fetch-base", "--version", "0.3.0", "--dest", os.path.join(self.root, "base"), "--repository", self.url
        )
        self.assertEqual(self.read("base/root/CLAUDE.md"), "template at 0.3.0\n")
        self.assertEqual(result["status"], "fetched")

    def test_a_tag_without_the_templates_falls_back(self):
        git(self.toolbox, "rm", "-q", "-r", "plugins")
        git(self.toolbox, "commit", "-q", "-m", "no templates")
        git(self.toolbox, "tag", "sdd-core-v0.0.1")
        result = self.run_script(
            "fetch-base", "--version", "0.0.1", "--dest", os.path.join(self.root, "base"), "--repository", self.url, expect=3
        )
        self.assertEqual(result["status"], "missing-tag")

    def test_an_unreachable_repository_falls_back(self):
        result = self.run_script(
            "fetch-base", "--version", "0.3.0", "--dest", os.path.join(self.root, "base"),
            "--repository", "file://" + os.path.join(self.root, "nowhere"), expect=3,
        )
        self.assertEqual(result["status"], "unreachable")

    def test_a_version_that_is_not_x_y_z_is_refused(self):
        self.run_script("fetch-base", "--version", "0.3.0;rm", "--dest", os.path.join(self.root, "base"), "--repository", self.url, expect=2)

    def test_a_non_empty_destination_is_refused(self):
        self.write("base/keep.md", "x\n")
        self.run_script("fetch-base", "--version", "0.3.0", "--dest", os.path.join(self.root, "base"), "--repository", self.url, expect=2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
