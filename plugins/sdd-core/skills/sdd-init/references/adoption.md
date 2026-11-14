# Adopting a project that already has tooling, and `--refresh`

## 1. The project already has target files

Rule: **what exists was written for a reason.** Merge, don't overwrite.

| File present | What to do |
|---|---|
| `CLAUDE.md` | Read it in full. Keep everything specific to the project (rules, context, pitfalls). Add the template sections that are missing; if an existing section contradicts the workflow (e.g. "commit straight to main"), flag it and ask at gate 1 — don't decide alone. |
| `AGENTS.md` (multi-tool format) | Don't replace it: add a "Claude agent team" section pointing to `.claude/agents/README.md`. |
| `.claude/agents/<x>.md` | Same name as a template → compare: keep the existing file's specific rules, add the template's blocks (USE WHEN / DO NOT USE description, output format, graphify…). Different name → keep it and add it to the routing table. |
| `.claude/settings.json` | JSON merge: add the git guardrail's `PreToolUse` hook, remove or change nothing else. |
| `.claude/hooks/*` from another git guardrail | Show both to the user, recommend keeping only one (two contradictory hooks = baffling blocks). |
| `openspec/` already initialised | No `openspec init`. `openspec update` to refresh the commands. `config.yaml`: merge `context` and `rules` (add the template rules that are missing). Existing specs are **not** touched. |
| `docs/*.md` with the same name | Merge section by section; whatever contradicts the observed code is flagged in the report (not silently fixed). |
| Existing CI | Only add `openspec.yml`, `tooling.yml` and (option `github`) `merge-conditions.yml`, whose `workflow_run.workflows` lists the existing pull-request workflows by `name:`; don't touch the existing workflows — except the deploy workflows (next row). |
| Existing deploy workflows (option `github` + `deploys`) | The guard block of `templates/github/workflows/deploy.yml` is merged at the top of the job that deploys (`concurrency: deploy-${{ github.workflow }}`, `workflow_dispatch`, full-history checkout without persisted credentials, the "Deploy guard" step that reads the guard from the last deployed commit), the project's steps kept unchanged after it; `deploy-alert.yml` added. Show the diff of each at gate 1. Vercel: after the adoption is merged, the owner redeploys production once without the Ignored Build Step (the last deployment has no guard yet). |
| `vercel.json` | Add `ignoreCommand` (`templates/vercel/vercel.json`); keep every other key. An existing `ignoreCommand`, or an Ignored Build Step set in Vercel's settings (a `vercel.json` value overrides it), is shown to the owner, who decides. |
| `.sdd/deployment.yaml` | Created when absent (phase 4 step 7 of `SKILL.md`), never rewritten: it is the project's own. |

Show the diff of every merged file at validation gate 1 (summary: sections added / kept / in
conflict).

## 2. Install marker

Last line of the generated `CLAUDE.md`:

```markdown
<!-- claude-toolbox: installed <sdd-core plugin version> on <YYYY-MM-DD> — options: <list> -->
```

It is what `--refresh` relies on. Read the version in the plugin's `.claude-plugin/plugin.json` (two
levels above this skill). Markers written before the autonomy levels were removed end with
`— autonomy: <level>`: still read (§3), never written again.

## 3. `/sdd-init --refresh` — resync with a newer version of the kit

1. Read the marker (`claude-toolbox: installed …`, or `sdd-kit: installed …` for a project set up before
   the catalog was renamed — rewrite it to the new form): installed version, options, and the former
   `autonomy` level if the marker still has one (it only feeds step 4's report; the new marker drops
   it). Missing → this project was not set up by the kit: offer a full install in adoption mode (§1).
2. Branch `chore/sdd-init-refresh-<version>`.
3. For every file generated from a template (`CLAUDE.md`, `AGENTS.md`, `.claude/agents/*`,
   `docs/{CONTRIBUTING,OPENSPEC_GUIDE,AGENT_TOOLBOX,GRAPHIFY}.md`, `openspec/config.yaml`,
   `.claude/hooks/*`, `.claude/settings.json` (union of the `allow` lists and hooks, nothing removed),
   `.claude/settings.local.example.json`, `.claude/launch.json` (option `ui`), the kit's CI workflows,
   `merge-conditions.yml` included (option `github`; its `workflow_run.workflows` list is read back
   from the current file and completed with any pull-request workflow it misses)).
   `.sdd/harness.yaml`, `.sdd/triggers.yaml` and `.sdd/deployment.yaml` are the project's own
   settings: created from phase 4 steps 5, 6 and 7 of `SKILL.md` when absent (for
   `deployment.yaml`, with the deploy guard's wiring, `deploy-alert.yml` and the `in-flight` label of
   step 7), never rewritten when present (new keys of the template are listed in the report). For the
   template-generated files:
   - fill the **new** template with the project's values (read back from the current files, not
     deduced again);
   - compare with the current file: what differs comes either from the kit (to apply) or from a local
     change (to keep). When in doubt about where a difference comes from, keep the local version and
     list it.
4. Files copied verbatim (hook `.sh`/`.pl`/`.test.sh`, `.sdd/bin/merge_conditions.py`,
   `.sdd/bin/test_merge_conditions.py` and `.sdd/bin/deploy-guard.sh`): replaced, then `bash .claude/hooks/block-git-writes.test.sh`
   and `python3 .sdd/bin/test_merge_conditions.py`. The local `.conf` is kept, its values unchanged,
   except for the settings the kit removed or added:
   - **`ALLOW_PR_MERGE` removed** (with the `autonomy-*` levels): delete the line. Who merges is now
     decided per pull request — the agent merges only through the verified route (`merge-conditions`
     green with `gates: none` on the head commit, judged against the current default-branch head, no
     other PR `in-flight`), the owner merges every PR with an open gate. **BREAKING**: a project that
     had `ALLOW_PR_MERGE=0` (`autonomy-pr`) now lets the agent merge its ungated PRs; one that had
     `ALLOW_PR_MERGE=1` (`autonomy-merge`) loses the agent's merge of gated PRs and of any PR when
     `merge-conditions` is absent (no option `github`). Say which case applies, in the report and in
     the commit body, and ask the owner before committing when it is the first.
   - **`MERGE_METHOD` added** when missing, from the repository's settings
     (`gh api repos/{owner}/{repo} --jq '[.allow_squash_merge, .allow_merge_commit]'`, VARIABLES
     `{{MERGE_METHOD}}`): only one allowed → that one; both → `merge`, the method the former hook
     enforced, unless the owner picks `squash`; neither (rebase only) → `squash`, and the report asks
     the owner to allow it; no GitHub remote → `merge`. Never `rebase`.
   - **`ALLOW_FORCE_WITH_LEASE=0` added** when missing.
   - `ALLOW_PUSH` and `PROTECTED_BRANCHES` keep their values (a former `autonomy-commit` project keeps
     `ALLOW_PUSH=0`: its agent still never pushes).
   - `.claude/settings.json`: the guardrail's hook entry gets `"timeout": 120` (the suite checks
     that the merge route's deadline stays well under it).
   Then the hook's test suite again.
   **The project's own docs are rewritten too**, as local changes listed in the report and the
   commit body, wherever they give the agent a command the new hook refuses:
   - a branch or worktree created from the default branch without `--no-track`
     (`git switch -c <b> origin/<default>`, `git checkout -b …`, `git worktree add -b <b> <dir>
     origin/<default>`, often followed by `git branch --unset-upstream`) → the same command with
     `--no-track`, the `--unset-upstream` step dropped;
   - an agent merge (`gh pr merge …`) → the merge route, `gh pr merge <n> --<method>
     --match-head-commit <sha>`, alone in its call; "only the owner merges" rules → per pull
     request, as in `CONTRIBUTING.md` §2;
   - a status posted with `--input` → `-f` fields.
   This applies to `CLAUDE.md`, `AGENTS.md`, `docs/CONTRIBUTING.md` and any doc or skill of the
   project that carries such a command (search them for `origin/<default>`, `worktree add`,
   `gh pr merge`).
5. Never touch: `openspec/specs/`, `openspec/changes/`, the reverse-documentation (`ARCHITECTURE.md`,
   module docs, glossary, ADRs, roadmap) — it belongs to the project.
6. Phase 5 of `SKILL.md` (checks), then one commit `chore(sdd-init): refresh workflow to <version>`
   listing in its body what comes from the kit and the local differences kept. Marker updated.
