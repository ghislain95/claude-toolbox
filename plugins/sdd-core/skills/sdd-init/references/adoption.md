# Adopting a project that already has tooling, and `--refresh`

## 1. Adoption mode: the project already has its own agent environment

**Adoption mode** applies when the project has rules, agents or hooks of its own (`CLAUDE.md` or
`.claude/CLAUDE.md`, `AGENTS.md`, `.claude/agents/`, `.claude/hooks/`, `.claude/skills/`,
`openspec/`) and no kit marker (§2). Rule: **what exists was written for a reason.** Merge, don't
overwrite — and say beforehand, file by file, what will happen.

### 1a. The mapping table comes first, approved before any write

Right after the recon (`SKILL.md` phase 1, steps 1 to 3, which only read), and **before writing any
file** (the reverse-documentation included), build the mapping table and show it to the owner at
validation gate 1, with the recon summary. Nothing is written until the owner approves it; their
corrections change the table, then the table is the plan.

1. Read every existing rule-bearing file in full: the rule files, each agent, each hook and its tests,
   `settings.json`, the vendored skills and commands, `openspec/config.yaml`, the CI workflows, the
   deploy configuration (`vercel.json`…), the docs the rules point to. A long file is mapped **section
   by section**: rules of one kind often live in a section of a file of another kind (git rules in a
   CLAUDE.md section, conventions in AGENTS.md).
2. One row per existing file or section, and one row per kit file that has no counterpart:

   | Existing (file § section) | Kit (file § section) | Decision | Reason |
   |---|---|---|---|

   - **keep** — project-specific, the kit has nothing equivalent, or the project's text is more
     precise: it stays where and as it is (the kit's files point to it when they need it).
   - **merge** — both cover the subject: the kit's mechanics go in (commands, gates, steps the hook
     and the checks rely on), the project's specifics stay (its names, paths, pitfalls, examples),
     **in the project's language**.
   - **replace** — the kit's version supersedes the project's (typically a second guardrail, a vendored
     copy of a skill the plugins now carry); always with the reason, and with what of the project's
     version is carried over.
   - **create** — a kit file the project lacks (`.sdd/*`, the merge-conditions workflow…).
   - **decide** — an existing rule the workflow contradicts ("only the owner merges", "commit straight
     to main", a branch command the hook refuses): the row states both sides and the owner settles it
     at gate 1. Never decided alone.
3. **Language**: the project's prose language stays. A French `CLAUDE.md` stays French; the kit
   sections merged into it are translated into French. Phase 2's language question defaults to the
   existing docs' language and only asks when they mix languages.
4. **Location**: the project's layout stays. A project whose rules live in `.claude/CLAUDE.md` keeps
   them there (no second, root `CLAUDE.md` that would drift from it); the install marker goes on that
   file's last line, and only there — the version check reads both files and flags a marker in each.
5. Show the table, the files counted by decision, and every **decide** row as a question. Wait for the
   approval. Then the per-file rules of §1b apply to each row.

**Worked example — geomni** (rules in a French `.claude/CLAUDE.md` that imports `../AGENTS.md`; a
Python guardrail; vendored skills; a backlog file instead of a roadmap). Excerpt of its table:

| Existing (file § section) | Kit (file § section) | Decision | Reason |
|---|---|---|---|
| `.claude/CLAUDE.md` (French, `@../AGENTS.md` import) | `CLAUDE.md` | merge, in place | the rules stay in `.claude/CLAUDE.md`, in French; no root `CLAUDE.md`; the marker goes on its last line |
| `.claude/CLAUDE.md` §1 "Workflow SDD (OpenSpec)": `/opsx:new` → passe adversariale → `/opsx:ff` → GO apply → `/opsx:apply` → `code-reviewer` → `/opsx:verify` → PR 1 → merge owner → vérification post-déploiement → PR 2 archive | `CLAUDE.md` §3 cycle | merge | same two-PR cycle; the kit adds the classification and the framing PR (it replaces the chat "GO apply"), the review harness (the `code-reviewer` agent becomes its conventions angle), the intent QA with `/local-qa:qa-prepare`, the verified merge route; kept: the three graphify refresh points, the post-archive status `✅ SHIPPED` in `docs/particulier/Geomni_Backlog_OpenSpec.md`, `/web-design-guidelines` and `/review-animations` on UI diffs (→ interface angle in `.sdd/harness.yaml`) |
| §1 "Branches, commits et PR", rule 4 "Seul l'owner merge" | `CONTRIBUTING.md` §2 "Who merges" | decide | the kit merges ungated pull requests through the verified route; the owner keeps every gated one |
| §1 "Branches, commits et PR", rule 1: `git worktree add -b feat/<id> … origin/main` then `git branch --unset-upstream` | `CLAUDE.md` §7, `CONTRIBUTING.md` §2 | merge | the same command with `--no-track` (the kit's hook refuses a branch tracking `main`), the `--unset-upstream` step dropped; kept: the worktree folder, copying `.env.development.local` and `settings.local.json`, `npm install`, `graphify update .`, the Docker services shared with the main checkout |
| §1 rules 2, 3, 5–8 (commit per task group, squash, post-deploy verification, archive PR, cleanup, hotfix) | `CLAUDE.md` §3 and §7, `OPENSPEC_GUIDE.md` §8 | merge | same steps; squash → `MERGE_METHOD=squash` |
| §2 "Routage des rôles" (10 agents, `rendering-dev` > `frontend-dev`) | `CLAUDE.md` §8, `.claude/agents/` | merge | the project's agents and tie-break rule kept; the kit's description blocks and output formats added agent by agent |
| §3 "Self-review" (`.claude/commands/review.md`) | `CLAUDE.md` §7 | keep | the project's own two-pass review command |
| §4 "Graphify" | `CLAUDE.md` §10, `docs/GRAPHIFY.md` | keep | more precise than the template (hub value objects, `god-nodes` bias); the template's `--force` rule is already there |
| §5 "Boîte à outils" | `CLAUDE.md` §11 | merge | `/passation` → `/handoff:passation`; adds `/sdd-core:review-harness`, `/local-qa:qa-prepare` |
| "Garde-fou" paragraph, `.claude/hooks/block-git-writes.sh` → `git_guardrails.py`, `test_git_guardrails.py` | `.claude/hooks/block-git-writes.{sh,pl,test.sh,conf}` | replace | one guardrail: the kit's already carries the Python one's cases (REST merge endpoint, branch tracking `main`), plus the merge route; `--force-with-lease`, allowed today → `ALLOW_FORCE_WITH_LEASE=1` |
| `.claude/skills/` (passation, retro, domain-modeling, web-design-guidelines…, vendored copies) | plugins `handoff`, `sdd-core`, `sdd-ui` | replace | the plugins carry them; a copy drifts. `graphify` and the `openspec-*` skills stay (installed by their own tools) |
| `.claude/commands/migrate.md`, `ticket.md` | — | keep | project-specific commands |
| `AGENTS.md` (English, cross-tool) | `AGENTS.md` | keep, plus a "Claude agent team" section | the project's cross-tool file; its git paragraph ("only the owner merges") follows the **decide** row above |
| `.github/workflows/pr.yml` (guardrail tests), `deploy-backend.yml`, `frontend/vercel.json` | `tooling.yml`, guard block of `deploy.yml`, `ignoreCommand` | replace / merge / merge | the guardrail job goes with the Python guardrail; the deploy job and Vercel get the deploy guard (diff shown) |
| — | `.sdd/triggers.yaml`, `deployment.yaml`, `harness.yaml`, `.sdd/bin/`, `merge-conditions.yml`, `deploy-alert.yml` | create | |
| `docs/Geomni_*_Architecture.md`, `docs/Geomni_Testing_Strategy.md`, the ADR | `docs/ARCHITECTURE.md`, module docs | keep | the reverse-documentation exists: the generated rules point to these files instead of new copies |
| `docs/particulier/Geomni_Backlog_OpenSpec.md` | `docs/ROADMAP.md` | keep | it is the roadmap; the post-archive step names it |

### 1b. Per-file rules once the table is approved

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

With the files written, show the owner the diff of every merged file (summary: sections added /
kept / in conflict) before the commit.

## 2. Install marker

Last line of the generated `CLAUDE.md` (in adoption mode, of the file that holds the project's rules:
the root `CLAUDE.md`, or `.claude/CLAUDE.md` when the project keeps them there — the version check
reads both):

```markdown
<!-- claude-toolbox: installed <sdd-core plugin version> (<toolbox commit>) on <YYYY-MM-DD> — options: <list> -->
```

It is what `--refresh` relies on. Read the version in the plugin's `.claude-plugin/plugin.json` (two
levels above this skill) and the commit with `python3 <base directory>/scripts/refresh_merge.py
install-sha --skill-dir <base directory>`: Claude Code's record of the installed plugin
(`installed_plugins.json`, its `gitCommitSha`), else the kit's clean git checkout. When it answers
`"sha": null` (a kit with uncommitted changes, an unknown install), write the marker without the
parenthesis and say in the report that the next refresh will merge two ways. The commit, not the
version, names the templates: one version number has shipped several template sets. Markers written
before 0.4.0 have no commit; markers written before the autonomy levels were removed end with
`— autonomy: <level>`: both still read (§3), never written again. Only one file carries the marker: a
project with a marker in both `CLAUDE.md` and `.claude/CLAUDE.md` gets a notice from the version check
(the highest version is compared); the refresh keeps the one in the file that holds the rules.

## 3. `/sdd-init --refresh` — resync with a newer version of the kit

1. Read the marker: `python3 <base directory>/scripts/refresh_merge.py read-marker CLAUDE.md
   .claude/CLAUDE.md` (`claude-toolbox: installed …`, or `sdd-kit: installed …` for a project set up
   before the catalog was renamed — rewritten to the new form): installed version, toolbox commit (null
   before 0.4.0), options, and the former `autonomy` level if the marker still has one (it only feeds
   step 4's report; the new marker drops it). `conflict` → the owner says which file keeps it. Missing
   (exit 3) → this project was not set up by the kit: offer a full install in adoption mode (§1).
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
   step 7), never rewritten when present (new keys of the template are listed in the report).
   `.claude/settings.json` keeps its JSON union, the hook files are replaced (step 4). Every other
   template-generated file is merged **three
   ways** — base: the templates of the recorded version; ours: the project's file; theirs: the new
   template — so that a local edit and a kit change are told apart by construction, not guessed:
   - **Base** — `python3 <base directory>/scripts/refresh_merge.py fetch-base --sha <the marker's
     commit> --dest <tmp>/base` (`<tmp>` from `mktemp -d`): a shallow fetch of exactly that commit of
     `https://github.com/ghislain95/claude-toolbox`, checked to be that commit, of which only the
     `templates/` folder is kept, in a temporary directory; no template copy is ever stored in the
     project. Never pass `--repository` (it exists for the script's tests; when set, the JSON says
     `repository_override` and you report it). No commit in the marker (a project set up before
     0.4.0), or exit 3 (`missing-commit`, `unreachable`: no network or no access) → **two-way
     fallback** for every file: the report says so, with the reason. Release tags
     (`sdd-core-v<version>`) are for people; the refresh never reads them.
   - **Fill base and theirs alike** — the recorded version's template into `<tmp>/base-filled/<path>`,
     the new template (this skill's `templates/`) into `<tmp>/new-filled/<path>`, both with the
     **same** project values, read back from the current files, never deduced again: the same
     variables, the same `sdd:if` resolution (the marker's options), and for each `sdd:fill` or
     `sdd:each` block the project's current text of that block, copied into both. The only differences
     left between the two are then the kit's. A project whose docs are in another language than the
     templates: translate the base, then build theirs from the translated base by applying, translated,
     only the lines the raw templates changed between the two versions (an unchanged line keeps the
     base's translation word for word — a fresh translation of it would read as a kit change).
   - **Merge** — a manifest, `[{"path": "<project file>", "base": "<tmp>/base-filled/…" or null,
     "theirs": "<tmp>/new-filled/…"}]` (`base` null when there is no base commit; a base path that does
     not exist when the recorded commit had no such template), then `python3 <base
     directory>/scripts/refresh_merge.py merge --manifest <file> --old-version <recorded> --new-version
     <current>`. It checks every entry first — two paths that are the same file (a symlink) refused, a
     file that is not UTF-8 refused, a file still holding a conflict-marker line neither template carries
     (a leftover of an earlier refresh, fenced code blocks included; an example line the kit ships in a
     code block is accepted) refused — and
     merges them all in memory with `git merge-file --diff3` (a CRLF file merged and written in CRLF);
     nothing is written unless every entry could be merged (exit 2 otherwise, the reason in the JSON).
     The new contents are all staged in temporary files first, then put in place; a failure while
     staging writes nothing, a failure while putting them in place exits 2 with `written` and
     `not_written` — report both, never a partial refresh as done.
     It reports each file: `merged`, `unchanged`, `created` (a template new in the kit, absent from the
     project), `deleted_locally` (the project deleted a file the recorded commit had: not created
     again), `two_way` (exit 4: no base — `no-base-commit`, or `new-in-kit` when the project already
     has a file the recorded commit had no template for; the file is left untouched and the
     differences are listed as `hunks` — apply what plainly comes from the kit, keep the local version
     when in doubt about where a difference comes from, list it), `conflicts` (exit 1: the same lines
     changed on both sides).
   - **Conflicts go to the owner**, never resolved by picking a side: the file carries the markers
     `<<<<<<< local`, `||||||| kit <recorded>` (the base), `=======`, `>>>>>>> kit <current>`; show
     each one to the owner with both sides and the base, apply their answer, and commit nothing while a
     marker is left (phase 5: `git diff --cached --check` on everything staged and the marker grep over
     every path of the manifest).
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
   listing in its body the merge's outcome per file (merged, conflicts and the owner's answers,
   two-way fallback and why), what comes from the kit and the local differences kept. Marker updated
   to the new version and the commit `install-sha` gives: it is the next refresh's base.
