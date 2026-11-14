# Design — dev-factory

## Context

See `proposal.md` for the why and the owner decisions. Constraints that shape the approach:

- **GitHub Free, private projects.** geomni (and wifisense) have no rulesets, no branch protection, no
  auto-merge; the agent acts with the owner's token. Merge protection is therefore client-side; the
  server-side barrier is the deploy pipeline (proposal, decision 1). The toolbox itself is public, so
  rulesets are available to it for free.
- **Existing assets.** The kit (`sdd-core` 0.2.0) already has `sdd-init` with an adoption mode and a
  `--refresh` (`references/adoption.md`), the perl guardrail (`block-git-writes.{sh,pl,test.sh,conf}`,
  197 cases) and a version-check session hook. The mods (`claude-mods`) are function-hook plugins with a
  `shared/` folder synced into each mod by `scripts/sync-shared.sh`, already listed in the kit's catalog
  through `git-subdir` sources.
- **geomni specifics.** Squash-only merges; `deploy-backend.yml` deploys on push to `main` filtered on
  `backend/**`; Vercel deploys the front on every push; a daily ETL scheduler runs repository code;
  path-filtered CI workflows; a Python guardrail (55 cases) with rules the kit lacks (REST merge
  endpoint, branch tracking `main`, `--force-with-lease`).
- **Owner's working mode.** Sequential agents, one heavy build at a time, normal or high effort.

## Goals / Non-Goals

**Goals:**
- Every rule the specs state is either checked mechanically or explicitly documented as honour-based.
- One source per fact: triggers, deployment profile and harness settings live in one project folder
  read by the hook, the CI checks and the skills alike.
- The owner's interventions are clicks and short chat answers, never commands.

**Non-Goals:**
- Defending against an agent that deliberately circumvents the hook (out of reach without GitHub Pro).
- Rewriting the mods; they only move.
- Supporting forges other than GitHub.

## Decisions

### D1 — Catalog layout and the fold of claude-mods

```
claude-toolbox/
  .claude-plugin/marketplace.json     name "claude-toolbox", every entry with a category
  plugins/sdd-core/                   workflow (sdd-init, review harness skills, templates)
  plugins/sdd-ui/                     optional UI skills
  plugins/handoff/                    skills/passation (former sdd-core:passation)
  plugins/local-qa/                   QA environment skill (usable outside SDD)
  mods/<mod>/ , mods/shared/, mods/scripts/   the four mods, unchanged inside
  openspec/                           the toolbox's own specs
```

`claude-mods` is imported with `git subtree add --prefix=mods` so its history is kept; catalog entries
switch from `git-subdir` to `./mods/<mod>`. **Why subtree:** keeps history without a tool the owner
lacks (`git filter-repo`) and leaves no submodule to fetch. Alternative rejected: submodule (Claude
Code fetches it, two repos to keep in sync — the very drift we remove).

`local-qa` is its own plugin because preparing a QA environment is useful outside the spec-driven
workflow (rule "one plugin per usage"); `sdd-core` depends on `handoff` and `local-qa`.

### D2 — Rename procedure

1. Rehearse on a scratch `CLAUDE_CONFIG_DIR`: add `sdd-kit` from a local clone, install, then switch
   to the renamed catalog and record what Claude Code does (re-add, plugin data kept or lost).
2. `gh repo rename claude-toolbox` (owner confirmation — outward-facing; GitHub keeps a redirect).
3. Marketplace `name` → `claude-toolbox`; README install prompt and every hard-coded
   `marketplaces/sdd-kit` path updated.
4. Install marker becomes `claude-toolbox: installed <version>`; `check-kit-version.sh` accepts both
   markers for one minor version.
5. `claude-mods` repository: README points to `claude-toolbox`, then archived (owner confirmation).
   The owner's `local-mods` directory marketplace is replaced by the local clone of `claude-toolbox`.

### D3 — The project's factory folder `.sdd/`

One versioned folder per project, read by the hook, the CI and the skills:

| File | Content |
|---|---|
| `.sdd/triggers.yaml` | intent and irreversible triggers (path globs, content regexes), plus the non-waivable gate-machinery list |
| `.sdd/deployment.yaml` | deploy targets (trigger, rollback command, probes), scheduled jobs (schedule, code paths), or `deploys_nothing: true`; schema in the template `OPENSPEC_GUIDE.md` §8, checked by `merge_conditions.py validate` |
| `.sdd/harness.yaml` | angles per risk, mechanical tools available, budget (minutes, tokens), effort |
| `.claude/hooks/block-git-writes.conf` | guardrail settings (stays next to the hook it configures) |

The gate-machinery list always includes `.sdd/**`, `.claude/hooks/**`, `.claude/settings.json`,
`.github/**`, `.gitattributes`, `.gitmodules`, `openspec/config.yaml`, `vercel.json` and every
`classification.yaml` touched outside a framing pull request (amended after the lot 3a review, D5).
**Why one folder:** the adversarial pass showed rules scattered across CLAUDE.md, hook and CI drift
apart; a single folder is the one place the gate-machinery trigger has to protect.

### D4 — Classification storage and approval: the framing pull request

Each change gets `openspec/changes/<id>/classification.yaml` (gates, evidence, waived triggers with
reason). **Approval is the owner merging a framing pull request** that carries only the proposal and
its classification. That puts the approved classification on `main` before apply, which is where every
check reads it from, and makes the approval an act on GitHub rather than a chat message.

- Alternatives rejected: approval recorded in the change branch (the PR would certify itself —
  adversarial objection 2); a label or comment (indistinguishable from the agent, who uses the owner's
  token).
- The framing PR touches `openspec/` only: no deploy target picks it up (D7).
- Reclassification during apply: the agent opens a new framing PR amending `classification.yaml`; the
  change PR waits for it.

### D5 — The `merge-conditions` check

A workflow `merge-conditions.yml` triggered by `pull_request_target` (runs the definition on `main`, so
a PR cannot edit its own check) and by `workflow_run` of the project's CI workflows. It never executes
PR code: it fetches the head commit as data and computes the diff against `main`. It sets a commit
status `merge-conditions` on the head commit:

- **success** only when: every CI workflow the diff requires has a successful run on the head commit
  (aggregate gate — the required set is computed from the same path filters, so a PR outside every
  filter is still judged); commit statuses `review-harness` and `opsx-verify` are success on the head
  commit; the diff's trigger hits are all accounted for by the approved classification.
- its **description** lists the open gates: `gates: none`, `gates: intent`, `gates: irreversible`,
  `gates: intent+irreversible`.

`review-harness` and `opsx-verify` statuses are posted by the agent with `gh api` when those steps
pass. They are honour-based (the agent could post them falsely) but mechanical: forgetting them blocks
the merge. Stated as such in the contributing guide.

Amended after the lot 3a review:
- The verdict depends on `main` (triggers, classifications, workflow filters). A `push` to the default
  branch re-judges every open pull request into it, and the description carries the judged base
  (`base <short sha>`); the merge route (D6) refuses when that base is not the current default-branch
  head.
- The status is spoofable (a workflow the PR adds can overwrite it; so can the agent's token). It
  remains the input of the client-side merge rule — against mistakes — and the deploy guard (D7)
  recomputes the verdict instead of reading it.
- Built-in gate machinery covers everything that changes what CI or the check does: `.github/**`,
  `.sdd/**`, `.claude/hooks/**`, `.claude/settings.json`, `.gitattributes`, `.gitmodules`,
  `openspec/config.yaml`, `vercel.json`, and any `classification.yaml` added, modified or deleted
  outside a framing pull request — not only the ones already on `main`.
- A change pull request must touch its own change folder, and the folder and the branch name must
  agree; touching another change's folder is an error. A missing `.sdd/triggers.yaml` on `main` is an
  error, never "defaults only".

### D6 — The guardrail: one perl implementation, one verified merge route

The kit's perl reader is kept (most cases, per-project `.conf`, already in the kit's CI). Added:

- geomni's cases ported as tests: REST merge endpoint `PUT …/pulls/N/merge`, `gh pr merge --auto`,
  branch tracking a protected branch, `--force-with-lease` allowed when `ALLOW_FORCE_WITH_LEASE=1`.
- `MERGE_METHOD=squash|merge` (`rebase` refused: after a rebase merge no single commit of the default
  branch marks "before this pull request", which the deploy guard needs); `ALLOW_PR_MERGE` and the three autonomy levels are removed (the
  change decides, not the project). **BREAKING** for wifisense's `.conf`, handled by its adoption.
- The single merge route: `gh pr merge <n> --<MERGE_METHOD>`. Before allowing it the hook queries
  GitHub for the PR's head SHA and the `merge-conditions` status of that SHA; it allows only `success`
  with `gates: none`, and blocks when the query fails (fail closed). It also blocks while another PR of
  the repository carries the `in-flight` label (D8).
- geomni's Python guardrail and its `pr.yml` job are removed by geomni's adoption.

Settled while implementing (group 7, then its review): the merge command names the head it
checked (`--match-head-commit <sha>`, required, equal to the PR's head on GitHub, so a push racing
the merge makes GitHub refuse it) and runs alone (one merge per command, only read-only git/gh
commands around it, `gh pr edit <n> --add-label in-flight` after it). The hook queries, within one
40-second deadline (the hook's timeout in `settings.json` is 120 s), `gh repo view` (repository and
default branch, resolved where the command runs), `pulls/<n>` (open, base = default branch, head
SHA), `commits/<sha>/statuses` (the newest `merge-conditions` entry, which must have been posted by
`github-actions[bot]`), `branches/<default>` (the `base <sha7>` of the description must be its head)
and `issues?labels=in-flight&state=all`, paginated (the search API behind `gh pr list` lags; this
needs Issues read on the token); "in flight" is the label on any other pull request whatever its
state. The agent can no longer post `merge-conditions` (blocked in `gh api`), and `-R`/`--repo`
anywhere, `GH_REPO`/`GH_HOST` anywhere in the command are refused so the checked repository is the
merged one; every unknown option is refused; `gh pr merge <n> --disable-auto` alone stays allowed. Tracking a protected branch includes git's
implicit tracking (`branch.autoSetupMerge`): `git switch -c x origin/main` needs `--no-track`.
`gh api` writes to `git/refs/heads/<protected>` and to `contents/`, `/merges`, and the GraphQL
mutations that merge or write a branch are blocked too. Without a `.conf` line, `MERGE_METHOD`
defaults to `merge`, the method the former hook enforced.

Alternative rejected: keep the Python version — fewer cases, no `.conf`, not in the kit's CI.

### D7 — The deploy guard

A script shipped by the kit, `.sdd/bin/deploy-guard.sh <sha>`: finds the PR merged as `<sha>`
(`GET /repos/{o}/{r}/commits/{sha}/pulls`), requires it merged, then **recomputes the verdict itself**
inside the deploy pipeline — `merge_conditions.py match` with the default branch before the merge as
base (the push event's `before`, never `<merge>^1`) and the PR head as head, plus the aggregate CI condition on the PR head — instead of trusting the
`merge-conditions` status. Amended after the lot 3a review: a commit status can be overwritten by any
workflow the pull request adds (every writer is `github-actions[bot]`) and by the agent's own token,
so the status is an input of the client-side merge rule only, never of the server-side barrier. Any
gates pass (an owner-merged gated PR deploys); an `unaccounted` hit, a red or missing required CI run,
or a direct push without a PR exit non-zero.

- geomni `deploy-backend.yml`: first step of the job, plus `concurrency: deploy` (amended after the
  lot 3c-1 review: one group per workflow, `deploy-<workflow>`) so two deploys never
  overlap.
- Vercel: `ignoreCommand` in `vercel.json` runs the guard (exit 0 = skip) and also skips when the
  commit has no frontend change. It needs a read-only fine-grained token in Vercel's environment
  (owner action).
- A refused deploy alerts the owner: failed workflow notification for the backend; for Vercel, the
  skipped build plus a GitHub issue opened by a `push` workflow that runs the same guard.

Settled while implementing (group 8): the logic is a `deploy-guard` subcommand of
`merge_conditions.py` (it reuses `match`, the required-workflow computation and the run verdicts
in-process, and its tests join the matcher's suite, which the toolbox's CI already runs), and
`.sdd/bin/deploy-guard.sh` is the per-platform entry point: `deploy-guard.sh <merged-sha>
<before-sha>` in a GitHub Actions job (exit 0 = deploy), `deploy-guard.sh --vercel [<globs>]` as
`ignoreCommand` (exit 1 = build only when the guard says deploy and the push changed a path under
the globs; every other outcome, a crash included, skips; an explicit preview builds unguarded).
Vercel is not given the push event, so `before` is read from the repository activity
(`GET /repos/{o}/{r}/activity`, the entry whose `after` is the commit) — never `<merge>^1`. Added
rules: the pushed commit's first parent must be `before` (the push carried the merge and nothing
else), and the guard fetches the default branch and `refs/pull/<n>/head` itself, with the token in
an HTTP header, deepening a shallow clone. The guard reads GitHub through HTTPS with a token
(`DEPLOY_GUARD_TOKEN`, `GH_TOKEN` or `GITHUB_TOKEN`), no `gh`. The `review-harness`/`opsx-verify`
statuses are not part of the guard (honour-based, D5). `vercel.json` is gate machinery wherever it
lives (`**/vercel.json`): geomni's is `frontend/vercel.json`. Known limits, stated in the
contributing guide: a deploy that bypasses the pipeline is not guarded; a refused commit stays on
the default branch and ships with the next merge unless reverted; `concurrency` keeps one waiting
run, so a third push can replace the second's run.

Amended after the lot 3c-1 review: **what the guard enforces** is a merged pull request, every
trigger hit accounted for, the CI the pull request needed, and a clean history since the target's
last deployment — **not the owner's gates**. Without another identity for the agent, owner and agent
merges look the same server-side; the gates stay client-side (the merge route). Fixes:
- *History*: every first-parent commit since the last deployed commit is judged (GitHub Actions:
  the head of the last successful run of the same workflow on the default branch; Vercel:
  `VERCEL_GIT_PREVIOUS_SHA`; none yet: the push alone). A refused commit blocks every later deploy
  until a later merged commit that passes the guard undoes it exactly; a rewritten history (the last
  deployed commit no longer an ancestor), a force-push or more than 100 commits are left to the
  owner. The merge route also refuses an agent merge while an open issue carries `deploy-refused`
  (the label `deploy-alert.yml` puts on a refusal).
- *Self-hosting*: the guard's code (`deploy-guard.sh`, then `merge_conditions.py`) is read from that
  trusted commit (git, else the contents API), never from the pushed one. Residue: the workflow
  files and `vercel.json` run from the pushed commit (GitHub and Vercel read them there); the agent's
  token has no `workflow` permission; a direct push by the owner is not stopped. The interface
  between the entry point and `deploy-guard.sh` (`<merged> <before> <trusted>`, `--vercel [globs]`)
  is therefore frozen: the trusted copy is older than the entry point that calls it.
- *Evil merge*: the commit's tree must equal `git merge-tree --write-tree <parent> <pr head>`.
- *Control characters*: globs match across newlines; a file name with a control character is an
  error, and every printed name or reason is escaped.
- *Vercel*: the `ignoreCommand` downloads the trusted guard and builds only on its explicit "build"
  (`[ $? -ne 1 ]`); the activity lookup is asked again before giving up; probes assert the served
  revision; after `vercel rollback`, production assignment is turned back on by a promotion.
- *Manual runs* (`workflow_dispatch`): only on the default branch; the commit's parent stands for
  `before`, the history check covers the rest. *Concurrency*: one group per deploy workflow.
- *Adoption*: a distinct outcome (exit 4), alerted as expected, not as a refusal.
- *PyYAML*: hash-pinned wheels in a fresh `mktemp -d` environment.
- *Workflows*: a run whose jobs were all skipped passes; a renamed required workflow stays required.

Amended after the lot 3c-1 re-review: a candidate trusted commit (the last successful run's head,
the owner's reset, `VERCEL_GIT_PREVIOUS_SHA`) counts only when it is on the pushed commit's
first-parent line — checked by the entry point before any of its code runs, and again by the guard
(`--last-deployed` off that line is refused); Vercel's shallow clone is deepened with the read-only
token first. A deploy job names its target (`DEPLOY_GUARD_TARGET`): only the commits since the
trusted one that change that target's trigger paths, read from the trusted commit's
`.sdd/deployment.yaml`, are judged, so a refused commit elsewhere never blocks it. When a target is
stuck anyway, the owner sets the repository variable `DEPLOY_GUARD_RESET_<TARGET>` to a reviewed
commit of the default branch (only the owner can: the agent's token has no Variables write).
Documented limits: a renamed deploy workflow starts from `before` (the owner renames workflows and
sets the reset); `workflow_dispatch` on an old branch runs that branch's unguarded workflow (fix:
deploy credentials bound to the default branch and the deploy workflow).

### D8 — Serialisation and rollback

- After merging, the agent puts the `in-flight` label on the merged PR; the hook refuses any other
  merge while one exists. The label is removed when verification passes or rollback completes.
  Client-side, like the rest of the merge protection; the deploy `concurrency` group is the
  server-side half.
- Verification window: `.sdd/deployment.yaml` scheduled jobs whose code paths intersect the diff extend
  verification until their next run has succeeded.
- Rollback: run each affected target's `rollback` command from `.sdd/deployment.yaml` (geomni:
  `gcloud run services update-traffic … --to-revisions=<previous>=100`, Vercel: promote the previous
  production deployment), then `git revert` on a `revert/<id>` branch. The revert PR carries a
  classification `revert-of: <id>` with both gates closed, which the check accepts only if the diff is
  the exact inverse of the merged change; its harness is limited to that verification.

Settled while implementing (group 8): the revert's marker is a new file
`openspec/changes/<id>/revert.yaml` (`revert_of`, `merge_commits` — amended after the lot 3c-1
review —, `reason`), not a key of
`classification.yaml` — editing a classification outside a framing PR is gate machinery, and the
approved classification must stay the one on the default branch; the unused `revert_of` key is
removed from the classification schema. A pull request that **adds** that file is of kind `revert`:
from `revert/<id>` only, its merge commit on the base ref's history and touching
`openspec/changes/<id>/`, and its diff, `revert.yaml` aside, exactly the inverse of that commit's
diff against its first parent (path, blob and mode of every file); anything else is an error. Its
gates: none, except irreversible when the reverted change had that gate open (fixed forward: the
owner decides) or the revert touches gate machinery; it needs no `review-harness`/`opsx-verify`.
The label moves: removed from the change's PR, put on the revert's PR in its merge command, removed
once the revert's deploy is verified. The merge command carries the label itself
(`gh pr merge … && gh pr edit <n> --add-label in-flight`, which the hook allows); after an owner
merge the agent labels it in its next call. Amended after the lot 3c-1 review: the listed merges
must be on the base ref's first-parent line, include the newest one that touched the change folder
and, where the API is at hand (the check, the guard), be merge commits of merged pull requests from
the change's own branches; several lots are reverted together (their diffs composed). The intent
gate opens when the reverted change had it open and is not the change in flight (its pull request
carries no `in-flight` label): undoing behaviour the owner approved is the owner's call.

### D9 — Review harness as skills

`sdd-core/skills/review-<angle>` (eight skills) plus `review-harness`, the orchestrator the session
runs after apply:

- Bug hunting delegates to Claude Code's `/code-review` and security to `/security-review` instead of
  re-implementing them; the other angles are written for the kit.
- Angle selection from `.sdd/harness.yaml` and the diff; agents run **sequentially**; one combined
  adversarial verifier per round checks every BLOCKER/MAJOR (owner's light mode), not one agent per
  finding.
- Mechanical backing per angle is declared in `.sdd/harness.yaml` (e.g. geomni: ArchUnit, ESLint,
  build size; mutation: absent until PIT/Stryker are added — a backlog line, not part of this change).
- Report written to `openspec/changes/<id>/review.md` (rounds, findings, refutations, angles not run),
  then the `review-harness` status is posted.

### D10 — `local-qa` environment

- Inventory: `docker ps` with compose labels (`com.docker.compose.project`, working dir) and
  `lsof -iTCP -sTCP:LISTEN` with each process's cwd, mapped to project and worktree.
- Started services are recorded in `.claude/qa/started.json` of the worktree; cleanup stops exactly
  those.
- Reuse rule: same project and no pending migration → reuse; pending migration → an isolated database
  under a compose project named after the worktree.
- The QA brief is a message in the conversation (rendered as a QA card by `conversation-cards`): link,
  3–6 points of gesture and expected result, captures.

### D11 — `sdd-init`: new generated files, adoption table, three-way refresh

- Templates added: `.sdd/*.yaml`, `merge-conditions.yml`, `deploy-guard.sh`, the `in-flight` label,
  contributing guide section "what is enforced where".
- Adoption mode starts with a mapping table (existing file/section → kit file/section → keep / merge /
  replace), approved by the owner before any write.
- Marker records the version; `--refresh` fetches that version's templates from the toolbox's git tag
  `sdd-core-v<version>` as the merge base. No template copy is stored in projects.

## Risks / Trade-offs

- [Merge protection is client-side] → deploy guard server-side; contributing guide states the limit;
  GitHub Pro + App stays a backlog line.
- [`review-harness`/`opsx-verify` statuses are honour-based] → they prevent omission, not lies; the
  review report is in the PR for audit.
- [`pull_request_target` runs with write token] → the workflow never checks out PR code into a run
  path; it reads blobs with `git show`; reviewed under the gate-machinery trigger.
- [Framing PR adds a step] → it replaces the chat GO, it is one click, and it makes the approval
  checkable.
- [Vercel guard needs a token in Vercel] → read-only, scoped to the repository; owner creates it once.
- [Stricter irreversible gate means more owner merges on backend changes] → accepted by the owner
  (proposal decision 2); revisited with evidence later.
- [Rename breaks existing `sdd-kit` installs] → rehearsal, compatibility markers for one version,
  README notice.

## Migration Plan

Lots as in the proposal. Lot 1 also protects the toolbox's own `main` with a GitHub ruleset (free, the
repository is public) requiring the toolbox's `merge-conditions`. Until lot 3 ships, the owner merges
every PR. geomni's adoption (lot 4) lands as a `chore/sdd-init` PR the owner merges; the first real
geomni change after it is the pilot, followed end to end. wifisense follows once the pilot is verified.
Rollback of the whole change: geomni's previous `.claude/` and workflows are restored by reverting the
adoption PR; the toolbox keeps the `sdd-kit` compatibility markers.

## Open Questions

- Exact Vercel CLI command to promote the previous deployment from the agent's machine, to be settled
  when writing geomni's `.sdd/deployment.yaml`.
- Whether the `in-flight` label should also be checked by the deploy guard; decided after the pilot.

## Follow-ups

- An identity of its own for the agent (a GitHub App) and GitHub Pro rulesets on the default branch:
  the only way for the server side to tell owner merges from agent merges, and so to enforce the gates.
- Deploy credentials bound to the default branch (Workload Identity Federation with an attribute
  condition on `refs/heads/main`), so a workflow edited elsewhere cannot deploy.
