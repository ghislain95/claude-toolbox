#!/usr/bin/env python3
"""Tests of merge_conditions.py. Run: python3 .sdd/bin/test_merge_conditions.py (needs git and PyYAML).

Every test builds a throwaway git repository in a temporary directory: `main` is the base branch, the
pull request is a branch cut from it. GitHub is replaced by a stub fed with API fixtures.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.dont_write_bytecode = True  # no __pycache__ left in .sdd/bin/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_conditions as mc  # noqa: E402

GIT_ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_AUTHOR_NAME="test",
    GIT_AUTHOR_EMAIL="test@example.invalid",
    GIT_COMMITTER_NAME="test",
    GIT_COMMITTER_EMAIL="test@example.invalid",
)
os.environ.update({key: GIT_ENV[key] for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")})

TRIGGERS = """\
intent:
  paths:
    - web/src/**
  content:
    - paths: [ 'api/**' ]
      pattern: 'localStorage\\.setItem'
irreversible:
  paths:
    - db/migrations/**
gate_machinery:
  paths:
    - tools/release.sh
"""


def classification(change="add-export", intent=False, irreversible=False, intent_waived=(),
                   irreversible_waived=()):
    def section(gate_open, waived):
        lines = [f"  open: {'true' if gate_open else 'false'}", "  evidence: stated in the proposal"]
        if waived:
            lines.append("  waived:")
            for trigger, reason in waived:
                lines.append(f"    - trigger: '{trigger}'")
                lines.append(f"      reason: {reason}")
        return "\n".join(lines)

    return (f"change: {change}\nintent:\n{section(intent, intent_waived)}\n"
            f"irreversible:\n{section(irreversible, irreversible_waived)}\n")


class Repo:
    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="merge-conditions-")
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.path, *args], env=GIT_ENV, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def write(self, path, content):
        full = os.path.join(self.path, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)

    def remove(self, path):
        self.git("rm", "-q", "--", path)

    def move(self, source, target):
        os.makedirs(os.path.dirname(os.path.join(self.path, target)), exist_ok=True)
        self.git("mv", source, target)

    def commit(self, message="commit"):
        self.git("add", "--all")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def branch(self, name):
        self.git("switch", "-q", "-c", name, "main")

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)


class MatcherTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".sdd/triggers.yaml", TRIGGERS)
        self.repo.write("README.md", "project\n")
        self.repo.write("api/store.js", "localStorage.setItem('v1', data)\n")

    def approve(self, text, change="add-export"):
        self.repo.write(f"openspec/changes/{change}/proposal.md", "# Proposal\n")
        self.repo.write(f"openspec/changes/{change}/{mc.CLASSIFICATION_FILE}", text)

    def pull_request(self, branch="feat/add-export"):
        self.repo.commit("base")
        self.repo.branch(branch)

    def match(self, branch="feat/add-export", tasks="add-export"):
        """Commit the pull request; a change pull request ticks a task of its own change folder."""
        if tasks:
            self.repo.write(f"openspec/changes/{tasks}/tasks.md", "- [x] 1.1 done\n")
        head = self.repo.commit("pull request")
        return mc.match(self.repo.path, "main", head, branch)

    # --- change pull requests -------------------------------------------------------------

    def test_undeclared_migration_is_unaccounted(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("db/migrations/V2__add_column.sql", "alter table t add c int;\n")
        result = self.match()
        self.assertEqual(result["kind"], "change")
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertEqual([(hit["trigger"], hit["file"]) for hit in result["unaccounted"]],
                         [("db/migrations/**", "db/migrations/V2__add_column.sql")])
        self.assertIn("unaccounted irreversible db/migrations/V2__add_column.sql", result["description"])

    def test_declared_gate_is_accounted(self):
        self.approve(classification(irreversible=True))
        self.pull_request()
        self.repo.write("db/migrations/V2__add_column.sql", "alter table t add c int;\n")
        result = self.match()
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertEqual(result["unaccounted"], [])
        self.assertEqual(result["description"], "gates: irreversible")

    def test_waived_intent_path_stays_closed(self):
        self.approve(classification(intent_waived=[("web/src/**", "renames a private helper")]))
        self.pull_request()
        self.repo.write("web/src/helper.ts", "export const x = 1\n")
        result = self.match()
        self.assertEqual(result["gates"], [])
        self.assertEqual(result["unaccounted"], [])
        self.assertEqual([(item["trigger"], item["reason"]) for item in result["waived"]],
                         [("web/src/**", "renames a private helper")])
        self.assertEqual(result["description"], "gates: none")

    def test_waiver_of_another_trigger_does_not_close_the_gate(self):
        self.approve(classification(intent_waived=[("web/**", "not the trigger as written")]))
        self.pull_request()
        self.repo.write("web/src/helper.ts", "export const x = 1\n")
        result = self.match()
        self.assertEqual(result["gates"], ["intent"])
        self.assertEqual(len(result["unaccounted"]), 1)

    def test_gate_machinery_ignores_waivers(self):
        self.approve(classification(irreversible_waived=[(".github/**", "only a comment")]))
        self.pull_request()
        self.repo.write(".github/workflows/ci.yml", "name: CI\n")
        result = self.match()
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertEqual(result["waived"], [])
        self.assertEqual([hit["file"] for hit in result["unaccounted"]], [".github/workflows/ci.yml"])

    def test_built_in_gate_machinery(self):
        # None of these is in TRIGGERS: each changes what CI or the check does.
        for path in (".github/actions/test/action.yml", ".github/CODEOWNERS", ".gitattributes",
                     "web/.gitattributes", ".gitmodules", "openspec/config.yaml", ".sdd/harness.yaml",
                     ".claude/hooks/block.sh", ".claude/settings.json", "vercel.json", "web/vercel.json"):
            with self.subTest(path=path):
                repo = Repo()
                self.addCleanup(repo.cleanup)
                repo.write(".sdd/triggers.yaml", "intent: {}\nirreversible: {}\n")
                repo.write(f"openspec/changes/add-export/{mc.CLASSIFICATION_FILE}", classification())
                repo.commit("base")
                repo.branch("feat/add-export")
                repo.write("openspec/changes/add-export/tasks.md", "- [x] 1.1\n")
                repo.write(path, "x\n")
                result = mc.match(repo.path, "main", repo.commit("pull request"), "feat/add-export")
                self.assertEqual([hit["file"] for hit in result["unaccounted"] if hit.get("machinery")], [path])

    def test_missing_triggers_file_is_an_error_and_keeps_the_default_machinery(self):
        os.remove(os.path.join(self.repo.path, ".sdd/triggers.yaml"))
        self.approve(classification())
        self.pull_request()
        self.repo.write("vercel.json", "{}\n")
        result = self.match()
        self.assertEqual(result["errors"], [".sdd/triggers.yaml missing on the base ref"])
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertEqual(result["hits"][0]["trigger"], "**/vercel.json")

    def test_project_gate_machinery_is_added_to_the_defaults(self):
        self.approve(classification(irreversible_waived=[("tools/release.sh", "typo")]))
        self.pull_request()
        self.repo.write("tools/release.sh", "echo release\n")
        result = self.match()
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertTrue(result["hits"][0]["machinery"])

    def test_classification_edited_in_the_pull_request_is_judged_by_the_base_version(self):
        self.approve(classification())
        self.pull_request()
        # The pull request opens the gate in its own copy: the base version must still be used.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification(irreversible=True))
        self.repo.write("db/migrations/V2__add_column.sql", "alter table t add c int;\n")
        result = self.match()
        self.assertEqual(result["kind"], "change")
        self.assertEqual(result["gates"], ["irreversible"])
        triggers = sorted(hit["trigger"] for hit in result["unaccounted"])
        self.assertEqual(triggers, ["db/migrations/**", mc.CLASSIFICATION_TRIGGER])

    def test_classification_added_by_a_change_pull_request_is_gate_machinery(self):
        # R1: a classification absent from the base ref, added for another change, is an edit too.
        self.approve(classification())
        self.pull_request()
        self.repo.write("openspec/changes/sneaky/classification.yaml",
                        classification("sneaky", irreversible_waived=[("db/migrations/**", "anything")]))
        result = self.match()
        self.assertIn((mc.CLASSIFICATION_TRIGGER, "openspec/changes/sneaky/classification.yaml"),
                      [(hit["trigger"], hit["file"]) for hit in result["hits"]])
        self.assertIn("several change folders touched (add-export, sneaky)", result["errors"])

    def test_classification_added_under_the_archive_is_gate_machinery(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("openspec/changes/archive/2026-01-01-old/classification.yaml", classification("old"))
        result = self.match()
        self.assertEqual(result["kind"], "change")
        self.assertEqual([(hit["trigger"], hit["file"]) for hit in result["unaccounted"]],
                         [(mc.CLASSIFICATION_TRIGGER, "openspec/changes/archive/2026-01-01-old/classification.yaml")])

    def test_classification_deleted_by_a_change_pull_request_is_gate_machinery(self):
        self.approve(classification())
        self.pull_request()
        self.repo.remove("openspec/changes/add-export/classification.yaml")
        result = self.match()
        self.assertEqual([hit["file"] for hit in result["unaccounted"]],
                         ["openspec/changes/add-export/classification.yaml"])

    def test_branch_carrying_the_approved_classification_is_no_edit(self):
        self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.approve(classification())  # same content added on both sides (squashed framing PR)
        self.repo.write("src/app.py", "print(1)\n")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        self.approve(classification())
        self.repo.commit("framing merged")
        result = mc.match(self.repo.path, "main", head, "feat/add-export")
        self.assertEqual(result["kind"], "change")
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["description"], "gates: none")

    def test_triggers_edited_in_the_pull_request_are_ignored(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write(".sdd/triggers.yaml", "intent: {}\nirreversible: {}\n")
        self.repo.write("db/migrations/V2__add_column.sql", "alter table t add c int;\n")
        result = self.match()
        triggers = sorted(hit["trigger"] for hit in result["unaccounted"])
        self.assertEqual(triggers, [".sdd/**", "db/migrations/**"])

    def test_content_pattern_matches_added_lines_only(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("api/store.js", "const unrelated = 1\n")  # removes the matching line
        result = self.match()
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["gates"], [])

    def test_content_pattern_reports_the_added_line(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("api/store.js", "localStorage.setItem('v1', data)\nconst a = 1\n"
                                        "localStorage.setItem('v2', other)\n")
        result = self.match()
        self.assertEqual(result["gates"], ["intent"])
        self.assertEqual([(hit["file"], hit["line"]) for hit in result["hits"]], [("api/store.js", 3)])
        self.assertIn("api/store.js:3", result["description"])

    def test_content_pattern_respects_its_paths(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("scripts/store.js", "localStorage.setItem('v2', other)\n")
        self.repo.write("api/other.js", "const b = 2\n")
        self.assertEqual(self.match()["hits"], [])

    def test_content_pattern_reads_files_gitattributes_hides(self):
        # R2: `-diff` / `binary` on the base ref must not blind the content triggers.
        self.repo.write(".gitattributes", "*.js -diff\napi/*.dat binary\n")
        self.approve(classification())
        self.pull_request()
        self.repo.write("api/new.js", "localStorage.setItem('v2', data)\n")
        self.repo.write("api/blob.dat", "localStorage.setItem('v3', data)\n")
        result = self.match()
        self.assertEqual([(hit["file"], hit["line"]) for hit in result["hits"]],
                         [("api/blob.dat", 1), ("api/new.js", 1)])

    def test_content_pattern_ignores_the_callers_diff_configuration(self):
        # R3: diff.noprefix / diff.mnemonicPrefix in the caller's configuration.
        self.approve(classification())
        self.pull_request()
        self.repo.write("api/new.js", "localStorage.setItem('v2', data)\n")
        head = self.repo.commit("pull request")
        for setting in ("diff.noprefix", "diff.mnemonicPrefix"):
            with self.subTest(setting=setting):
                self.repo.git("config", setting, "true")
                result = mc.match(self.repo.path, "main", head, "feat/add-export")
                self.repo.git("config", "--unset", setting)
                self.assertEqual([hit["file"] for hit in result["hits"]], ["api/new.js"])

    def test_content_pattern_with_unusual_file_names(self):
        # repro2: a backslash is C-quoted in diff headers; `[ab]` is a pathspec pattern unless literal.
        self.approve(classification())
        self.pull_request()
        self.repo.write("api/we\\ird.js", "localStorage.setItem(1)\n")
        self.repo.write("api/[ab].js", "const quiet = 1\n")
        self.repo.write("api/a.js", "localStorage.setItem(2)\n")
        result = self.match()
        self.assertEqual(sorted(hit["file"] for hit in result["hits"]), ["api/a.js", "api/we\\ird.js"])

    def test_invalid_approved_classification_fails(self):
        self.approve("change: add-export\nintent: {open: maybe}\n")
        self.pull_request()
        self.repo.write("src/app.py", "print(1)\n")
        result = self.match()
        self.assertEqual((result["kind"], result["gates"], result["label"]), ("change", ["invalid"], "gates: invalid"))
        self.assertTrue(result["errors"])
        self.assertTrue(result["description"].startswith("gates: invalid - approved classification.yaml"))

    # --- which change a pull request belongs to -------------------------------------------

    def test_branch_name_alone_is_unclassified(self):
        # R4: a hotfix named after an in-flight change, touching no change folder, gets no waiver.
        self.approve(classification(intent_waived=[("web/src/**", "rename")]))
        self.pull_request("fix/add-export")
        self.repo.write("web/src/checkout.tsx", "export const Pay = () => null\n")
        result = self.match("fix/add-export", tasks=None)
        self.assertEqual((result["kind"], result["change"], result["gates"]), ("unclassified", None, ["unclassified"]))
        self.assertEqual(result["waived"], [])

    def test_change_folder_must_match_the_branch(self):
        # repro2: a pull request cannot pick the classification that judges it.
        self.approve(classification("strict", intent=True), change="strict")
        self.approve(classification("permissive", intent_waived=[("web/src/**", "x")]), change="permissive")
        self.pull_request("feat/strict")
        self.repo.write("web/src/page.tsx", "x\n")
        result = self.match("feat/strict", tasks="permissive")
        self.assertEqual((result["kind"], result["change"]), ("unclassified", None))
        self.assertEqual(result["errors"], ["change folder permissive does not match the branch feat/strict"])

    def test_lot_branch_belongs_to_its_change(self):
        # A change delivered in several pull requests: `<type>/<id>/<lot>`.
        self.approve(classification())
        self.pull_request("feat/add-export/merge-route")
        self.repo.write("src/app.py", "print(1)\n")
        result = self.match("feat/add-export/merge-route")
        self.assertEqual((result["kind"], result["change"], result["errors"]), ("change", "add-export", []))

    def test_lot_segment_is_never_read_as_the_change(self):
        # `feat/other/add-export` belongs to `other`, never to `add-export`.
        self.approve(classification())
        self.pull_request("feat/other/add-export")
        self.repo.write("src/app.py", "print(1)\n")
        result = self.match("feat/other/add-export")
        self.assertEqual(result["change"], None)
        self.assertEqual(result["errors"], ["change folder add-export does not match the branch feat/other/add-export"])

    def test_several_change_folders_fail(self):
        self.approve(classification())
        self.approve(classification("other"), change="other")
        self.pull_request()
        self.repo.write("openspec/changes/other/tasks.md", "- [x] 1\n")
        self.repo.write("src/app.py", "print(1)\n")
        result = self.match()
        self.assertEqual(result["change"], None)
        self.assertIn("several change folders touched (add-export, other)", result["errors"])

    # --- framing, archive, unclassified --------------------------------------------------

    def test_framing_pull_request(self):
        self.pull_request("docs/add-export-framing")
        self.approve(classification(intent=True))
        result = self.match("docs/add-export-framing", tasks=None)
        self.assertEqual((result["kind"], result["change"], result["gates"]), ("framing", "add-export", ["framing"]))
        self.assertEqual(result["description"], "gates: framing")

    def test_reclassification_is_a_framing_pull_request(self):
        self.approve(classification())
        self.pull_request("docs/add-export-framing-2")
        self.repo.write("openspec/changes/add-export/classification.yaml", classification(irreversible=True))
        result = self.match("docs/add-export-framing-2", tasks=None)
        self.assertEqual((result["kind"], result["errors"], result["hits"]), ("framing", [], []))

    def test_framing_with_code_is_not_framing(self):
        self.pull_request("docs/add-export-framing")
        self.approve(classification())
        self.repo.write("src/app.py", "print(1)\n")
        self.assertEqual(self.match("docs/add-export-framing", tasks=None)["kind"], "unclassified")

    def test_framing_with_invalid_classification_fails(self):
        self.pull_request("docs/add-export-framing")
        self.approve("change: add-export\n")
        result = self.match("docs/add-export-framing", tasks=None)
        self.assertEqual(result["kind"], "framing")
        self.assertTrue(result["errors"])

    def test_archive_pull_request(self):
        self.approve(classification(intent=True))
        self.pull_request("chore/add-export-archive")
        self.repo.move("openspec/changes/add-export", "openspec/changes/archive/2026-11-13-add-export")
        self.repo.write("openspec/specs/export/spec.md", "# export\n")
        self.repo.write("docs/ROADMAP.md", "- [x] export\n")
        result = self.match("chore/add-export-archive", tasks=None)
        self.assertEqual((result["kind"], result["change"]), ("archive", "add-export"))
        self.assertEqual(result["gates"], [])  # own diff only: the change's open intent gate is not carried
        self.assertEqual(result["hits"], [])

    def test_archive_with_an_edited_classification_opens_the_gate(self):
        self.approve(classification())
        self.pull_request("chore/add-export-archive")
        self.repo.move("openspec/changes/add-export", "openspec/changes/archive/2026-11-13-add-export")
        self.repo.write("openspec/changes/archive/2026-11-13-add-export/classification.yaml",
                        classification(irreversible=True))
        result = self.match("chore/add-export-archive", tasks=None)
        self.assertEqual(result["kind"], "archive")
        self.assertEqual(result["gates"], ["irreversible"])
        self.assertEqual(sorted(hit["file"] for hit in result["unaccounted"]),
                         ["openspec/changes/add-export/classification.yaml",
                          "openspec/changes/archive/2026-11-13-add-export/classification.yaml"])

    def test_archive_with_code_is_a_change(self):
        self.approve(classification())
        self.pull_request("chore/add-export-archive")
        self.repo.move("openspec/changes/add-export", "openspec/changes/archive/2026-11-13-add-export")
        self.repo.write("src/app.py", "print(1)\n")
        self.assertEqual(self.match("chore/add-export-archive", tasks=None)["kind"], "change")

    def test_archive_folder_of_another_change_is_not_an_archive(self):
        # R8: `2026-11-13-add-export` is not an archive folder of `export`.
        for change in ("export", "add-export"):
            self.approve(classification(change), change=change)
        self.pull_request("chore/export-archive")
        self.repo.move("openspec/changes/export", "openspec/changes/archive/2026-11-13-export")
        self.repo.write("openspec/changes/archive/2026-11-13-add-export/proposal.md", "# not this change\n")
        self.assertEqual(self.match("chore/export-archive", tasks=None)["kind"], "change")

    def test_archive_into_a_folder_whose_name_merely_ends_with_the_change_is_not_an_archive(self):
        self.approve(classification("export"), change="export")
        self.pull_request("chore/export-archive")
        self.repo.move("openspec/changes/export", "openspec/changes/archive/2026-11-13-add-export")
        result = self.match("chore/export-archive", tasks=None)
        self.assertEqual(result["kind"], "change")
        self.assertIn("openspec/changes/export/classification.yaml", [hit["file"] for hit in result["unaccounted"]])

    def test_archive_into_two_folders_is_not_an_archive(self):
        self.approve(classification())
        self.pull_request("chore/add-export-archive")
        self.repo.move("openspec/changes/add-export", "openspec/changes/archive/2026-11-13-add-export")
        self.repo.write("openspec/changes/archive/add-export/notes.md", "# a second archive folder\n")
        self.assertEqual(self.match("chore/add-export-archive", tasks=None)["kind"], "change")

    def test_archive_into_the_undated_folder(self):
        self.approve(classification())
        self.pull_request("chore/add-export-archive")
        self.repo.move("openspec/changes/add-export", "openspec/changes/archive/add-export")
        result = self.match("chore/add-export-archive", tasks=None)
        self.assertEqual((result["kind"], result["hits"]), ("archive", []))

    def test_unclassified_pull_request(self):
        self.pull_request("fix/api-typo")
        self.repo.write("api/handler.py", "print(1)\n")
        result = self.match("fix/api-typo", tasks=None)
        self.assertEqual((result["kind"], result["change"], result["gates"]), ("unclassified", None, ["unclassified"]))
        self.assertEqual(result["description"], "gates: unclassified")

    # --- the deploy guard's call ---------------------------------------------------------

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = mc.main(["-C", self.repo.path, *argv])
        return code, (json.loads(output.getvalue()) if output.getvalue() else None)

    def merged(self, branch="feat/add-export"):
        """Merge the pull request into main; (first parent of the merge commit, pull request head)."""
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1.1 done\n")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge", branch)
        return self.repo.git("rev-parse", "HEAD^1"), head

    def test_match_after_the_merge_judges_the_merged_pull_request(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("src/app.py", "print(1)\n")
        base, head = self.merged()
        code, result = self.run_main("match", "--base", base, "--head", head, "--branch", "feat/add-export")
        self.assertEqual((code, result["kind"], result["base"], result["gates"]), (0, "change", base, []))

    def test_match_exits_non_zero_on_an_unaccounted_hit(self):
        self.approve(classification())
        self.pull_request()
        self.repo.write("db/migrations/V2__add_column.sql", "alter table t add c int;\n")
        base, head = self.merged()
        code, result = self.run_main("match", "--base", base, "--head", head, "--branch", "feat/add-export")
        self.assertEqual((code, result["gates"]), (1, ["irreversible"]))

    def test_match_exits_non_zero_on_an_invalid_classification(self):
        self.approve("change: add-export\n")
        self.pull_request()
        self.repo.write("src/app.py", "print(1)\n")
        base, head = self.merged()
        code, result = self.run_main("match", "--base", base, "--head", head, "--branch", "feat/add-export")
        self.assertEqual((code, result["label"]), (1, "gates: invalid"))

    def test_match_exits_2_when_it_cannot_judge(self):
        self.repo.commit("base")
        code, result = self.run_main("match", "--base", "main", "--head", "0" * 40, "--branch", "feat/x")
        self.assertEqual((code, result), (2, None))


class SchemaTest(unittest.TestCase):
    def test_triggers_errors(self):
        _, errors = mc.load_triggers("intent:\n  paths: [ 3 ]\n  content:\n    - pattern: '('\nextra: 1\n")
        self.assertEqual(len(errors), 3, errors)

    def test_classification_requires_evidence(self):
        text = "change: x\nintent: {open: false}\nirreversible: {open: false, evidence: none}\n"
        result, errors = mc.load_classification(text, "x")
        self.assertIsNone(result)
        self.assertEqual(errors, ["classification.yaml: intent.evidence: expected the reason for the answer"])

    def test_classification_change_must_match_its_folder(self):
        _, errors = mc.load_classification(classification("x"), "y")
        self.assertEqual(len(errors), 1)


class GlobTest(unittest.TestCase):
    def test_github_path_filter_syntax(self):
        cases = [
            ("docs/*", "docs/a.md", True), ("docs/*", "docs/a/b.md", False),
            ("docs/**", "docs/a/b.md", True), ("**/README.md", "README.md", True),
            ("**/README.md", "a/b/README.md", True), ("*.md", "a/b.md", False),
            ("**.js", "src/js/app.js", True), ("*.jsx?", "page.js", True), ("*.jsx?", "page.jsx", True),
            ("db/V[0-9]*.sql", "db/V2__x.sql", True), ("db/V[0-9]*.sql", "db/Vx.sql", False),
        ]
        for pattern, path, expected in cases:
            self.assertEqual(mc.glob_match(pattern, path), expected, (pattern, path))

    def test_double_star_crosses_a_newline(self):
        # R3b: a file name holding a newline must still match `**`.
        self.assertTrue(mc.glob_match("db/migrations/**", "db/migrations/a\nb.sql"))
        self.assertTrue(mc.glob_match(".github/**", ".github/workflows/a\n.yml"))

    def test_negation_order(self):
        self.assertFalse(mc.filter_includes(["docs/**", "!docs/**/*.md"], "docs/a.md"))
        self.assertTrue(mc.filter_includes(["docs/**", "!docs/**/*.md", "docs/keep.md"], "docs/keep.md"))


# --- check -------------------------------------------------------------------------------------

WORKFLOWS = {
    "always.yml": "name: Always\non: [pull_request]\njobs: {}\n",
    "web.yml": "name: Web\non:\n  pull_request:\n    paths: [ 'web/**' ]\njobs: {}\n",
    "not-docs.yml": "name: NotDocs\non:\n  pull_request:\n    paths-ignore: [ 'docs/**' ]\njobs: {}\n",
    "deploy.yml": "name: Deploy\non:\n  push:\n    branches: [ main ]\njobs: {}\n",
    "release-branch.yml": "name: Release\non:\n  pull_request:\n    branches: [ 'release/**' ]\njobs: {}\n",
    "not-main.yml": "name: NotMain\non:\n  pull_request:\n    branches-ignore: [ 'main' ]\njobs: {}\n",
    "labels-only.yml": "name: Labels\non:\n  pull_request:\n    types: [ labeled ]\njobs: {}\n",
    "nested/inner.yml": "name: Inner\non: [pull_request]\njobs: {}\n",  # not a workflow: GitHub ignores subfolders
    "merge-conditions.yml": "name: Merge conditions\non: pull_request_target\njobs: {}\n",
}
GREEN = {"review-harness": "success", "opsx-verify": "success"}


def quiet(message):
    pass


def pull_request(number, sha, branch="feat/add-export", base="main", state="open"):
    return {"number": number, "state": state, "head": {"sha": sha, "ref": branch}, "base": {"ref": base}}


class StubGitHub:
    """GitHub's REST API as `check` uses it, with its pagination (30 items when per_page is absent)."""

    def __init__(self, pulls, runs=(), statuses=None, moves=None):
        self.pulls, self.runs, self.statuses, self.posted = pulls, list(runs), dict(statuses or {}), []
        self.moves = moves or {}  # number: (reads after which the head moves, new head sha)
        self.reads = {}

    @staticmethod
    def page(items, params):
        size, page = int(params.get("per_page", 30)), int(params.get("page", 1))
        return items[(page - 1) * size:page * size]

    def get(self, path):
        route, _, query = path.partition("?")
        params = dict(item.split("=", 1) for item in query.split("&") if item)
        single = re.fullmatch(r"repos/[^/]+/[^/]+/pulls/(\d+)", route)
        if single:
            number = int(single.group(1))
            pull = next(pull for pull in self.pulls if pull["number"] == number)
            self.reads[number] = self.reads.get(number, 0) + 1
            after, sha = self.moves.get(number, (None, None))
            if after is not None and self.reads[number] > after:
                return dict(pull, head=dict(pull["head"], sha=sha))
            return pull
        if route.endswith("/pulls"):
            pulls = self.pulls
            if "state" in params:
                pulls = [pull for pull in pulls
                         if pull["state"] == params["state"] and pull["base"]["ref"] == params.get("base")]
            return self.page(pulls, params)
        if route.endswith("/actions/runs"):
            return {"total_count": len(self.runs), "workflow_runs": self.page(self.runs, params)}
        if route.endswith("/status"):
            statuses = [{"context": key, "state": value} for key, value in self.statuses.items()]
            return {"total_count": len(statuses), "statuses": self.page(statuses, params)}
        raise AssertionError(f"unexpected API call {path}")

    def post_status(self, repo, sha, state, description, target_url=None):
        self.posted.append((repo, sha, state, description))


def run(name, sha, status="completed", conclusion="success", run_id=1, event="pull_request"):
    return {"id": run_id, "path": f".github/workflows/{name}", "event": event,
            "status": status, "conclusion": conclusion, "head_sha": sha}


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".sdd/triggers.yaml", TRIGGERS)
        for name, content in WORKFLOWS.items():
            self.repo.write(f".github/workflows/{name}", content)
        self.repo.write("README.md", "project\n")

    def head(self, files, branch="feat/add-export", classified=True, removed=()):
        """Commit the base, then the pull request; a change pull request ticks one of its tasks."""
        if classified:
            self.repo.write("openspec/changes/add-export/proposal.md", "# Proposal\n")
            self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        self.repo.commit("base")
        self.repo.branch(branch)
        if branch == "feat/add-export":
            self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1.1\n")
        for path, content in files.items():
            self.repo.write(path, content)
        for path in removed:
            self.repo.remove(path)
        return self.repo.commit("pull request")

    def base7(self):
        return self.repo.git("rev-parse", "main")[:7]

    def judge(self, sha, branch="feat/add-export", runs=(), statuses=None):
        stub = StubGitHub([pull_request(7, sha, branch)], runs, statuses)
        outcome = mc.check(stub, self.repo.path, "acme/app", "main", pr=7, sha=sha, base_ref="main", fetch=False,
                           log=quiet)
        self.assertEqual(len(stub.posted), 1)
        self.assertEqual(stub.posted[0][:4], ("acme/app", sha, outcome[0]["state"], outcome[0]["description"]))
        return outcome[0]

    def green_runs(self, sha):
        return [run("always.yml", sha), run("not-docs.yml", sha, run_id=2)]

    # --- required workflows ------------------------------------------------------------------

    def test_required_workflows_follow_the_path_filters(self):
        sha = self.head({"src/app.py": "print(1)\n"})
        files = mc.match(self.repo.path, "main", sha, "feat/add-export")["files"]
        required = mc.required_workflows(self.repo.path, "main", files, "main")
        self.assertEqual(required, [".github/workflows/always.yml", ".github/workflows/not-docs.yml"])
        required = mc.required_workflows(self.repo.path, "main", ["web/a.ts"], "main")
        self.assertEqual(required, [".github/workflows/always.yml", ".github/workflows/not-docs.yml",
                                    ".github/workflows/web.yml"])
        required = mc.required_workflows(self.repo.path, "main", ["docs/a.md"], "main")
        self.assertEqual(required, [".github/workflows/always.yml"])
        required = mc.required_workflows(self.repo.path, "main", ["docs/a.md"], "release/1")
        self.assertEqual(required, [".github/workflows/always.yml", ".github/workflows/not-main.yml",
                                    ".github/workflows/release-branch.yml"])

    def test_unreadable_workflow_is_required(self):
        self.repo.write(".github/workflows/broken.yml", "on: [ pull_request\n")
        self.repo.commit("base")
        required = mc.required_workflows(self.repo.path, "main", ["docs/a.md"], "main")
        self.assertEqual(required, [".github/workflows/always.yml", ".github/workflows/broken.yml"])

    def test_pull_request_outside_every_filter_is_still_judged(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=self.green_runs(sha), statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]), ("success", f"gates: none; base {self.base7()}"))

    def test_running_workflow_is_pending(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha, status="in_progress", conclusion=None),
                                        run("not-docs.yml", sha, run_id=2)], statuses=GREEN)
        self.assertEqual(outcome["state"], "pending")
        self.assertEqual(outcome["description"], f"gates: none - always running; base {self.base7()}")

    def test_failed_workflow_is_a_failure_even_when_another_is_pending(self):
        sha = self.head({"src/app.py": "print(1)\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha, conclusion="failure"),
                                        run("not-docs.yml", sha, status="queued", conclusion=None, run_id=2)],
                             statuses=GREEN)
        self.assertEqual(outcome["state"], "failure")
        self.assertTrue(outcome["description"].startswith("gates: none - always failure; not-docs running"))

    def test_workflow_whose_jobs_were_all_skipped_counts_as_run(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha, conclusion="skipped"),
                                        run("not-docs.yml", sha, run_id=2, conclusion="neutral")], statuses=GREEN)
        self.assertEqual(outcome["state"], "success")

    def test_latest_run_of_a_workflow_wins(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha, conclusion="failure", run_id=1),
                                        run("always.yml", sha, run_id=3), run("not-docs.yml", sha, run_id=2)],
                             statuses=GREEN)
        self.assertEqual(outcome["state"], "success")

    def test_run_of_another_commit_does_not_count(self):
        sha = self.head({"docs/a.md": "x\n"})
        for other in ("0" * 40, None):
            with self.subTest(head_sha=other):
                runs = [run("always.yml", other, run_id=5), run("not-docs.yml", sha, run_id=2)]
                outcome = self.judge(sha, runs=runs, statuses=GREEN)
                self.assertEqual(outcome["state"], "pending")
                self.assertIn("no run of always", outcome["description"])

    def test_run_of_another_event_does_not_count(self):
        sha = self.head({"docs/a.md": "x\n"})
        runs = [run("always.yml", sha, event="push", run_id=5), run("not-docs.yml", sha, run_id=2)]
        outcome = self.judge(sha, runs=runs, statuses=GREEN)
        self.assertEqual(outcome["state"], "pending")
        self.assertIn("no run of always", outcome["description"])

    def test_runs_and_statuses_are_read_past_the_first_page(self):
        sha = self.head({"docs/a.md": "x\n"})
        noise = [run("lint.yml", sha, run_id=100 + index) for index in range(150)]
        statuses = {f"ci/{index}": "success" for index in range(120)}
        statuses.update(GREEN)
        outcome = self.judge(sha, runs=noise + self.green_runs(sha), statuses=statuses)
        self.assertEqual(outcome["state"], "success")

    # --- review statuses --------------------------------------------------------------------

    def test_missing_review_harness_status_is_not_green(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=self.green_runs(sha), statuses={"opsx-verify": "success"})
        self.assertEqual(outcome["state"], "pending")
        self.assertIn("no review-harness status", outcome["description"])

    def test_pending_review_harness_status_is_pending(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=self.green_runs(sha),
                             statuses={"review-harness": "pending", "opsx-verify": "success"})
        self.assertEqual(outcome["description"], f"gates: none - review-harness pending; base {self.base7()}")
        self.assertEqual(outcome["state"], "pending")

    def test_failed_review_harness_status_is_a_failure(self):
        sha = self.head({"docs/a.md": "x\n"})
        outcome = self.judge(sha, runs=self.green_runs(sha),
                             statuses={"review-harness": "failure", "opsx-verify": "success"})
        self.assertEqual(outcome["state"], "failure")

    def test_unclassified_needs_no_review_status_and_reports_its_gate(self):
        sha = self.head({"docs/a.md": "x\n"}, branch="fix/typo", classified=False)
        outcome = self.judge(sha, branch="fix/typo", runs=[run("always.yml", sha)])
        self.assertEqual((outcome["state"], outcome["description"]),
                         ("success", f"gates: unclassified; base {self.base7()}"))

    def test_owner_merged_gate_is_success_with_its_gate(self):
        self.repo.write("openspec/changes/add-export/proposal.md", "# Proposal\n")
        self.repo.write("openspec/changes/add-export/classification.yaml", classification(intent=True))
        sha = self.head({"web/src/page.ts": "x\n"}, classified=False)
        outcome = self.judge(sha, runs=self.green_runs(sha) + [run("web.yml", sha, run_id=3)], statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]), ("success", f"gates: intent; base {self.base7()}"))

    def test_description_fits_in_a_commit_status_and_keeps_the_base(self):
        files = {f"db/migrations/V{index}__a_rather_long_migration_name.sql": "x\n" for index in range(2, 12)}
        sha = self.head(files)
        outcome = self.judge(sha, runs=[])
        self.assertEqual(outcome["state"], "failure")
        self.assertLessEqual(len(outcome["description"]), mc.DESCRIPTION_MAX)
        self.assertTrue(outcome["description"].startswith("gates: irreversible - unaccounted irreversible"))
        self.assertTrue(outcome["description"].endswith(f"...; base {self.base7()}"))

    # --- workflows the pull request edits ---------------------------------------------------

    def gated_head(self, files, removed=()):
        """A change pull request whose classification opens the irreversible gate (gate machinery)."""
        self.repo.write("openspec/changes/add-export/proposal.md", "# Proposal\n")
        self.repo.write("openspec/changes/add-export/classification.yaml", classification(irreversible=True))
        return self.head(files, classified=False, removed=removed)

    def test_required_workflow_deleted_by_the_pull_request_is_its_own_reason(self):
        sha = self.gated_head({"src/app.py": "print(1)\n"}, removed=[".github/workflows/not-docs.yml"])
        outcome = self.judge(sha, runs=[run("always.yml", sha)], statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]),
                         ("failure", f"gates: irreversible - not-docs deleted by the pull request; base {self.base7()}"))

    def test_required_workflow_filtered_out_by_the_pull_request_is_its_own_reason(self):
        sha = self.gated_head({"src/app.py": "print(1)\n",
                               ".github/workflows/not-docs.yml": "name: NotDocs\non:\n  pull_request:\n"
                                                                 "    paths: [ 'nothing/**' ]\njobs: {}\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha)], statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]),
                         ("failure", f"gates: irreversible - not-docs no longer runs on the pull request; "
                                     f"base {self.base7()}"))

    def test_required_workflow_edited_but_still_running_is_awaited(self):
        sha = self.gated_head({"src/app.py": "print(1)\n",
                               ".github/workflows/not-docs.yml": "name: NotDocs2\non: [pull_request]\njobs: {}\n"})
        outcome = self.judge(sha, runs=[run("always.yml", sha)], statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]),
                         ("pending", f"gates: irreversible - no run of not-docs; base {self.base7()}"))

    def test_workflow_added_by_the_pull_request_is_its_own_reason(self):
        sha = self.gated_head({"src/app.py": "print(1)\n",
                               ".github/workflows/new.yml": "name: New\non: [pull_request]\njobs: {}\n",
                               ".github/workflows/helpers/data.yml": "not: a workflow\n"})
        outcome = self.judge(sha, runs=self.green_runs(sha), statuses=GREEN)
        self.assertEqual((outcome["state"], outcome["description"]),
                         ("failure", f"gates: irreversible - new added by the pull request; base {self.base7()}"))

    # --- which pull requests are judged, and when the status is posted ----------------------

    def test_check_by_sha_judges_only_the_matching_open_pull_request(self):
        sha = self.head({"docs/a.md": "x\n"})
        pulls = [pull_request(7, sha), pull_request(8, "0" * 40, "other"),
                 pull_request(9, sha, "x", base="release"), pull_request(10, sha, state="closed")]
        stub = StubGitHub(pulls, self.green_runs(sha), GREEN)
        outcomes = mc.check(stub, self.repo.path, "acme/app", "main", sha=sha, base_ref="main", fetch=False,
                            log=quiet)
        self.assertEqual([outcome["number"] for outcome in outcomes], [7])
        self.assertEqual([posted[2] for posted in stub.posted], ["success"])

    def test_closed_pull_request_is_not_judged(self):
        sha = self.head({"docs/a.md": "x\n"})
        stub = StubGitHub([pull_request(7, sha, state="closed")], self.green_runs(sha), GREEN)
        outcomes = mc.check(stub, self.repo.path, "acme/app", "main", sha=sha, base_ref="main", fetch=False,
                            log=quiet)
        self.assertEqual((outcomes, stub.posted), ([], []))

    def test_event_head_that_is_no_longer_the_head_is_not_judged(self):
        sha = self.head({"docs/a.md": "x\n"})
        stub = StubGitHub([pull_request(7, "1" * 40)], self.green_runs(sha), GREEN)
        outcomes = mc.check(stub, self.repo.path, "acme/app", "main", pr=7, sha=sha, base_ref="main", fetch=False,
                            log=quiet)
        self.assertEqual((outcomes, stub.posted), ([], []))

    def test_head_moved_while_judging_is_not_posted(self):
        sha = self.head({"docs/a.md": "x\n"})
        stub = StubGitHub([pull_request(7, sha)], self.green_runs(sha), GREEN, moves={7: (1, "1" * 40)})
        outcomes = mc.check(stub, self.repo.path, "acme/app", "main", pr=7, sha=sha, base_ref="main", fetch=False,
                            log=quiet)
        self.assertEqual(([outcome["posted"] for outcome in outcomes], stub.posted), ([False], []))

    def test_push_to_main_re_judges_every_open_pull_request(self):
        first = self.head({"docs/a.md": "x\n"})
        self.repo.git("switch", "-q", "main")
        self.repo.branch("fix/typo")
        self.repo.write("docs/b.md", "y\n")
        second = self.repo.commit("second pull request")
        pulls = [pull_request(7, first), pull_request(8, second, "fix/typo"),
                 pull_request(9, second, "x", base="release"), pull_request(10, first, state="closed")]
        stub = StubGitHub(pulls, self.green_runs(first) + [run("always.yml", second, run_id=4)], GREEN)
        outcomes = mc.check(stub, self.repo.path, "acme/app", "main", all_open=True, base_ref="main", fetch=False,
                            log=quiet)
        base7 = self.base7()
        self.assertEqual([outcome["number"] for outcome in outcomes], [7, 8])
        self.assertEqual([posted[1:] for posted in stub.posted], [
            (first, "pending", f"re-judging: main moved to {base7}"),
            (second, "pending", f"re-judging: main moved to {base7}"),
            (first, "success", f"gates: none; base {base7}"),
            (second, "success", f"gates: unclassified; base {base7}"),
        ])

    def test_crash_posts_an_error(self):
        self.repo.commit("base")
        stub = StubGitHub([pull_request(7, "f" * 40, "feat/x")])
        outcome = mc.check(stub, self.repo.path, "acme/app", "main", pr=7, base_ref="main", fetch=False, log=quiet)
        self.assertEqual(outcome[0]["state"], "error")
        self.assertEqual(stub.posted[0][2], "error")


def revert_file(merge_commits, change="add-export", reason="the export probe returned 500"):
    commits = [merge_commits] if isinstance(merge_commits, str) else list(merge_commits)
    return f"revert_of: {change}\nmerge_commits: [ {', '.join(commits)} ]\nreason: {reason}\n"


class LookupStub:
    """PullLookup's answer: the merged pull requests of a commit, from {sha: [pull]}."""

    def __init__(self, pulls=None):
        self.pulls = pulls or {}

    def merged_as(self, sha):
        return self.pulls.get(sha, [])


def change_pull(number, merge_sha, branch="feat/add-export", labels=()):
    return {"number": number, "merged_at": "2026-11-13T10:00:00Z", "merge_commit_sha": merge_sha,
            "base": {"ref": "main"}, "head": {"sha": "f" * 40, "ref": branch},
            "labels": [{"name": label} for label in labels]}


class RevertFixture:
    """A repository where change add-export is approved, merged, then reverted."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".sdd/triggers.yaml", TRIGGERS)
        self.repo.write("src/app.py", "print(1)\n")
        self.repo.write("src/tool.sh", "echo tool\n")
        self.repo.write("openspec/changes/add-export/proposal.md", "# Proposal\n")

    def merged_change(self, files, classification_text=None, removed=(), method="squash", modes=(),
                      branch="feat/add-export", base=True):
        """Approve, branch, change, merge into main; returns the merge commit."""
        if base:
            self.repo.write("openspec/changes/add-export/classification.yaml", classification_text or classification())
            self.repo.commit("base")
        self.repo.git("switch", "-q", "-c", branch, "main")
        lot = branch.split("/")[2] if branch.count("/") > 1 else None
        self.repo.write(f"openspec/changes/add-export/{lot or 'tasks'}.md", f"- [x] {branch}\n")
        for path, content in files.items():
            self.repo.write(path, content)
        for path in removed:
            self.repo.remove(path)
        for path in modes:
            os.chmod(os.path.join(self.repo.path, path), 0o755)
        self.repo.git("add", "--all")
        self.repo.git("commit", "-q", "-m", "change")
        self.repo.git("switch", "-q", "main")
        if method == "squash":
            self.repo.git("merge", "-q", "--squash", branch)
            self.repo.git("commit", "-q", "-m", "feat(add-export): squashed (#7)")
        else:
            self.repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #7", branch)
        return self.repo.git("rev-parse", "HEAD")

    def revert(self, merged, branch="revert/add-export", mainline=False, edit=None, text=None, lookup=None,
               commits=None):
        self.repo.git("switch", "-q", "-c", branch, "main")
        for commit in reversed(commits or [merged]):
            self.repo.git("revert", "--no-edit", *(["-m", "1"] if mainline else []), commit)
        if edit:
            edit()
        self.repo.write("openspec/changes/add-export/revert.yaml", text or revert_file(commits or merged))
        head = self.repo.commit("revert")
        return mc.match(self.repo.path, "main", head, branch, lookup)


class RevertTest(RevertFixture, unittest.TestCase):
    """A revert pull request: `revert/<id>`, `revert.yaml`, the exact inverse of the merged change."""

    def test_exact_inverse_of_a_squash_merge_opens_no_gate(self):
        merged = self.merged_change({"src/app.py": "print(2)\n", "src/new.py": "x = 1\n"}, removed=["src/tool.sh"])
        result = self.revert(merged)
        self.assertEqual((result["kind"], result["change"], result["errors"]), ("revert", "add-export", []))
        self.assertEqual((result["gates"], result["unaccounted"], result["description"]), ([], [], "gates: none"))

    def test_exact_inverse_of_a_merge_commit(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"}, method="merge")
        result = self.revert(merged, mainline=True)
        self.assertEqual((result["kind"], result["errors"], result["gates"]), ("revert", [], []))

    def test_modified_revert_is_rejected(self):
        merged = self.merged_change({"src/app.py": "print(2)\n", "src/new.py": "x = 1\n"})
        result = self.revert(merged, edit=lambda: self.repo.write("src/app.py", "print(1)  # restored\n"))
        self.assertEqual(result["kind"], "revert")
        self.assertEqual(result["errors"], [f"not the exact inverse of {merged[:7]}: src/app.py"])
        self.assertTrue(result["description"].startswith("gates: none - not the exact inverse"))

    def test_revert_with_an_extra_file_is_rejected(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        result = self.revert(merged, edit=lambda: self.repo.write("src/other.py", "y = 2\n"))
        self.assertEqual(result["errors"], [f"not the exact inverse of {merged[:7]}: src/other.py"])

    def test_partial_revert_is_rejected(self):
        merged = self.merged_change({"src/app.py": "print(2)\n", "src/new.py": "x = 1\n"})
        result = self.revert(merged, edit=lambda: self.repo.write("src/new.py", "x = 1\n"))
        self.assertEqual(result["errors"], [f"not the exact inverse of {merged[:7]}: src/new.py"])

    def test_mode_left_changed_is_not_an_exact_inverse(self):
        merged = self.merged_change({}, modes=["src/tool.sh"])
        self.repo.git("switch", "-q", "-c", "revert/add-export", "main")
        self.repo.git("revert", "--no-edit", merged)
        os.chmod(os.path.join(self.repo.path, "src/tool.sh"), 0o755)  # the content goes back, the mode does not
        self.repo.write("openspec/changes/add-export/revert.yaml", revert_file(merged))
        head = self.repo.commit("revert")
        result = mc.match(self.repo.path, "main", head, "revert/add-export")
        self.assertEqual(result["errors"], [f"not the exact inverse of {merged[:7]}: src/tool.sh"])

    def test_revert_from_another_branch_is_rejected(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        result = self.revert(merged, branch="fix/add-export")
        self.assertEqual(result["errors"], ["a revert of add-export comes from the branch revert/add-export, not fix/add-export"])

    def test_merge_commit_must_be_on_the_base_ref(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        self.repo.git("switch", "-q", "-c", "elsewhere", "main")
        self.repo.write("src/app.py", "print(3)\n")
        elsewhere = self.repo.commit("not on main")
        self.repo.git("switch", "-q", "main")
        result = self.revert(merged, text=revert_file(elsewhere))
        self.assertIn(f"revert of add-export: {elsewhere[:7]} is not a merge on the base ref's first-parent line",
                      result["errors"])

    def test_commit_inside_a_merged_branch_is_not_a_merge_of_the_first_parent_line(self):
        # R5: a commit of the merged branch, reachable from main but not on its first-parent line.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] a\n")
        inner = self.repo.commit("lot a")
        self.repo.write("src/b.py", "2\n")
        self.repo.commit("lot b")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge #7", "feat/add-export")
        result = self.revert(inner, text=revert_file(inner))
        self.assertIn(f"revert of add-export: {inner[:7]} is not a merge on the base ref's first-parent line",
                      result["errors"])

    def test_merge_commit_must_be_a_merge_of_the_change(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        self.repo.write("src/other.py", "z = 3\n")
        other = self.repo.commit("unrelated commit on main")
        result = self.revert(merged, text=revert_file(other))
        self.assertIn(f"revert of add-export: {other[:7]} did not change openspec/changes/add-export/", result["errors"])

    def test_the_newest_merge_of_the_change_must_be_reverted(self):
        first = self.merged_change({"src/app.py": "print(2)\n"}, branch="feat/add-export/a")
        second = self.merged_change({"src/b.py": "b\n"}, branch="feat/add-export/b", base=False)
        result = self.revert(first, text=revert_file(first), commits=[first])
        self.assertIn(f"revert of add-export: the newest merge of the change, {second[:7]}, is not reverted",
                      result["errors"])

    def test_several_lots_are_reverted_together(self):
        first = self.merged_change({"src/app.py": "print(2)\n", "src/new.py": "1\n"}, branch="feat/add-export/a")
        second = self.merged_change({"src/app.py": "print(3)\n"}, branch="feat/add-export/b", base=False)
        result = self.revert(second, commits=[first, second])
        self.assertEqual((result["kind"], result["errors"], result["gates"]), ("revert", [], []))
        lone = self.merged_change({"src/c.py": "c\n"}, branch="feat/add-export/c", base=False)
        self.repo.git("branch", "-q", "-D", "revert/add-export")
        partial = self.revert(lone, branch="revert/add-export", commits=[lone],
                              edit=lambda: self.repo.write("src/app.py", "print(1)\n"))
        self.assertEqual(partial["errors"], [f"not the exact inverse of {lone[:7]}: src/app.py"])

    def test_listed_merges_must_be_pull_requests_of_the_change(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        lookup = LookupStub({merged: [change_pull(7, merged, branch="feat/other-change")]})
        result = self.revert(merged, lookup=lookup)
        self.assertEqual(result["errors"], [f"revert of add-export: {merged[:7]} is not the merge of a pull request "
                                            f"of the change"])
        for branch in ("feat/add-export", "feat/add-export/lot-2"):
            with self.subTest(branch=branch):
                self.repo.git("switch", "-q", "main")
                self.repo.git("branch", "-q", "-D", "revert/add-export")
                lookup = LookupStub({merged: [change_pull(7, merged, branch=branch)]})
                self.assertEqual(self.revert(merged, lookup=lookup)["errors"], [])

    def test_invalid_revert_file_is_rejected(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        result = self.revert(merged, text=f"revert_of: add-export\nmerge_commit: {merged}\n")
        self.assertEqual(result["kind"], "revert")
        self.assertEqual(result["errors"], [
            "revert.yaml: unknown key 'merge_commit'",
            "revert.yaml: merge_commits: expected the full shas of the reverted merges, one per lot",
            "revert.yaml: reason: expected the diagnosis of the failed verification"])
        for text, expected in (("revert_of: add-export\nmerge_commits: [ 'abc1234' ]\nreason: r\n",
                                "revert.yaml: merge_commits: expected the full shas of the reverted merges, one per lot"),
                               (f"revert_of: add-export\nmerge_commits: [ {merged}, {merged} ]\nreason: r\n",
                                "revert.yaml: merge_commits: a merge is listed twice")):
            with self.subTest(text=text):
                self.assertEqual(mc.load_revert(text, "add-export")[1], [expected])

    def test_revert_of_an_irreversible_change_opens_the_irreversible_gate(self):
        merged = self.merged_change({"db/migrations/V2__a.sql": "alter table t add c int;\n"},
                                    classification(irreversible=True))
        result = self.revert(merged)
        self.assertEqual((result["errors"], result["gates"], result["unaccounted"]), ([], ["irreversible"], []))

    def test_revert_touching_gate_machinery_opens_the_irreversible_gate(self):
        merged = self.merged_change({"tools/release.sh": "echo release\n"})
        result = self.revert(merged)
        self.assertEqual((result["errors"], result["gates"]), ([], ["irreversible"]))
        self.assertTrue(any(hit.get("machinery") for hit in result["hits"]))

    def test_revert_of_the_intent_change_in_flight_opens_no_gate(self):
        merged = self.merged_change({"web/src/page.ts": "x\n"}, classification(intent=True))
        lookup = LookupStub({merged: [change_pull(7, merged, labels=("in-flight",))]})
        result = self.revert(merged, lookup=lookup)
        self.assertEqual((result["errors"], result["gates"], result["unaccounted"]), ([], [], []))

    def test_revert_of_an_intent_change_not_in_flight_opens_the_intent_gate(self):
        # R5: undoing behaviour the owner approved and that passed its verification is the owner's call.
        merged = self.merged_change({"web/src/page.ts": "x\n"}, classification(intent=True))
        for lookup in (None, LookupStub({merged: [change_pull(7, merged)]})):
            with self.subTest(lookup=lookup):
                result = self.revert(merged, lookup=lookup)
                self.assertEqual((result["errors"], result["gates"]), ([], ["intent"]))
                self.repo.git("switch", "-q", "main")
                self.repo.git("branch", "-q", "-D", "revert/add-export")

    def test_revert_needs_the_approved_classification(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        self.repo.git("switch", "-q", "-c", "chore/drop", "main")
        self.repo.remove("openspec/changes/add-export/classification.yaml")
        dropped = self.repo.commit("drop the classification")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--ff-only", dropped)
        result = self.revert(merged)
        self.assertEqual(result["gates"], ["invalid"])
        self.assertIn("revert of add-export: no approved classification on the base ref", result["errors"])

    def test_editing_an_existing_revert_file_is_no_revert(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        self.revert(merged)
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--ff-only", "revert/add-export")
        self.repo.git("switch", "-q", "-c", "fix/add-export", "main")
        self.repo.write("openspec/changes/add-export/revert.yaml", revert_file(merged, reason="a better diagnosis"))
        self.repo.write("src/app.py", "print(4)\n")
        result = mc.match(self.repo.path, "main", self.repo.commit("fix"), "fix/add-export")
        self.assertEqual((result["kind"], result["errors"]), ("change", []))

    def test_revert_needs_no_review_status(self):
        merged = self.merged_change({"src/app.py": "print(2)\n"})
        result = self.revert(merged)
        self.assertEqual(mc.evaluate(result, [], [], {})[0], "success")


class CheckRevertTest(RevertFixture, unittest.TestCase):
    """`check` ties a revert to the pull requests it reverts (the in-flight label closes the intent gate)."""

    def test_check_reads_the_reverted_pull_requests(self):
        merged = self.merged_change({"web/src/page.ts": "x\n"}, classification(intent=True))
        self.revert(merged)
        head = self.repo.git("rev-parse", "HEAD")
        change = dict(change_pull(7, merged, labels=("in-flight",)), state="closed")
        revert_pull = pull_request(8, head, "revert/add-export")
        stub = StubGitHub([revert_pull, change])
        outcome = mc.check(stub, self.repo.path, "acme/app", "main", pr=8, sha=head, base_ref="main", fetch=False,
                           log=quiet)
        self.assertEqual(outcome[0]["description"], f"gates: none; base {self.repo.git('rev-parse', 'main')[:7]}")
        change["labels"] = []
        outcome = mc.check(stub, self.repo.path, "acme/app", "main", pr=8, sha=head, base_ref="main", fetch=False,
                           log=quiet)
        self.assertTrue(outcome[0]["description"].startswith("gates: intent;"), outcome)


GUARD_WORKFLOWS = {name: WORKFLOWS[name] for name in ("always.yml", "not-docs.yml", "web.yml", "deploy.yml")}


class GuardStub:
    """GitHub's REST API as the deploy guard reads it, strict about the queries it accepts and
    paginated like GitHub. A pull request is listed for the commits in its `_commits` (its merge
    commit by default). `activity` is a list of answers, one per call (the last one repeats)."""

    PAGED = {"per_page", "page"}

    def __init__(self, pulls=(), runs=(), activity=(), default_branch="main", fail=None, activities=None):
        self.pulls, self.runs = list(pulls), list(runs)
        self.activities = activities if activities is not None else [list(activity)]
        self.default_branch, self.fail, self.calls = default_branch, fail, []

    def get(self, path):
        self.calls.append(path)
        route, _, query = path.partition("?")
        params = dict(item.split("=", 1) for item in query.split("&") if item)
        if self.fail and self.fail in route:
            raise RuntimeError(f"GET {route}: HTTP Error 502")
        if route == "repos/acme/app":
            assert not params, path
            return {"default_branch": self.default_branch}
        if re.fullmatch(r"repos/acme/app/commits/[0-9a-f]{40}/pulls", route):
            assert set(params) == self.PAGED and params["per_page"] == "100", path
            sha = route.split("/")[4]
            listed = [{key: value for key, value in pull.items() if key != "_commits"} for pull in self.pulls
                      if sha in pull.get("_commits", [pull.get("merge_commit_sha")])]
            return StubGitHub.page(listed, params)
        if route == "repos/acme/app/actions/runs":
            assert set(params) == self.PAGED | {"head_sha", "event"} and params["event"] == "pull_request", path
            runs = [item for item in self.runs if item["head_sha"] == params["head_sha"]]
            return {"total_count": len(runs), "workflow_runs": StubGitHub.page(runs, params)}
        if route == "repos/acme/app/activity":
            assert params == {"ref": "refs/heads/main", "per_page": "100"}, path
            answer = self.activities[0] if len(self.activities) == 1 else self.activities.pop(0)
            return answer
        raise AssertionError(f"unexpected API call {path}")


def merged_pull(number, merge_sha, head_sha, branch="feat/add-export", base="main", merged=True):
    return {"number": number, "merged_at": "2026-11-13T10:00:00Z" if merged else None,
            "merge_commit_sha": merge_sha, "base": {"ref": base}, "head": {"sha": head_sha, "ref": branch}}


TARGETS = """\
targets:
  - { name: api, platform: cloud-run, trigger: { paths: [ 'src/**' ] }, rollback: { command: r }, probes: [ { command: p } ] }
  - { name: database, platform: cloud-sql, trigger: { paths: [ 'src/**', 'db/**' ] }, rollback: { command: r }, probes: [ { command: p } ] }
  - { name: web, platform: vercel, trigger: { paths: [ 'web/**' ] }, rollback: { command: r }, probes: [ { command: p } ] }
  - { name: everything, platform: vercel, trigger: { every_push: true }, rollback: { command: r }, probes: [ { command: p } ] }
"""


class DeployGuardTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".sdd/triggers.yaml", TRIGGERS)
        for name, content in GUARD_WORKFLOWS.items():
            self.repo.write(f".github/workflows/{name}", content)
        self.repo.write("README.md", "project\n")
        self.repo.write("openspec/changes/add-export/proposal.md", "# Proposal\n")

    def merge(self, files, classification_text=None, removed=(), branch="feat/add-export", before_extra=None,
              method="squash", base=True):
        """Base, pull request, merge (squash by default). Returns (before, merged, head)."""
        if base:
            self.repo.write("openspec/changes/add-export/classification.yaml", classification_text or classification())
            self.repo.commit("base")
        self.repo.git("switch", "-q", "-c", branch, "main")
        self.repo.write("openspec/changes/add-export/tasks.md", f"- [x] {branch}\n")
        for path, content in files.items():
            self.repo.write(path, content)
        for path in removed:
            self.repo.remove(path)
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        before = self.repo.git("rev-parse", "HEAD")
        if before_extra:
            self.repo.write(*before_extra)
            self.repo.commit("direct commit")
        if method == "squash":
            self.repo.git("merge", "-q", "--squash", branch)
            self.repo.git("commit", "-q", "-m", "squashed (#7)")
        else:
            self.repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #7", branch)
        return before, self.repo.git("rev-parse", "HEAD"), head

    def green(self, head):
        return [run("always.yml", head), run("not-docs.yml", head, run_id=2)]

    def guard(self, stub, merged, before, **options):
        options.setdefault("fetch", False)
        return mc.deploy_guard(stub, self.repo.path, "acme/app", merged, before, delay=0, **options)

    def test_merged_pull_request_with_green_ci_deploys(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)
        self.assertEqual(reason, f"deploy {merged[:7]}: #7 (change, gates: none), required CI green on {head[:7]}")

    def test_real_merge_commit_deploys(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"}, method="merge")
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)

    def test_direct_push_is_refused_after_asking_again(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([], self.green(head))
        code, reason = self.guard(stub, merged, before, attempts=3)
        self.assertEqual((code, reason), (mc.GUARD_REFUSED, f"refused {merged[:7]}: no pull request was merged "
                                                               f"into main as {merged[:7]} (direct push)"))
        self.assertEqual(sum("/pulls" in call for call in stub.calls), 3)

    def test_unmerged_pull_request_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head, merged=False)], self.green(head))
        self.assertEqual(self.guard(stub, merged, before)[0], mc.GUARD_REFUSED)

    def test_pull_request_merged_into_another_branch_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head, base="release")], self.green(head))
        self.assertEqual(self.guard(stub, merged, before)[0], mc.GUARD_REFUSED)

    def test_pull_request_merged_as_another_commit_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([dict(merged_pull(7, "e" * 40, head), _commits=[merged])], self.green(head))
        self.assertEqual(self.guard(stub, merged, before)[0], mc.GUARD_REFUSED)

    def test_several_pull_requests_merged_as_the_commit_are_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head), merged_pull(8, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"several pull requests merged as {merged[:7]} (#7, #8)", reason)

    def test_pull_requests_are_read_past_the_first_page(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        noise = [dict(merged_pull(100 + index, "d" * 40, head), _commits=[merged]) for index in range(120)]
        stub = GuardStub(noise + [merged_pull(7, merged, head)], self.green(head))
        self.assertEqual(self.guard(stub, merged, before)[0], mc.GUARD_DEPLOY)

    def test_red_ci_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        runs = [run("always.yml", head, conclusion="failure"), run("not-docs.yml", head, run_id=2)]
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], runs), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertTrue(reason.endswith(f"required CI not green on its head {head[:7]}: always failure"), reason)

    def test_workflow_whose_jobs_were_all_skipped_passes(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        for conclusion in ("skipped", "neutral"):
            with self.subTest(conclusion=conclusion):
                runs = [run("always.yml", head, conclusion=conclusion), run("not-docs.yml", head, run_id=2)]
                code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], runs), merged, before)
                self.assertEqual(code, mc.GUARD_DEPLOY, reason)

    def test_missing_or_running_ci_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        for runs, expected in (([run("always.yml", head)], "no run of not-docs"),
                               ([run("always.yml", head), run("not-docs.yml", head, status="in_progress",
                                                              conclusion=None, run_id=2)], "not-docs running"),
                               ([run("always.yml", head), run("not-docs.yml", head, event="push", run_id=2)],
                                "no run of not-docs")):
            with self.subTest(expected=expected):
                code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], runs), merged, before)
                self.assertEqual(code, mc.GUARD_REFUSED)
                self.assertTrue(reason.endswith(expected), reason)

    def test_path_filtered_workflow_is_required_by_the_diff(self):
        before, merged, head = self.merge({"web/app.ts": "x\n"}, classification(intent=True))
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, before)
        self.assertEqual((code, reason.rsplit(": ", 1)[-1]), (mc.GUARD_REFUSED, "no run of web"))

    def test_owner_merged_gated_change_deploys(self):
        before, merged, head = self.merge({"web/app.ts": "x\n"}, classification(intent=True))
        runs = self.green(head) + [run("web.yml", head, run_id=3)]
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], runs), merged, before)
        self.assertEqual((code, reason), (mc.GUARD_DEPLOY, f"deploy {merged[:7]}: #7 (change, gates: intent), "
                                                             f"required CI green on {head[:7]}"))

    def test_unaccounted_trigger_hit_is_refused(self):
        before, merged, head = self.merge({"db/migrations/V2__a.sql": "alter table t add c int;\n"})
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("unaccounted irreversible db/migrations/V2__a.sql", reason)

    def test_invalid_classification_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"}, "change: add-export\n")
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("gates: invalid", reason)

    def test_file_name_with_a_newline_is_refused_and_never_printed_raw(self):
        # R3b / R8: a newline hides a migration from the globs and forges lines in the alert.
        before, merged, head = self.merge({"db/migrations/V9__drop\ndeploy-guard: ok.sql": "drop table t;\n"})
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("file name with a control character: db/migrations/V9__drop\\ndeploy-guard: ok.sql", reason)
        self.assertNotIn("\n", reason)

    def test_push_carrying_more_than_the_merge_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"}, before_extra=("src/sneaky.py", "x\n"))
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"its first parent is not {before[:7]}", reason)

    def test_rebase_merge_of_two_commits_is_refused(self):
        # R4: GitHub's "Rebase and merge" pushes each commit of the pull request.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        before = self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1\n")
        self.repo.commit("c1")
        self.repo.write("src/a.py", "1\n")
        head = self.repo.commit("c2")
        self.repo.git("switch", "-q", "main")
        self.repo.git("cherry-pick", f"{head}~1", head)
        merged = self.repo.git("rev-parse", "HEAD")
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("so the push carried more than one merge", reason)
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, None,
                                  last_deployed=before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("no pull request was merged into main as", reason)

    def test_merge_edited_during_the_merge_is_refused(self):
        # R2: the merge commit carries a file the pull request head never had.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        before = self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1\n")
        self.repo.write("src/a.py", "1\n")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "--no-commit", "feat/add-export")
        self.repo.write("db/migrations/V9__drop.sql", "drop table users;\n")
        merged = self.repo.commit("Merge #7")
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual((code, reason), (mc.GUARD_REFUSED, f"refused {merged[:7]}: {merged[:7]} is not the merge of "
                                                               f"{before[:7]} and #7's head {head[:7]}: its content "
                                                               f"was edited during the merge"))

    def test_workflow_deleted_by_the_merged_pull_request_is_not_required(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"}, classification(irreversible=True),
                                          removed=[".github/workflows/not-docs.yml"])
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], [run("always.yml", head)]), merged, before)
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)

    def test_renamed_required_workflow_stays_required(self):
        self.repo.write("openspec/changes/add-export/classification.yaml", classification(irreversible=True))
        self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1\n")
        self.repo.write("src/a.py", "1\n")
        self.repo.move(".github/workflows/not-docs.yml", ".github/workflows/not-docs-2.yml")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        before = self.repo.git("rev-parse", "HEAD")
        self.repo.git("merge", "-q", "--squash", "feat/add-export")
        merged = self.repo.commit("squashed")
        stub = GuardStub([merged_pull(7, merged, head)], [run("always.yml", head)])
        code, reason = self.guard(stub, merged, before)
        self.assertEqual((code, reason.rsplit(": ", 1)[-1]), (mc.GUARD_REFUSED, "no run of not-docs-2"))
        stub = GuardStub([merged_pull(7, merged, head)], [run("always.yml", head), run("not-docs-2.yml", head, run_id=2)])
        self.assertEqual(self.guard(stub, merged, before)[0], mc.GUARD_DEPLOY)

    def test_required_workflows_are_read_from_before_the_merge(self):
        # The pull request filters not-docs out: the definition before the merge still requires it.
        before, merged, head = self.merge({"src/app.py": "print(1)\n",
                                           ".github/workflows/not-docs.yml": "name: NotDocs\non:\n  pull_request:\n"
                                                                             "    paths: [ 'nothing/**' ]\njobs: {}\n"},
                                          classification(irreversible=True))
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], [run("always.yml", head)]), merged, before)
        self.assertEqual((code, reason.rsplit(": ", 1)[-1]), (mc.GUARD_REFUSED, "no run of not-docs"))

    def test_nothing_under_the_paths_skips(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, before, paths=["web/**"])
        self.assertEqual((code, reason), (mc.GUARD_NOTHING, f"skip {merged[:7]}: nothing changed under web/** "
                                                              f"since {before[:7]}"))
        self.assertEqual(self.guard(stub, merged, before, paths=["web/**", "src/**"])[0], mc.GUARD_DEPLOY)

    def test_before_is_read_from_the_repository_activity(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        activity = [{"ref": "refs/heads/main", "before": "1" * 40, "after": "2" * 40, "activity_type": "push"},
                    {"ref": "refs/heads/main", "before": before, "after": merged, "activity_type": "pr_merge"}]
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head), activity)
        self.assertEqual(self.guard(stub, merged, None)[0], mc.GUARD_DEPLOY)

    def test_activity_lookup_is_asked_again(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        late = [{"ref": "refs/heads/main", "before": before, "after": merged, "activity_type": "pr_merge"}]
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head), activities=[[], [], late])
        self.assertEqual(self.guard(stub, merged, None, attempts=3)[0], mc.GUARD_DEPLOY)
        self.assertEqual(sum("/activity" in call for call in stub.calls), 3)

    def test_before_missing_from_the_activity_cannot_be_judged(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        activity = [{"ref": "refs/heads/other", "before": before, "after": merged}]
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head), activity)
        self.assertEqual(self.guard(stub, merged, None),
                         (mc.GUARD_CANNOT_JUDGE, f"cannot judge {merged[:7]}: no push of main to it in the repository "
                                                 f"activity, so the commit before it is unknown"))

    def test_force_push_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        activity = [{"ref": "refs/heads/main", "before": before, "after": merged, "activity_type": "force_push"}]
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head), activity)
        code, reason = self.guard(stub, merged, None)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("was force-pushed", reason)

    def test_branch_creation_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        self.assertEqual(self.guard(stub, merged, "0" * 40)[0], mc.GUARD_REFUSED)

    def test_manual_run_deploys_the_default_branch_only(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        self.assertEqual(self.guard(stub, merged, before, ref="refs/heads/main")[0], mc.GUARD_DEPLOY)
        self.assertEqual(self.guard(stub, merged, before, ref="refs/heads/feat/x"),
                         (mc.GUARD_REFUSED, f"refused {merged[:7]}: a manual run deploys main only, not refs/heads/feat/x"))

    def test_adoption_merge_is_its_own_outcome(self):
        os.remove(os.path.join(self.repo.path, ".sdd/triggers.yaml"))
        before, merged, head = self.merge({".sdd/triggers.yaml": TRIGGERS})
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_ADOPTION)
        self.assertTrue(reason.startswith(f"adoption {merged[:7]}: {merged[:7]} (#7) installs .sdd/triggers.yaml"), reason)

    def test_failures_to_judge_refuse(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        pulls = [merged_pull(7, merged, head)]
        for name, stub, sha, previous, expected in (
                ("API down", GuardStub(pulls, self.green(head), fail="actions/runs"), merged, before, "HTTP Error 502"),
                ("no default branch", GuardStub(pulls, self.green(head), default_branch=None), merged, before,
                 "the default branch of acme/app is unknown"),
                ("unknown before", GuardStub(pulls, self.green(head)), merged, "3" * 40, f"commit {'3' * 12!r} unavailable"),
                ("unknown head", GuardStub([merged_pull(7, merged, "4" * 40)], self.green(head)), merged, before,
                 f"#7's head {'4' * 12!r} unavailable"),
                ("not a sha", GuardStub(pulls, self.green(head)), "main", before, "'main' is not a full commit sha")):
            with self.subTest(name=name):
                code, reason = self.guard(stub, sha, previous)
                self.assertEqual(code, mc.GUARD_CANNOT_JUDGE)
                self.assertIn(expected, reason)

    def test_merged_revert_deploys(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        self.repo.git("switch", "-q", "-c", "revert/add-export", "main")
        self.repo.git("revert", "--no-edit", merged)
        self.repo.write("openspec/changes/add-export/revert.yaml", revert_file(merged))
        revert_head = self.repo.commit("revert")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--squash", "revert/add-export")
        self.repo.git("commit", "-q", "-m", "revert (#8)")
        reverted = self.repo.git("rev-parse", "HEAD")
        pulls = [merged_pull(8, reverted, revert_head, branch="revert/add-export"), merged_pull(7, merged, head)]
        code, reason = self.guard(GuardStub(pulls, self.green(revert_head)), reverted, merged)
        self.assertEqual((code, reason.split(": ", 1)[1].split(",")[0]), (mc.GUARD_DEPLOY, "#8 (revert"), reason)

    def test_merged_revert_of_another_change_s_merge_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        self.repo.git("switch", "-q", "-c", "revert/add-export", "main")
        self.repo.git("revert", "--no-edit", merged)
        self.repo.write("openspec/changes/add-export/revert.yaml", revert_file(merged))
        revert_head = self.repo.commit("revert")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--squash", "revert/add-export")
        reverted = self.repo.commit("revert (#8)")
        pulls = [merged_pull(8, reverted, revert_head, branch="revert/add-export"),
                 merged_pull(7, merged, head, branch="feat/other-change")]
        code, reason = self.guard(GuardStub(pulls, self.green(revert_head)), reverted, merged)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"{merged[:7]} is not the merge of a pull request of the change", reason)

    # --- the history since the last deployed commit ---------------------------------------

    def direct_push_then_merge(self):
        """A refused direct push E, then a proper merge on top. Returns (deployed, E, merged, head)."""
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        deployed = self.repo.commit("base")
        self.repo.write("db/migrations/V9__drop.sql", "drop table users;\n")
        evil = self.repo.commit("direct push")
        before, merged, head = self.merge({"src/a.py": "1\n"}, base=False)
        self.assertEqual(before, evil)
        return deployed, evil, merged, head

    def test_refused_commit_does_not_ship_with_the_next_merge(self):
        # R1: the merge itself passes; the direct push before it was never deployed.
        deployed, evil, merged, head = self.direct_push_then_merge()
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        self.assertEqual(self.guard(stub, merged, evil)[0], mc.GUARD_DEPLOY)  # without the last deployed commit
        code, reason = self.guard(stub, merged, evil, last_deployed=deployed)
        self.assertEqual((code, reason), (mc.GUARD_REFUSED, f"refused {merged[:7]}: {evil[:7]}, merged since the last "
                                                               f"deployed {deployed[:7]}, is not deployable: no pull "
                                                               f"request was merged into main as {evil[:7]} (direct push)"))

    def test_refused_commit_undone_by_a_merged_revert_is_cleared(self):
        deployed, evil, merged, head = self.direct_push_then_merge()
        self.repo.git("switch", "-q", "-c", "fix/undo", "main")
        self.repo.git("revert", "--no-edit", evil)
        undo_head = self.repo.git("rev-parse", "HEAD")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--squash", "fix/undo")
        undo = self.repo.commit("undo the direct push (#9)")
        pulls = [merged_pull(7, merged, head), merged_pull(9, undo, undo_head, branch="fix/undo")]
        stub = GuardStub(pulls, self.green(head) + self.green(undo_head))
        code, reason = self.guard(stub, undo, merged, last_deployed=deployed)
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)
        self.assertTrue(reason.endswith(f"(and 2 earlier commit(s) since {deployed[:7]})"), reason)

    def test_undo_must_be_exact_and_merged(self):
        deployed, evil, merged, head = self.direct_push_then_merge()
        self.repo.write("db/migrations/V9__drop.sql", "drop table users; -- kept\n")
        partial = self.repo.commit("direct partial undo")
        pulls = [merged_pull(7, merged, head)]
        code, reason = self.guard(GuardStub(pulls, self.green(head)), partial, merged, last_deployed=deployed)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"{evil[:7]}, merged since the last deployed", reason)

    def test_undo_that_is_itself_refused_does_not_clear(self):
        deployed, evil, merged, head = self.direct_push_then_merge()
        self.repo.git("revert", "--no-edit", evil)  # exact, but pushed directly
        undo = self.repo.git("rev-parse", "HEAD")
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), undo, merged,
                                  last_deployed=deployed)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"refused {undo[:7]}: {evil[:7]}, merged since the last deployed", reason)

    def test_last_deployed_must_be_a_full_sha(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        self.assertEqual(self.guard(GuardStub(), merged, None, last_deployed="main"),
                         (mc.GUARD_CANNOT_JUDGE, f"cannot judge {merged[:7]}: last deployed 'main' is not a full commit sha"))

    def test_merge_of_a_conflicting_pull_request_is_refused(self):
        # GitHub never merges a conflicting pull request: a merge commit whose parent and pull request
        # head conflict was resolved by hand, even when it equals the head.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        self.repo.write("src/a.txt", "1\n")
        self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1\n")
        self.repo.write("src/a.txt", "3\n")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        self.repo.write("src/a.txt", "2\n")
        before = self.repo.commit("main moved")
        self.repo.git("merge", "-q", "--no-ff", "-X", "theirs", "-m", "Merge #7", "feat/add-export")
        merged = self.repo.git("rev-parse", "HEAD")
        self.assertEqual(self.repo.git("rev-parse", f"{merged}^{{tree}}"), self.repo.git("rev-parse", f"{head}^{{tree}}"))
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, before)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("its content was edited during the merge", reason)

    def test_last_deployed_commit_off_the_first_parent_line_is_not_trusted(self):
        # Review A: a run's head_sha on a merged branch (reachable, but not a commit of main) is no anchor.
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        self.repo.commit("base")
        self.repo.branch("feat/add-export")
        self.repo.write("openspec/changes/add-export/tasks.md", "- [x] 1\n")
        inner = self.repo.commit("inner commit of the branch")
        self.repo.write("src/a.py", "1\n")
        head = self.repo.commit("pull request")
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge #7", "feat/add-export")
        merged = self.repo.git("rev-parse", "HEAD")
        self.assertTrue(mc.is_ancestor(self.repo.path, inner, merged))
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, None,
                                  last_deployed=inner)
        self.assertEqual((code, reason), (mc.GUARD_REFUSED, f"refused {merged[:7]}: the last deployed commit "
                                                               f"{inner[:7]} is not on its first-parent line (a commit "
                                                               f"of a merged branch, not of main): it is not trusted"))

    def with_targets(self, profile):
        self.repo.write(".sdd/deployment.yaml", profile)

    def test_target_judges_only_the_commits_changing_its_paths(self):
        # Review C(1): a refused commit outside the target's paths does not block that target.
        self.with_targets(TARGETS)
        deployed, evil, merged, head = self.direct_push_then_merge()  # evil: db/; the merge: src/
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, evil, last_deployed=deployed, target="api")
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)
        self.assertTrue(reason.endswith(f"; 1 commit(s) since {deployed[:7]} outside the target's paths, not judged"),
                        reason)
        code, reason = self.guard(stub, merged, evil, last_deployed=deployed, target="database")
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"{evil[:7]}, merged since the last deployed", reason)
        code, reason = self.guard(stub, merged, evil, last_deployed=deployed, target="everything")
        self.assertEqual(code, mc.GUARD_REFUSED)

    def test_target_with_no_change_since_the_last_deploy_deploys(self):
        self.with_targets(TARGETS)
        deployed, evil, merged, head = self.direct_push_then_merge()
        code, reason = self.guard(GuardStub(), merged, evil, last_deployed=deployed, target="web")
        self.assertEqual((code, reason), (mc.GUARD_DEPLOY, f"deploy {merged[:7]}: no commit since {deployed[:7]} "
                                                             f"changes the target's paths; 2 commit(s) since "
                                                             f"{deployed[:7]} outside the target's paths, not judged"))

    def test_target_is_read_from_the_trusted_commit(self):
        self.with_targets(TARGETS)
        self.repo.write("openspec/changes/add-export/classification.yaml", classification())
        deployed = self.repo.commit("base")
        self.repo.write("db/migrations/V9__drop.sql", "drop table users;\n")
        self.repo.write(".sdd/deployment.yaml", TARGETS.replace("'src/**', 'db/**'", "'nothing/**'"))
        evil = self.repo.commit("direct push narrowing the target")
        stub = GuardStub()
        code, reason = self.guard(stub, evil, deployed, last_deployed=deployed, target="database")
        self.assertEqual(code, mc.GUARD_REFUSED, reason)

    def test_unknown_target_cannot_be_judged(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, before, target="api")
        self.assertEqual((code, reason), (mc.GUARD_CANNOT_JUDGE, f"cannot judge {merged[:7]}: no .sdd/deployment.yaml "
                                                                    f"at the trusted commit {before[:7]}"))
        self.with_targets(TARGETS)
        self.repo.commit("profile")
        before, merged, head = self.merge({"src/b.py": "2\n"}, base=False, branch="fix/add-export")
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        self.assertEqual(self.guard(stub, merged, before, target="nope"),
                         (mc.GUARD_CANNOT_JUDGE, f"cannot judge {merged[:7]}: no target 'nope' in "
                                                 f".sdd/deployment.yaml at {before[:7]}"))

    def test_history_rewritten_since_the_last_deployed_commit_is_refused(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        self.repo.git("switch", "-q", "-c", "elsewhere", before)
        self.repo.write("x.txt", "x\n")
        elsewhere = self.repo.commit("not on main")
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = self.guard(stub, merged, before, last_deployed=elsewhere)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn(f"the last deployed commit {elsewhere[:7]} is not in its history", reason)

    def test_last_deployed_commit_itself_deploys(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        self.assertEqual(self.guard(GuardStub(), merged, None, last_deployed=merged)[0], mc.GUARD_DEPLOY)

    def test_too_long_a_history_is_refused(self):
        deployed, evil, merged, head = self.direct_push_then_merge()
        self.addCleanup(setattr, mc, "CHAIN_MAX", mc.CHAIN_MAX)
        mc.CHAIN_MAX = 1
        code, reason = self.guard(GuardStub([merged_pull(7, merged, head)], self.green(head)), merged, evil,
                                  last_deployed=deployed)
        self.assertEqual(code, mc.GUARD_REFUSED)
        self.assertIn("2 commits since the last deployed", reason)

    def test_paths_count_since_the_last_deployed_commit(self):
        deployed, evil, merged, head = self.direct_push_then_merge()
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, _ = self.guard(stub, merged, evil, last_deployed=deployed, paths=["db/**"])
        self.assertEqual(code, mc.GUARD_REFUSED)  # db/ changed since the deploy, not in the merge itself

    def test_fetches_the_pull_request_head_into_a_shallow_clone(self):
        before, merged, head = self.merge({"src/app.py": "print(1)\n"})
        server = tempfile.mkdtemp(prefix="merge-conditions-server-")
        self.addCleanup(shutil.rmtree, server, True)
        bare = os.path.join(server, "acme", "app.git")
        subprocess.run(["git", "clone", "-q", "--bare", self.repo.path, bare], env=GIT_ENV, check=True)
        subprocess.run(["git", "-C", bare, "update-ref", "refs/pull/7/head", head], env=GIT_ENV, check=True)
        subprocess.run(["git", "-C", bare, "branch", "-q", "-D", "feat/add-export"], env=GIT_ENV, check=True)
        work = os.path.join(server, "work")
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{bare}", work], env=GIT_ENV, check=True)
        self.assertEqual(mc.rev_parse(work, head), "")
        stub = GuardStub([merged_pull(7, merged, head)], self.green(head))
        code, reason = mc.deploy_guard(stub, work, "acme/app", merged, before, token="t",
                                       server_url=f"file://{server}", delay=0)
        self.assertEqual(code, mc.GUARD_DEPLOY, reason)


class DeployGuardCommandTest(unittest.TestCase):
    def setUp(self):
        environment = {name: os.environ.pop(name) for name in mc.TOKEN_VARIABLES if name in os.environ}
        self.addCleanup(os.environ.update, environment)

    def test_no_token_cannot_judge(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = mc.main(["deploy-guard", "--repo", "acme/app", "--sha", "a" * 40, "--before", "b" * 40])
        self.assertEqual((code, output.getvalue().strip()), (2, "deploy-guard: cannot judge: no token "
                                                                 "(DEPLOY_GUARD_TOKEN, GH_TOKEN, GITHUB_TOKEN)"))

    def test_verdict_file_and_printed_line_escape_control_characters(self):
        folder = tempfile.mkdtemp(prefix="deploy-guard-verdict-")
        self.addCleanup(shutil.rmtree, folder, True)
        verdict = os.path.join(folder, "verdict.json")
        original = mc.deploy_guard
        self.addCleanup(setattr, mc, "deploy_guard", original)
        mc.deploy_guard = lambda *args, **kwargs: (1, "refused x: #7: file\ndeploy-guard: forged\x1b")
        os.environ["GH_TOKEN"] = "t"
        self.addCleanup(os.environ.pop, "GH_TOKEN", None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = mc.main(["deploy-guard", "--repo", "acme/app", "--sha", "a" * 40, "--last-deployed", "b" * 40,
                            "--verdict-file", verdict])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "deploy-guard: refused x: #7: file\\ndeploy-guard: forged\\u001b\n")
        with open(verdict) as handle:
            self.assertEqual(json.load(handle), {"code": 1, "outcome": "refused", "sha": "a" * 40,
                                                 "reason": "refused x: #7: file\\ndeploy-guard: forged\\u001b"})

    def test_needs_a_starting_point(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mc.main(["deploy-guard", "--repo", "acme/app", "--sha", "a" * 40])

    def test_token_order(self):
        self.assertEqual(mc.guard_token({"GITHUB_TOKEN": "c", "GH_TOKEN": "b", "DEPLOY_GUARD_TOKEN": "a"}), "a")
        self.assertEqual(mc.guard_token({"GITHUB_TOKEN": "c", "GH_TOKEN": ""}), "c")
        self.assertIsNone(mc.guard_token({}))


SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy-guard.sh")
# A stand-in for python3: logs each call (with the first line of the merge_conditions.py it is given),
# answers `-c 'import yaml'` with FAKE_YAML, creates a venv (a copy of itself) when FAKE_VENV is 0.
FAKE_PYTHON = """#!/usr/bin/env bash
case "$1" in
  -c) printf '%s\\n' "$*" >> "$FAKE_LOG"; exit "${FAKE_YAML:-0}" ;;
  -m) printf '%s\\n' "$*" >> "$FAKE_LOG"
      if [ "$2" = venv ] && [ "${FAKE_VENV:-1}" = 0 ]; then mkdir -p "$3/bin" && cp "$0" "$3/bin/python"; exit 0; fi
      [ "$2" = pip ] && exit "${FAKE_PIP:-0}"
      exit "${FAKE_VENV:-1}" ;;
esac
printf '%s | %s\\n' "$(head -n 1 "$1")" "${*:2}" >> "$FAKE_LOG"
echo "deploy-guard: fake verdict"
exit "${FAKE_CODE:-0}"
"""
FAKE_CURL = """#!/usr/bin/env bash
printf 'curl %s\\n' "$*" >> "$FAKE_LOG"
while [ $# -gt 0 ]; do [ "$1" = -o ] && { printf '# from the contents API\\n' > "$2"; exit "${FAKE_CURL:-0}"; }; shift; done
exit 1
"""


class DeployGuardScriptTest(unittest.TestCase):
    """deploy-guard.sh: the trusted code it runs, its arguments per platform and the exit-code mapping
    (Vercel's is inverted)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="deploy-guard-script-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.bin = os.path.join(self.folder, "bin")
        os.makedirs(self.bin)
        for name, text in (("python", FAKE_PYTHON), ("curl", FAKE_CURL)):
            with open(os.path.join(self.bin, name), "w") as handle:
                handle.write(text)
            os.chmod(os.path.join(self.bin, name), 0o755)
        self.log = os.path.join(self.folder, "log")
        # The checkout: the trusted commit's guard says "# trusted", the pushed one's "# pushed".
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write(".sdd/bin/merge_conditions.py", "# trusted\n")
        self.trusted = self.repo.commit("trusted")
        self.repo.write(".sdd/bin/merge_conditions.py", "# pushed\n")
        self.merged = self.repo.commit("pushed")
        self.repo.git("switch", "-q", "--orphan", "bare")
        self.repo.write("README.md", "no guard\n")
        self.unguarded = self.repo.commit("before the guard")
        self.repo.git("switch", "-q", "main")
        self.top = self.repo.git("rev-parse", "--show-toplevel")

    def run_script(self, *arguments, **environment):
        base = {key: value for key, value in os.environ.items()
                if not key.startswith(("GITHUB_", "VERCEL_", "FAKE_")) and key not in mc.TOKEN_VARIABLES}
        base.update(DEPLOY_GUARD_PYTHON=os.path.join(self.bin, "python"), FAKE_LOG=self.log, TMPDIR=self.folder,
                    PATH=self.bin + os.pathsep + base.get("PATH", ""), GH_TOKEN="t")
        base.update(environment)
        if os.path.exists(self.log):
            os.remove(self.log)
        result = subprocess.run(["bash", SCRIPT, *arguments], env=base, cwd=self.repo.path,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as handle:
                calls = handle.read().splitlines()
        return result.returncode, [call for call in calls if " | " in call], result.stdout.decode(), calls

    def actions(self, code, before=None, trusted=None, **environment):
        environment.setdefault("GITHUB_REPOSITORY", "acme/app")
        return self.run_script(self.merged, self.trusted if before is None else before,
                               trusted or self.trusted, FAKE_CODE=str(code), **environment)

    def vercel(self, code, *globs, **environment):
        environment.setdefault("VERCEL_ENV", "production")
        environment.setdefault("VERCEL_GIT_REPO_OWNER", "acme")
        environment.setdefault("VERCEL_GIT_REPO_SLUG", "app")
        environment.setdefault("VERCEL_GIT_COMMIT_SHA", self.merged)
        environment.setdefault("VERCEL_GIT_PREVIOUS_SHA", self.trusted)
        return self.run_script("--vercel", *globs, FAKE_CODE=str(code), **environment)

    def test_actions_runs_the_trusted_guard_and_maps_its_verdict(self):
        for guard_code, expected in ((0, 0), (1, 1), (2, 2), (3, 1), (4, 4), (139, 139)):
            with self.subTest(guard=guard_code):
                code, calls, _, _ = self.actions(guard_code)
                self.assertEqual(code, expected)
                self.assertEqual(calls, [f"# trusted | -C {self.top} deploy-guard --repo acme/app --sha "
                                         f"{self.merged} --last-deployed {self.trusted} --before {self.trusted}"])

    def test_trusted_commit_without_a_guard_is_the_adoption(self):
        code, calls, output, _ = self.actions(0, trusted=self.unguarded)
        self.assertEqual((code, calls), (4, []))
        self.assertIn("deploy-guard: adoption:", output)
        self.assertEqual(self.vercel(0, VERCEL_GIT_PREVIOUS_SHA=self.unguarded)[:2], (0, []))

    def test_trusted_commit_missing_here_is_read_from_the_contents_api(self):
        missing = "9" * 40
        code, calls, _, log = self.actions(0, trusted=missing, GITHUB_API_URL="https://api.example.invalid")
        self.assertEqual(code, 0)
        self.assertTrue(calls[0].startswith("# from the contents API | "), calls)
        self.assertIn("curl -fsSL -H Authorization: Bearer t -H Accept: application/vnd.github.raw -o ", log[0])
        self.assertTrue(log[0].endswith(f"https://api.example.invalid/repos/acme/app/contents/.sdd/bin/"
                                        f"merge_conditions.py?ref={missing}"), log[0])
        self.assertEqual(self.actions(0, trusted=missing, FAKE_CURL="22")[:2], (2, []))

    def test_manual_run_uses_the_parent_and_the_ref(self):
        code, calls, _, _ = self.actions(0, before="", GITHUB_EVENT_NAME="workflow_dispatch",
                                         GITHUB_REF="refs/heads/main")
        self.assertEqual(code, 0)
        self.assertTrue(calls[0].endswith(f"--last-deployed {self.trusted} --ref refs/heads/main --before {self.trusted}"),
                        calls[0])
        self.assertEqual(self.actions(0, before="")[:2], (2, []))  # an empty before outside a manual run

    def test_actions_usage(self):
        for arguments in ((), ("a" * 40,), ("a" * 40, "b" * 40), ("a" * 40, "b" * 40, ""), ("", "b", "c"),
                          ("a" * 40, "b" * 40, "c" * 40, "d")):
            with self.subTest(arguments=arguments):
                code, calls, _, _ = self.run_script(*arguments, GITHUB_REPOSITORY="acme/app")
                self.assertEqual((code, calls), (2, []))

    def test_actions_without_repository_cannot_judge(self):
        code, calls, output, _ = self.run_script(self.merged, self.trusted, self.trusted, FAKE_CODE="0")
        self.assertEqual((code, calls), (2, []))
        self.assertIn("repository unknown", output)

    def test_target_is_passed_on(self):
        code, calls, _, _ = self.actions(0, DEPLOY_GUARD_TARGET="api")
        self.assertTrue(calls[0].endswith(f"--before {self.trusted} --target api"), calls[0])

    def test_verdict_file_is_passed_on(self):
        code, calls, _, _ = self.actions(0, DEPLOY_GUARD_VERDICT="/tmp/verdict.json")
        self.assertTrue(calls[0].endswith("--verdict-file /tmp/verdict.json"), calls[0])

    def test_vercel_builds_only_when_the_trusted_guard_says_deploy(self):
        for guard_code, expected in ((0, 1), (1, 0), (2, 0), (3, 0), (4, 0), (127, 0)):
            with self.subTest(guard=guard_code):
                code, calls, _, _ = self.vercel(guard_code, "frontend/**", "shared/**")
                self.assertEqual(code, expected)
                self.assertEqual(calls, [f"# trusted | -C {self.top} deploy-guard --repo acme/app --sha "
                                         f"{self.merged} --last-deployed {self.trusted} --paths frontend/** shared/**"])

    def test_vercel_without_globs_passes_no_paths(self):
        code, calls, _, _ = self.vercel(0)
        self.assertEqual(code, 1)
        self.assertTrue(calls[0].endswith(f"--last-deployed {self.trusted}"), calls[0])

    def test_vercel_without_environment_is_guarded_not_a_preview(self):
        for guard_code, expected in ((0, 1), (1, 0)):
            with self.subTest(guard=guard_code):
                code, calls, _, _ = self.vercel(guard_code, VERCEL_ENV="")
                self.assertEqual((code, len(calls)), (expected, 1))

    def test_vercel_preview_builds_unguarded(self):
        code, calls, _, _ = self.vercel(1, VERCEL_ENV="preview")
        self.assertEqual((code, calls), (1, []))

    def test_vercel_without_commit_previous_deployment_or_repository_skips(self):
        for environment in ({"VERCEL_GIT_COMMIT_SHA": ""}, {"VERCEL_GIT_PREVIOUS_SHA": ""},
                            {"VERCEL_GIT_REPO_OWNER": ""}):
            with self.subTest(environment=environment):
                code, calls, _, _ = self.vercel(0, **environment)
                self.assertEqual((code, calls), (0, []))

    def test_pyyaml_is_installed_hash_pinned_in_a_fresh_environment(self):
        code, calls, _, log = self.actions(0, FAKE_YAML="1", FAKE_VENV="0")
        self.assertEqual(code, 0)
        venv = [line for line in log if line.startswith("-m venv ")][0].split()[2]
        self.assertTrue(os.path.basename(os.path.dirname(venv)).startswith("sdd-deploy-guard."), venv)
        pip = [line for line in log if line.startswith("-m pip ")][0]
        self.assertIn("--only-binary :all: --require-hashes -r ", pip)
        self.assertEqual(len(calls), 1)
        self.assertFalse(os.path.exists(os.path.dirname(venv)))  # removed on exit
        self.assertEqual(self.actions(0, FAKE_YAML="1", FAKE_VENV="0", FAKE_PIP="1")[:2], (2, []))

    def test_missing_pyyaml_that_cannot_be_installed_refuses(self):
        self.assertEqual(self.actions(0, FAKE_YAML="1")[:2], (2, []))
        self.assertEqual(self.vercel(0, FAKE_YAML="1")[:2], (0, []))

    def test_missing_interpreter_refuses(self):
        missing = os.path.join(self.folder, "no-python")
        self.assertEqual(self.actions(0, DEPLOY_GUARD_PYTHON=missing)[0], 2)
        self.assertEqual(self.vercel(0, DEPLOY_GUARD_PYTHON=missing)[0], 0)


class TemplateCopyTest(unittest.TestCase):
    """In the toolbox, `.sdd/bin/` is the installed copy of the sdd-init template: byte-identical."""

    def test_installed_copy_is_the_template(self):
        here = os.path.dirname(os.path.abspath(__file__))
        template = os.path.join(here, "..", "..", "plugins", "sdd-core", "skills", "sdd-init", "templates", "sdd", "bin")
        if not os.path.isdir(template) or os.path.samefile(template, here):
            self.skipTest("not the toolbox's installed copy")
        names = sorted(name for name in os.listdir(here) if not name.startswith((".", "__")))
        self.assertEqual(names, sorted(name for name in os.listdir(template) if not name.startswith((".", "__"))))
        for name in names:
            with self.subTest(name=name), open(os.path.join(here, name), "rb") as mine, \
                    open(os.path.join(template, name), "rb") as theirs:
                self.assertEqual(mine.read(), theirs.read(), f"{name} differs from its template")
                self.assertEqual(os.stat(os.path.join(here, name)).st_mode & 0o111,
                                 os.stat(os.path.join(template, name)).st_mode & 0o111)


DEPLOYMENT = """\
targets:
  - name: backend
    platform: cloud-run
    trigger: { paths: [ 'backend/**' ] }
    workflow: .github/workflows/deploy-backend.yml
    rollback:
      command: gcloud run services update-traffic api --region europe-west1 --to-revisions=PREVIOUS=100
      unconfirmed: true
    probes:
      - command: curl -fsS https://api.example.com/health
        expect: '"status":"UP"'
  - name: frontend
    platform: vercel
    trigger: { every_push: true }
    rollback:
      command: vercel rollback --yes
    probes:
      - command: curl -fsS -o /dev/null https://www.example.com/
        unconfirmed: true
scheduled_jobs:
  - name: daily-etl
    schedule: '0 3 * * * Europe/Paris'
    paths: [ 'backend/src/main/java/**/etl/**' ]
    runs: Cloud Scheduler, Cloud Run job etl
    probe:
      command: gcloud run jobs executions list --job etl --limit 1 --format 'value(status.succeededCount)'
      expect: '^1$'
"""


class DeploymentSchemaTest(unittest.TestCase):
    def test_valid_profile_lists_its_unconfirmed_values(self):
        profile, errors, unconfirmed = mc.load_deployment(DEPLOYMENT)
        self.assertEqual(errors, [])
        self.assertEqual([target["name"] for target in profile["targets"]], ["backend", "frontend"])
        self.assertEqual(unconfirmed, ["targets[backend].rollback", "targets[frontend].probes[0]"])

    def test_project_that_deploys_nothing(self):
        self.assertEqual(mc.load_deployment("deploys_nothing: true\n")[1], [])
        self.assertEqual(mc.load_deployment("deploys_nothing: true\nscheduled_jobs: []\n")[1], [])

    def test_errors(self):
        cases = {
            "deploys_nothing: true\ntargets: [ { name: a } ]\n":
                "deployment.yaml: deploys_nothing is true, so no target (and no rollback) can be listed",
            "targets: []\n": "deployment.yaml: no target: list what merging deploys, or set deploys_nothing: true",
            "{}\n": "deployment.yaml: no target: list what merging deploys, or set deploys_nothing: true",
            "deploys_nothing: yes please\n": "deployment.yaml: deploys_nothing: expected true or false",
            "deploys_nothing: true\nextra: 1\n": "deployment.yaml: unknown key 'extra'",
            "deploys_nothing: true\nscheduled_jobs: [ { name: etl, schedule: daily } ]\n":
                "deployment.yaml: scheduled_jobs[etl].paths: expected a non-empty list of globs",
            "deploys_nothing: true\nscheduled_jobs: [ { name: etl, paths: [ 'a/**' ] } ]\n":
                "deployment.yaml: scheduled_jobs[etl].schedule: expected the schedule (cron, with its time zone)",
            "deploys_nothing: true\nscheduled_jobs: [ { name: etl, schedule: d, paths: [ 'a/**' ], "
            "probe: { expect: x } } ]\n": "deployment.yaml: scheduled_jobs[etl].probe.command: expected the command, as run",
            "deploys_nothing: true\nscheduled_jobs: [ { schedule: d, paths: [ 'a/**' ] } ]\n":
                "deployment.yaml: scheduled_jobs[0].name: expected the job's name",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(expected, mc.load_deployment(text)[1])

    def test_target_errors(self):
        def target(**fields):
            base = {"name": "api", "platform": "cloud-run", "trigger": {"every_push": True},
                    "rollback": {"command": "rollback"}, "probes": [{"command": "curl x"}]}
            base.update(fields)
            for key in [key for key, value in base.items() if value is None]:
                del base[key]
            return mc.load_deployment(mc.yaml.safe_dump({"targets": [base]}))[1]

        self.assertEqual(target(), [])
        cases = [
            (dict(rollback=None), "rollback: expected the platform command that restores the previous deployment"),
            (dict(rollback={"note": "by hand"}), "rollback.command: expected the command, as run"),
            (dict(trigger={"paths": ["a/**"], "every_push": True}), "trigger: expected either"),
            (dict(trigger={}), "trigger: expected either"),
            (dict(trigger={"every_push": False}), "trigger.every_push: expected true"),
            (dict(trigger={"paths": []}), "trigger.paths: expected a non-empty list of globs"),
            (dict(probes=[]), "probes: expected at least one probe"),
            (dict(probes=[{"expect": "UP"}]), "probes[0].command: expected the command, as run"),
            (dict(probes=[{"command": "curl", "expect": "("}]), "probes[0].expect: invalid regex"),
            (dict(probes=[{"command": "curl", "unconfirmed": "maybe"}]), "probes[0].unconfirmed: expected true or false"),
            (dict(platform=None), "platform: expected the platform"),
            (dict(name=None), "targets[0].name: expected the target's name"),
            (dict(color="red"), "unknown key 'color'"),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                errors = target(**fields)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_duplicate_target_names(self):
        profile = mc.yaml.safe_load(DEPLOYMENT)
        profile["targets"][1]["name"] = "backend"
        self.assertIn("deployment.yaml: targets[backend]: duplicate target name",
                      mc.load_deployment(mc.yaml.safe_dump(profile))[1])


class ValidateCommandTest(unittest.TestCase):
    def test_validate_prints_unconfirmed_values_and_checks_revert_files(self):
        folder = tempfile.mkdtemp(prefix="merge-conditions-validate-")
        self.addCleanup(shutil.rmtree, folder, True)
        deployment = os.path.join(folder, "deployment.yaml")
        revert = os.path.join(folder, "add-export", "revert.yaml")
        os.makedirs(os.path.dirname(revert))
        with open(deployment, "w") as handle:
            handle.write(DEPLOYMENT)
        with open(revert, "w") as handle:
            handle.write(revert_file("a" * 40, change="other"))
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = mc.main(["validate", deployment, revert])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue().splitlines(), [f"unconfirmed: {deployment}: targets[backend].rollback",
                                                          f"unconfirmed: {deployment}: targets[frontend].probes[0]"])
        self.assertEqual(errors.getvalue().splitlines(),
                         [f"{revert}: revert.yaml: revert_of is 'other', the folder is 'add-export'"])

    def test_validate_reports_each_invalid_file(self):
        folder = tempfile.mkdtemp(prefix="merge-conditions-validate-")
        self.addCleanup(shutil.rmtree, folder, True)
        good = os.path.join(folder, "add-export", "classification.yaml")
        bad = os.path.join(folder, "triggers.yaml")
        os.makedirs(os.path.dirname(good))
        with open(good, "w") as handle:
            handle.write(classification())
        with open(bad, "w") as handle:
            handle.write(textwrap.dedent("intent:\n  paths: oops\n"))
        self.assertEqual(mc.validate_files([good]), [])
        self.assertEqual(len(mc.validate_files([good, bad])), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
