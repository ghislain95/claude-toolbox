# {{PROJECT_NAME}} — OpenSpec guide (SDD)

> Practical guide to the Spec Driven Development workflow on {{PROJECT_NAME}}.
> Audience: developer (human or agent) working in Claude Code.
> Upstream reference: [OpenSpec](https://github.com/Fission-AI/OpenSpec), [`CLAUDE.md`](../CLAUDE.md), [`AGENTS.md`](../AGENTS.md).

---

## 1. The concepts in 30 seconds

- **`openspec/specs/<domain>/spec.md`** — the **source of truth**: how the
  system behaves *today*. Never edited by hand.
- **`openspec/changes/<change-id>/`** — a **change** = a proposed evolution,
  a self-contained folder: `proposal.md` (why), `specs/` (deltas: what),
  `design.md` (how), `tasks.md` (steps).
- **Delta** — a change declares `ADDED` / `MODIFIED` / `REMOVED` Requirements
  relative to the current specs, without rewriting them.
- **Archive** — `/opsx:archive` merges the deltas into `openspec/specs/` and
  archives the change. The only moment the specs move: the loop
  feeds itself.
- **`openspec/config.yaml`** — the project context and writing rules injected
  into every artifact (proposal, specs, design, tasks).

Specs are born **change by change**: an existing domain without a spec gets its own
from the first change that touches it (the `ADDED` delta then describes the current behaviour
it touches, not the whole domain). No massive reverse-spec: it is expensive and goes stale fast.

## 2. "I want to…" → what to do

| I want to | Action |
|---|---|
| Implement an epic/ticket from the roadmap | `/opsx:new <change-id>` then the full cycle (§3) |
| A feature not framed yet | `/opsx:new <change-id>` — `product-owner` frames it with you |
| Explore an idea without committing | `/opsx:explore` |
| Fix a bug that contradicts a spec | `/opsx:new fix-<bug>` |
| Trivial hotfix (< 30 min, specified behaviour intact) | Direct implementation on a `fix/…` branch, no change |
| Resume a change in progress | `/opsx:continue` or `/opsx:apply` |
| Check the implementation against the specs | `/opsx:verify` |
| Finish a delivered change | `/opsx:archive` |
| Fix a spec (typo, precision) | A small change (`/opsx:new fix-spec-<domain>`, `MODIFIED` delta) then `/opsx:archive` — `/opsx:sync` only carries the deltas of an **existing** change over into `specs/`; never a manual edit of `specs/` |
| Discover the cycle on a real example | `/opsx:onboard` |

## 3. The full cycle of a feature

```
/opsx:new <change-id> → classification → framing merge (approval) → /opsx:ff → /opsx:apply → /opsx:verify<!-- sdd:if github --> → PR 1 merged → verified in production → PR 2: /opsx:archive<!-- sdd:endif --><!-- sdd:if !github --> → /opsx:archive<!-- sdd:endif -->
```

With the agent team (routing: [`CLAUDE.md`](../CLAUDE.md) §8, details: [`AGENTS.md`](../AGENTS.md)):

1. **Framing** — `product-owner`: `proposal.md` (intent, scope, non-goals,
   testable criteria), roadmap epic referenced, and `classification.yaml` next to it (§7): the
   intent and irreversible gates, open or closed, each with its evidence.
1b. **Adversarial pass** — always, scaled: `architect` tries to break the proposal (a full
   attempt for a structural change — new module, new contract, migration, cross-cutting choice, new
   mechanism —, the five strongest objections for a small one), its classification included;
   objections are resolved in the proposal, or put to the user, before the framing merge.
1c. **Framing <!-- sdd:if github -->pull request<!-- sdd:endif --><!-- sdd:if !github -->merge<!-- sdd:endif -->** — branch `docs/<change-id>-framing`, carrying only the change
   folder (proposal, classification, `.openspec.yaml`)<!-- sdd:if github -->, opened as a pull request<!-- sdd:endif -->. **Its merge
   into `{{DEFAULT_BRANCH}}` by the owner is the approval**: the classification on
   `{{DEFAULT_BRANCH}}` is the one every check reads. No `/opsx:ff`, no apply before it is merged.
   A classification found wrong during apply is amended by a **new** framing branch
   (`docs/<change-id>-framing-2`, the classification and the proposal only); once it is merged, the
   change branch merges `{{DEFAULT_BRANCH}}` in and goes on. Editing the approved classification in
   the change branch never counts: the check reads `{{DEFAULT_BRANCH}}`'s version and treats the edit
   as gate machinery.
2. **Design** — `architect`, on the change branch `<type>/<change-id>` cut from
   `{{DEFAULT_BRANCH}}` after the framing merge: spec deltas (Given/When/Then, translatable 1:1 into tests) +
   `design.md` (owning module, migration yes/no, layer boundaries, decisions
   sourced at the pinned version).
3. **Implementation** — `<module>-dev`<!-- sdd:if multi-module --> / `full-stack-dev`<!-- sdd:endif -->: `tasks.md` ticked as
   it goes; `tester` checks: 1 delta scenario = 1 test.
4. **Verification** — `/sdd-core:review-harness <id>` (every review angle, findings adversarially
   verified, three fix rounds at most, report in `review.md`, commit status `review-harness`), then
   `/opsx:verify` (compliance with the deltas, tests actually run; when it passes, commit status
   `opsx-verify` on the pushed head, [`CONTRIBUTING.md`](CONTRIBUTING.md) §2).
<!-- sdd:if github -->
5. **Delivery** — implementation commit(s) by the agent on the change branch (Conventional
   Commits, [`CONTRIBUTING.md`](CONTRIBUTING.md) §2), push, PR 1 and its merge — by the agent through
   the verified route when `merge-conditions` reports `gates: none`, by the owner when a gate is
   open —, the `in-flight` label, the post-deploy verification, then PR 2 on `<type>/<id>-archive`:
   `/opsx:archive`, post-archive (`doc-writer` checks that `docs/` does not contradict the merged
   specs), commit `chore(<id>)`, and the final report (§8).
<!-- sdd:endif -->
<!-- sdd:if !github -->
5. **Archiving** — implementation commit(s) by the agent on the change branch (Conventional
   Commits, [`CONTRIBUTING.md`](CONTRIBUTING.md) §2), `/opsx:archive`, post-archive (`doc-writer`
   checks that `docs/` does not contradict the merged specs), commit `chore(<id>)`; finally a merge
   by a human ([`CONTRIBUTING.md`](CONTRIBUTING.md) §2).
<!-- sdd:endif -->

**Context hygiene**: a fresh context per phase (`/clear`, or `/handoff:passation` then a
new session) — the artifacts carry the memory.

## 4. Writing rules for specs and deltas

- **SHALL or MUST on the first line** of each requirement's text
  (the validator only reads the first physical line for this check).
- **Observable behaviour only**: endpoints, events, commands, exchange
  formats, error codes. No class names (→ `design.md`).
- `#### Scenario:` scenarios in GIVEN/WHEN/THEN, translatable 1:1 into tests.
- Cover the error cases (invalid input, duplicate, insufficient rights, unknown
  resource, limit reached), not just the happy path.
- Everything in **{{CODE_LANG}}** (like the code and the tests).
- The future does not go into the specs: an unimplemented epic = a future change
  (the intent lives in [`ROADMAP.md`](ROADMAP.md)).
- Any impact on {{DOMAIN_RISKS}} must be explicit in the proposal.

## 5. Useful CLI

```bash
openspec validate --all     # before every commit touching openspec/
openspec list               # changes in progress
openspec status             # state of a change's artifacts
openspec update             # after an upgrade of the npm package (regenerates /opsx:* and skills)
```

The CLI version is pinned in CI (`.github/workflows/openspec.yml`): bump it **at the same
time** locally and in CI, deliberately.

## 6. Known pitfalls

- ❌ Editing `openspec/specs/` by hand → archive/sync only. Single exception: the
  `## Purpose` section (deltas do not carry it), fixed in the archive commit of the change that
  makes it wrong (`CLAUDE.md` §3). CI (`.github/workflows/openspec.yml`) rejects a diff of
  `openspec/specs/` without `openspec/changes/`.
- ❌ SHALL/MUST pushed to the 2nd line by a line break → validation fails.
- ❌ Implementing a contract absent from the specs → a change is missing.
- ❌ Deviating from `design.md` without updating it.
- ❌ Forgetting `/opsx:archive` after delivery → the specs drift.
- ❌ Believing `/opsx:verify` finishes the work: it **audits**, it neither commits nor archives.
- ❌ Committing or pushing on `{{DEFAULT_BRANCH}}` → never: everything goes through a branch and <!-- sdd:if github -->a PR<!-- sdd:endif --><!-- sdd:if !github -->a human merge<!-- sdd:endif -->
  ([`CONTRIBUTING.md`](CONTRIBUTING.md) §2).
- ❌ `/opsx:ff` or `/opsx:apply` before the framing merge → the change has no approved
  classification: the artifacts rules stop, and a change pull request without one is judged
  `gates: unclassified` (a human merges it).
- ❌ Fixing a wrong classification inside the change branch → it is not read, and the edit opens the
  irreversible gate as gate machinery; reclassify through a new framing branch (§3, 1c).

## 7. Classification and triggers

Two files decide, change by change, which human gates stand between an approved proposal and
production. Both are YAML, both are checked by `python3 .sdd/bin/merge_conditions.py validate <file>`.

- **Intent gate** — the change visibly alters a business gesture, a screen, what the product shows or
  how it feels, whatever the layer (a backend scoring rule that changes the colours on screen counts).
  Open → the owner runs a short QA before merge.
- **Irreversible gate** — the change is not *code only*: a migration, a stored format (database,
  cache, browser storage, published file), a rollout step after merge, consumption of paid quota or
  capacity, infrastructure, a public endpoint others consume. Open → the owner gives the go (merges).
- **Gate machinery** — whatever changes what CI or the check does: triggers and every `.sdd/` file,
  any `classification.yaml` outside a framing pull request, hooks, agent settings, `.github/`,
  `.gitattributes`, `.gitmodules`, `openspec/config.yaml`, any `vercel.json`: always opens the
  irreversible gate, never waivable.
- Technical risk opens no gate: it raises review depth and post-deploy checks instead.

### `.sdd/triggers.yaml` — what opens a gate (per project)

```yaml
intent:
  paths: [ 'web/src/**', 'api/src/scoring/**' ]       # GitHub path-filter globs
  content:
    - paths: [ 'api/src/**' ]                         # optional: every file when omitted
      pattern: 'colorRamp|scoreWeight'                # Python regex, searched in ADDED lines only
irreversible:
  paths: [ 'api/migrations/**', 'infra/**', 'api/openapi.yaml' ]
  content:
    - paths: [ 'web/src/**' ]
      pattern: 'localStorage\.setItem|sessionStorage\.setItem'
gate_machinery:                                       # never waivable
  paths: [ 'deploy/release.sh' ]                      # the project's own, on top of the built-in list
```

- `paths`: a file the pull request adds, modifies or deletes opens the gate. `*` stops at `/`, `**`
  crosses it, `?` is zero or one of the preceding character (GitHub's syntax).
- `content`: one hit per file, on the first added line that matches; removed lines never match. Every
  file is read as text (binary files and `.gitattributes` settings included). A pattern only sees
  one added line at a time: it misses a construct split across lines, and a change that alters
  behaviour without adding a matching line (a removed guard, an edited constant elsewhere) — use
  `paths` for what must never slip through.
- `gate_machinery`: built in, always applied even when omitted: `.github/**`, `.sdd/**`,
  `.claude/hooks/**`, `.claude/settings.json`, `**/.gitattributes`, `.gitmodules`,
  `openspec/config.yaml`, `**/vercel.json` (wherever Vercel's root directory puts it: it carries the
  deploy guard); add the project's own (release scripts, deploy
  configuration). Adding, changing or deleting any `openspec/changes/**/classification.yaml` outside
  a framing pull request is gate machinery too, whether or not `{{DEFAULT_BRANCH}}` already has it
  (the archive pull request's identical move excepted).
- Read from `{{DEFAULT_BRANCH}}` only: a pull request that edits this file is judged by the previous
  version (and opens the irreversible gate).

### `openspec/changes/<id>/classification.yaml` — the gates of one change

```yaml
change: add-export                       # the change folder's name
intent:
  open: true
  evidence: "Adds an Export button to the report screen and a new download flow"
  waived: []
irreversible:
  open: false
  evidence: "Code only: no migration, no stored format, the CSV is generated on demand and not kept"
  waived:
    - trigger: 'api/openapi.yaml'        # exactly as written in triggers.yaml
      reason: "Adds an optional field to an internal endpoint no other client calls"
```

- `open` and a non-empty `evidence` for both gates, always. `waived` lists the triggers the diff
  will hit although the gate stays closed, each with its reason; a waiver never closes gate machinery.
- Written by the proposal step, challenged by the adversarial pass, approved by the framing merge
  (§3). The copy on `{{DEFAULT_BRANCH}}` is the only one read.

### What the check does with them
<!-- sdd:if github -->

The `merge-conditions` commit status (workflow `.github/workflows/merge-conditions.yml`, run from
`{{DEFAULT_BRANCH}}`, never from the pull request) classifies each pull request:
<!-- sdd:endif -->
<!-- sdd:if !github -->

`python3 .sdd/bin/merge_conditions.py match --base {{DEFAULT_BRANCH}} --head <branch> --branch <branch>`
classifies a branch the same way:
<!-- sdd:endif -->

| Pull request | Recognised by | Result |
|---|---|---|
| framing | only files of `openspec/changes/<id>/`, `classification.yaml` among them | `gates: framing` — the owner's merge approves |
| change | touches exactly one change folder `openspec/changes/<id>/` (its `tasks.md` at least), from a branch `<type>/<id>` (or `<type>/<id>/<lot>` for one pull request of a change delivered in several), and `{{DEFAULT_BRANCH}}` holds that change's classification | gates = the classification's open gates + every trigger hit not waived; a hit on a gate declared closed, without a waiver, is **unaccounted** and fails the check; an invalid approved classification gives `gates: invalid` and fails |
| archive | moves `openspec/changes/<id>/` into one folder `openspec/changes/archive/YYYY-MM-DD-<id>/` (or `<id>/`) and touches only `openspec/specs/`, `docs/`, `ROADMAP.md`, `BACKLOG.md` | judged on its own diff, normally `gates: none` |
| revert | adds `openspec/changes/<id>/revert.yaml` (§8), from the branch `revert/<id>`, and `{{DEFAULT_BRANCH}}` holds that change's classification | `gates: none` when the merges it lists are merges of the change's own pull requests on `{{DEFAULT_BRANCH}}`'s first-parent line (the newest of them included) and the diff, `revert.yaml` aside, is their **exact inverse** (every file back to the blob and mode it had before the first of them, nothing else); `gates: intent` when the reverted change had that gate open and is not the change in flight (its pull request has no `in-flight` label); `gates: irreversible` when it had that gate open or the revert touches gate machinery; anything else — a modified, partial or extended revert, another branch, a commit off the first-parent line or of another change, an older merge while a newer one exists — is an error and fails the check. No `review-harness`/`opsx-verify` needed: the exact inverse is the verification |
| unclassified | touches no change folder (hotfix, tooling) — the branch name alone never selects a classification — or its change has no approved classification | `gates: unclassified` — a human merges |

Touching several change folders, or a folder the branch does not name, is an error (the check fails),
and so is a `.sdd/triggers.yaml` missing from `{{DEFAULT_BRANCH}}`. The description reads
`gates: <gates>[ - <what is missing or wrong>]; base <sha7>`, the gates being `none`, `intent`,
`irreversible`, `intent+irreversible`, `framing`, `unclassified` or `invalid` (a revert reports the
gates it opens, usually `none`), and `base` the commit
of `{{DEFAULT_BRANCH}}` the verdict was computed against. Only `gates: none` is a change an agent may
merge, and only while `base` is still the head of `{{DEFAULT_BRANCH}}`; any other value is merged by
the owner.<!-- sdd:if github --> A push to `{{DEFAULT_BRANCH}}` re-judges every open pull request into
it (`pending`, `re-judging: …`, first). The status protects against mistakes only: a workflow the pull
request adds, or the agent's own token, can overwrite it. The deploy guard therefore never reads it:
it recomputes the verdict server-side (§8, "Deploy guard").<!-- sdd:endif -->

## 8. Delivery: deployment profile, verification, rollback, report

### `.sdd/deployment.yaml` — what merging deploys (per project)

```yaml
targets:                                   # or, for a project whose merge deploys nothing: deploys_nothing: true
  - name: api                              # unique
    platform: cloud-run                    # free text: cloud-run, vercel, fly, kubernetes…
    trigger: { paths: [ 'api/**' ] }       # what deploys it on a push to {{DEFAULT_BRANCH}}; or { every_push: true }
    workflow: .github/workflows/deploy-api.yml   # optional: the workflow that deploys it
    rollback:                              # back to the previous deployment, no rebuild
      command: gcloud run services update-traffic api --region europe-west1 --to-revisions=<previous>=100
      note: "<previous>: gcloud run revisions list --service api --region europe-west1 --limit 2 …"
      unconfirmed: true                    # not proven yet: the owner confirms it
    probes:                                # pass = exit 0 and, when given, `expect` (a regex) found in the output
      # first: the target serves the merged commit (the image is tagged with the sha it was built from)
      - command: gcloud run services describe api --region europe-west1 --format 'value(spec.template.spec.containers[0].image)'
        expect: ':{sha}$'
      - command: curl -fsS https://api.example.com/health
        expect: '"status" *: *"UP"'
  - name: web
    platform: vercel
    trigger: { every_push: true }
    rollback:
      command: vercel rollback --yes --token $VERCEL_TOKEN
      note: "Rolling back turns off the automatic assignment of the production domain: once a fix is deployed, `vercel promote <its deployment url> --yes` (or `vercel rollback --undo`) turns it back on, then probe the served revision again"
    probes:
      # first: production serves the merged commit (the GitHub deployment Vercel reports for the sha)
      - command: "gh api 'repos/{owner}/{repo}/deployments?sha={sha}&environment=Production' --jq '.[0].id' | xargs -I{} gh api 'repos/{owner}/{repo}/deployments/{}/statuses' --jq '.[0].state'"
        expect: '^success$'
      - command: "curl -fsS -o /dev/null https://www.example.com/"
scheduled_jobs:                            # jobs that run the merged code later
  - name: nightly-etl
    schedule: '0 3 * * * Europe/Paris'
    paths: [ 'api/src/etl/**' ]            # the code it runs
    runs: Cloud Scheduler → Cloud Run job etl
    probe: { command: "gcloud run jobs executions list --job etl --limit 1 --format 'value(status.succeededCount)'", expect: '^1$' }
```

- `{sha}` in a probe stands for the merged commit being verified. **The first probe of a target
  asserts that it serves that commit**: a target that did not deploy the sha (the guard refused it,
  the build failed, a rollback is still in place) fails the verification like a broken endpoint.
- Every target has a `trigger`, a `rollback` command and at least one probe; `deploys_nothing: true`
  excludes targets (and so any rollback). `unconfirmed: true` marks a value no file of the repository
  proves (a target, a rollback, a probe, a job): `python3 .sdd/bin/merge_conditions.py validate
  .sdd/deployment.yaml` checks the schema and prints each one, and the owner confirms them.
- Generated by `sdd-init` from the deploy workflows and the hosting configuration, then the
  project's own: never regenerated. It is gate machinery (`.sdd/**`).
<!-- sdd:if !github -->
- Without a GitHub remote, the human who merges runs the verification below by hand: the probes of
  each target the merge deployed, the scheduled jobs whose paths it touched, the rollback commands on
  failure.
<!-- sdd:endif -->
<!-- sdd:if github -->

### After the merge — one change in flight

1. **Label** — the agent's merge command ends with `&& gh pr edit <n> --add-label in-flight` (the
   hook allows exactly that, in the same command, after the merge); after an owner merge, or if
   the label edit failed, `gh pr edit <n> --add-label in-flight` alone in the next call. While a pull
   request carries the label, the hook refuses every other merge, and each deploy workflow's
   `concurrency: deploy-<workflow>` keeps two of its deploys from overlapping.
2. **Verification window** — for each target whose `trigger` the merged diff hits: wait for its
   deploy (the guard may refuse it: the deploy-alert issue says why), run its `probes` — the first
   one checks that it serves the merged commit —, then the
   change's own post-deploy checks (the last group of `tasks.md`). For each scheduled job whose
   `paths` the diff touches, the window extends until the job's next run has succeeded (its `probe`).
   A target the diff does not hit is not probed.
3. **Passed** — `gh pr edit <n> --remove-label in-flight`; PR 2 on `<type>/<id>-archive`
   (`git switch -c <type>/<id>-archive --no-track origin/{{DEFAULT_BRANCH}}`): `/opsx:archive`,
   post-archive, commit `chore(<id>)`, merged through the same route (`merge-conditions` judges it
   `archive`; no label, it deploys no code). Then the final report (below).
4. **Failed** — in this order:
   1. each affected target's `rollback` command: production goes back to the previous deployment
      without a rebuild (then its `note`, if any: Vercel's rollback turns off the automatic
      production assignment until a deployment is promoted again); probe the served revision;
   2. a revert pull request: `git switch -c revert/<id> --no-track origin/{{DEFAULT_BRANCH}}`,
      `git revert --no-edit <merge commit>` (`-m 1` for a merge commit; for a change delivered in
      several pull requests, each lot's merge, newest first), plus `openspec/changes/<id>/revert.yaml`:
      ```yaml
      revert_of: <id>                                   # the change folder's name
      merge_commits: [ <full sha of each merge of the change on {{DEFAULT_BRANCH}}> ]   # the newest one at least
      reason: "The /api/export probe returns 500 since the merge: the CSV writer needs a column the production view lacks"
      ```
      `merge-conditions` accepts it with no gate only if those are merges of the change's own pull
      requests on `{{DEFAULT_BRANCH}}`'s first-parent line, the newest among them, and its diff,
      `revert.yaml` aside, is the exact inverse of them together (§7, "revert"); nothing else goes in
      it — a fix is a new change. Reverting a change that is not the one in flight, when its intent
      gate was open, opens the intent gate: the owner approved that behaviour;
   3. move the label: `gh pr edit <n> --remove-label in-flight`, then the revert's merge command ends
      with `&& gh pr edit <revert n> --add-label in-flight`; verify the revert's deploy (the same
      probes), then remove that label;
   4. alert the owner: what failed, the probe output, the diagnosis, the rollback and revert done;
   5. open a fix change (`/opsx:new fix-<id>`). The reverted change is not archived.

   A change whose irreversible gate was open is not reverted this way (its revert opens the gate:
   a migration is fixed forward): rollback what the platform can, alert, and the owner decides.

### Deploy guard — the server-side barrier

**What it enforces**: every commit of `{{DEFAULT_BRANCH}}` that reaches production came from a merged
pull request, with every trigger hit accounted for and the CI the pull request needed green — the
pushed commit and every first-parent commit since the target's last deployment. **What it does not
enforce: the owner's gates.** The agent acts with the owner's token, so an owner merge and an agent
merge look the same server-side; a gate is kept by the merge route (client-side) and by the owner
merging gated pull requests. Any gate therefore passes the guard.

`.sdd/bin/deploy-guard.sh` runs first in each deploy job and in `deploy-alert.yml`, and as Vercel's
`ignoreCommand`; it never reads `merge-conditions`. **Its code is read from a trusted commit, never
from the pushed one**: the owner's reset commit (below) if set, else the last commit the workflow ran
successfully on (Vercel: the last production deployment, `VERCEL_GIT_PREVIOUS_SHA`), else the default
branch before the push — a candidate is trusted only when it is on the pushed commit's
**first-parent line** (a commit of `{{DEFAULT_BRANCH}}`, not one of a merged branch); otherwise the
guard falls back to `before` (Vercel: skips). A deploy job names its target (`DEPLOY_GUARD_TARGET`):
only the commits since the trusted one that change **that target's trigger paths** — read from the
trusted commit's `.sdd/deployment.yaml` — are judged; the others are reported, not judged, and never
block it (a target with `every_push`, and `deploy-alert.yml`, judge them all). For each judged commit
it recomputes:

- the pull request merged **as** that commit (`commits/<sha>/pulls`, merged into
  `{{DEFAULT_BRANCH}}`, its merge commit equal to the sha) — none: a direct push, refused;
- the commit's content is exactly the merge of its first parent and the pull request's head (a
  commit edited during the merge is refused); the pushed commit's first parent is the push's
  `before` (a "Rebase and merge" of several commits is refused);
- `merge_conditions.py match` against that parent: an unaccounted hit, an invalid classification
  or a file name holding a control character refuses;
- every workflow required by the diff, judged by the definitions **before** the merge, has a
  `pull_request` run on the head that succeeded (or whose jobs were all skipped); a workflow the pull
  request deleted is not required, one it renamed is, under its new name.

A refused commit is accepted later only once a following merged commit undoes it **exactly** (a
pull request that reverts it); until then every deploy of a target whose paths it changes is
refused.

**Owner reset** — when a target stays refused with no exact revert possible (later merges changed the
same files, a guard bug refuses its own fix, a target idle for more than 100 merges, a renamed deploy
workflow): the owner reviews `{{DEFAULT_BRANCH}}` and sets the repository variable
`DEPLOY_GUARD_RESET_<TARGET>` (the target's name upper-cased, every other character turned into `_`;
`DEPLOY_GUARD_RESET_DEPLOY_ALERT` for the alert workflow) to a reviewed commit:
`gh variable set DEPLOY_GUARD_RESET_API --body <sha>`. The deploy step takes it as the trusted commit,
and so judges only what came after it, as long as it is on the pushed commit's first-parent line
(otherwise it is ignored) and no later deploy has gone past it. **Only the owner sets repository
variables**: the agent's token has no Variables write ([`CONTRIBUTING.md`](CONTRIBUTING.md) §2,
"Access"). For Vercel, the owner's reset is a production redeploy without the Ignored Build Step. Anything it cannot judge refuses
too. A manual run (`workflow_dispatch`) is judged the same way and only on `{{DEFAULT_BRANCH}}`.
Exit codes: 0 deploy, 1 refused, 2 cannot judge, 4 the adoption merge (the guard was not installed
before it: it deploys nothing, as expected).

A refused GitHub Actions deploy fails its job; a refused Vercel build is skipped (Vercel: exit 0 =
skip, and anything but the guard's own "build" skips); in both cases `deploy-alert.yml` opens an issue
labelled `deploy-refused`, and while one is open the merge route refuses every agent merge. The owner
resolves it — a pull request that reverts the refused commit exactly — and closes the issue.
**Re-running a skipped Vercel production build**: once the cause is fixed, the next guarded push
builds; to deploy the current commit at once, Vercel → Deployments → Redeploy, with "Use project's
Ignore Build Step" ticked (the guard judges it again). Unticking it deploys unguarded: owner only,
after review — also how the first production deployment after the adoption is made (until then
`VERCEL_GIT_PREVIOUS_SHA` points at a commit without the guard, so every build is skipped).

What is not covered: the workflow files and `vercel.json` run from the pushed commit (GitHub and
Vercel read them there) — the agent's token has no `workflow` permission and both are gate
machinery, but a direct push by the owner is not stopped; a deploy made outside these pipelines; the
gates (above). **A renamed deploy workflow** has no successful run under its new name, so its first
run trusts `before` and commits refused before the rename are not judged again: only the owner can
rename a workflow (the agent has no `workflow` permission), and sets the reset variable when doing so.
**A manual run on another branch**: `workflow_dispatch` runs the workflow file of the ref it is
dispatched on, so an older branch whose deploy workflow predates the guard can deploy unguarded with
any token that has Actions write; the fix is deploy credentials bound to the default branch and to the
deploy workflow (Workload Identity Federation with conditions on `assertion.ref` and
`job_workflow_ref`), or deleting such branches. **Vercel's clone is shallow** (10 commits): the
`ignoreCommand` deepens it with the read-only token before checking that the last production
deployment is on the first-parent line; if that fetch fails, production builds are skipped (fail
closed) — check it on the first production build. Follow-ups: an identity of its own for the agent (a GitHub App) with GitHub Pro rulesets
on `{{DEFAULT_BRANCH}}`; deploy credentials (Workload Identity Federation) bound to `{{DEFAULT_BRANCH}}`.
<!-- sdd:endif -->

### Final report — to the owner, once per change

```markdown
## <change-id> — shipped | rolled back
**What shipped**: <one paragraph, in the user's terms>; PRs #<n> (change), #<m> (archive)
**Gates**: none | intent (QA passed on <date>) | irreversible (go on <date>)
**Review harness**: <rounds> rounds; fixed: <BLOCKER/MAJOR found and fixed, one line each>; refuted: <count>; angles not run: <list or none>
**Verification**: <each probe and check, with its result>; scheduled jobs: <job — run of <date>: ok | not concerned>
**Look at in production**: <2 to 4 concrete places: URL, screen, gesture, expected result>
**Left open**: <follow-up changes or backlog lines, or none>
```

The report is one message, sent when the archive pull request is merged (or the rollback is done:
then "rolled back", with the diagnosis and the fix change). The owner is not asked anything between
the framing merge and this report unless a gate is open.
