---
name: sdd-init
description: Installs the SDD workflow (OpenSpec + specialised agents + mandatory review + git guardrails + CI) in the current project, whatever the language — first reverse-documents the actual code, then generates CLAUDE.md, agents, OpenSpec rules, hook and CI from what was observed. Also `--refresh` to resync an installed project with a newer version of the kit.
argument-hint: "[--refresh]"
disable-model-invocation: true
---

# sdd-init — install the SDD workflow in a project

You install, in the current repository, the workflow described in the kit's `GUIDE.md`: spec-driven
development with OpenSpec, specialised sub-agents, mandatory review before verify, post-archive,
a mechanical git guardrail and CI. The process is **the same from one project to the next**; the
rules, however, **come out of the project's own code** — never from another project, never from a
guess.

This folder (the "base directory" given when the skill is invoked) contains:
- `templates/` — templates to fill in; the convention is in [`templates/VARIABLES.md`](templates/VARIABLES.md) (read it first);
- `references/recon.md` — the reverse-documentation checklist;
- `references/adoption.md` — projects that already have a `CLAUDE.md`, agents or OpenSpec, and the `--refresh` mode.

`$ARGUMENTS` contains `--refresh` → go straight to `references/adoption.md` §3.

## Principles (hold them for the whole install)

1. **Facts are your job.** Never ask the user what the code, the CI, the dependency files or the git
   history can tell you. You only ask for **choices**.
2. **Observed ≠ wished for.** A "non-negotiable" rule only goes into `CLAUDE.md` if it is verified in
   the code (cite `file:line`) **or** decided by the user. Everything else goes under "to confirm" in
   the final report.
3. **A mechanical rule becomes a check**, not an instruction: if a rule can be verified by a linter,
   an architecture test or CI, propose that check (a backlog line in `docs/ROADMAP.md`) instead of
   only writing prose.
4. **Nothing is overwritten without being read.** An existing target file → `references/adoption.md`.
5. **Few, but right.** An agent, skill or section that doesn't serve this project is not generated
   (e.g. no `devops` agent without Docker or CI; no `full-stack-dev` with a single module).
6. **Verify before concluding**: every check command written into a file has been run at least once
   during the install, and its result is in the report.

## Phase 0 — Pre-flight

1. `git rev-parse --show-toplevel` (not a git repository → offer `git init`, otherwise stop),
   `git status --short` (dirty tree → ask whether to go on: the install is committed separately),
   `git branch --show-current`, default branch (`git symbolic-ref refs/remotes/origin/HEAD` or, failing
   that, the local `main`/`master`), remote (`git remote -v` → GitHub remote? → option `github`; GitHub
   remote or `.github/workflows/` present → option `ci`). Today's date: `date +%F` (→ `{{INSTALL_DATE}}`).
2. Create the working branch **before any write**: `git switch -c chore/sdd-init`.
3. Tools — check them, and for each missing one give the install command (don't install it without
   the user's go-ahead):

   | Tool | Check | Install | Required |
   |---|---|---|---|
   | Node ≥ 20 + npm | `node -v` | nodejs.org / `brew install node` | yes (OpenSpec) |
   | OpenSpec CLI | `openspec --version` | `npm install -g @fission-ai/openspec@latest` | yes |
   | jq | `jq --version` | `brew install jq` / `apt install jq` | yes (without jq, the hook blocks every `git`/`gh`) |
   | perl | `perl -v` | ships with macOS/Linux | yes (the hook's shell reader) |
   | Python 3.9+ with PyYAML | `python3 -c "import yaml"` | `python3 -m pip install --user pyyaml` | yes (`.sdd/bin/merge_conditions.py`: classification checks, `merge-conditions`) |
   | gh | `gh auth status` | `brew install gh` | with option `github` |
   | uv + graphify | `graphify --version` | `uv tool install "graphifyy[sql]"` | with option `graphify` |

4. Companion plugins: ask the user to run `/plugin` and confirm that `superpowers` and `handoff` are
   installed (the workflow relies on `systematic-debugging`, `verification-before-completion`,
   `test-driven-development`, and the generated rules call `/handoff:passation`). If one is missing:
   `/plugin install superpowers@claude-plugins-official`, `/plugin install handoff@claude-toolbox`.
5. Files that already exist (`CLAUDE.md`, `AGENTS.md`, `.claude/agents/`, `.claude/settings.json`,
   `openspec/`, `docs/`) → note them: they go through `references/adoption.md`.

## Phase 1 — Reverse-documentation (code first)

Follow [`references/recon.md`](references/recon.md). Summary:

1. **Module map**: list the modules (VARIABLES.md §4), their stack and pinned versions, their build /
   test / lint commands **as CI runs them** (or, without CI, as the project's scripts define them).
2. **Parallel recon**: one `Explore` sub-agent ("very thorough") per module, plus one for
   cross-cutting concerns (CI, infra, existing docs, git history) — small project (single module, a
   few thousand lines): do the recon yourself, it is faster. Each returns a report structured
   according to `recon.md` §3, every claim sourced `file:line`. You aggregate.
3. **Baseline**: run each module's check commands. Red → record it as is ("the baseline is red: N
   failing tests"); **fix nothing** during the install.
4. Write the reverse-documentation from the templates:
   - `docs/ARCHITECTURE.md` (`templates/docs/ARCHITECTURE.md`)
   - per module: `<module>/docs/CODING_RULES.md`, `MODULES.md`, `TESTING_STRATEGY.md`
     (`templates/module-docs/`) — single-module repo: straight into `docs/`
   - `docs/GLOSSARY.md`: seeded from the domain names (entities, aggregates, states, roles) found in
     the code — short definitions, marked "to confirm" when inferred
   - `docs/adr/ADR-001-…`: one ADR per **structural decision already taken** and visible in the code
     (choice of framework, database, auth, architecture style), status `Accepted (reverse-documented)`
   - `docs/ROADMAP.md`: goal taken from the README and existing docs (otherwise a "to confirm" line,
     without asking an extra question) + the backlog section fed by what the recon found (notable
     TODO/FIXME, debt, mechanical checks to add)
5. **Validation gate 1** — show the user a short summary: modules, stack, commands and their status,
   5 to 10 observed architecture rules (with evidence), assumed domain risks, points "to confirm".
   They correct it; you only move on to phase 2 once they agree.
6. **Options deduced, not asked**: `multi-module` (≥ 2 modules), `devops` (Docker, IaC or deployment
   scripts — CI alone is not enough), `migrations` (VARIABLES §3), `deploys` (a push to the default
   branch deploys something: a deploy workflow or a hosting configuration found by the recon,
   `references/recon.md` "Deployment"), `github`, `ci`, `lean` (single
   module and < ~5,000 lines of code: `wc -l` on source files, tests and dependencies excluded).
   With `github`, also read the repository's merge settings for `{{MERGE_METHOD}}` (VARIABLES §1).
   Announce them at gate 1; the user can challenge them.

## Phase 2 — Choices (a single round of questions)

Ask **in one go** (question tool, ≤ 4 questions, each option explained, your recommendation first)
the choices the code cannot settle:

1. **Merge method** — only when the repository allows both squash and merge commits (otherwise
   deduced, VARIABLES `{{MERGE_METHOD}}`): `squash` (recommended: one commit per change on the
   default branch, reverted as one) · `merge`. Rebase is never offered: the deploy guard needs the
   default branch before the merge as one commit. There is no question on who merges: the agent
   pushes and opens PRs, merges only through the verified route (`merge-conditions` green with
   `gates: none`, checked by the hook on GitHub), and a PR with an open gate is merged by the owner.
   Without a GitHub remote the agent does not push (`ALLOW_PUSH=0`): say so at gate 1, and set
   `ALLOW_PUSH=1` by hand only if the owner wants the agent to push to another remote.
2. **Language** of the docs and replies (English, French, or another one). The templates are written
   in English: with another language, translate the prose as you fill them. Code, commits and
   OpenSpec artifacts stay in English unless explicitly chosen otherwise.
3. **Options** (multi-select): `graphify` (map of the code; offered ticked above ~20k lines, unticked
   below — a small project is faster to read than to query), `graphify-hooks` (only meaningful with
   `graphify`, offered ticked with it: `graphify hook install` puts local git hooks — post-commit,
   post-checkout — that rebuild the graph incrementally; per developer, nothing committed), `ui` (offered ticked if the project has
   a web interface: `sdd-ui` plugin), `work-style` (offered ticked: the kit's way of working in
   `CLAUDE.md` §12 — short framing with examples, working all the way through once framing is agreed,
   structured final report, handoff), `caveman` / `cockpit` (display preferences installed at user
   level; `cockpit` = the desktop mods `openspec-cockpit` + `conversation-cards` from the claude-toolbox
   marketplace are installed — offered ticked if `claude plugin list` shows them).
4. **Agent model** (`opus` recommended: the quality of the review and of the adversarial pass depends
   on it; `inherit` to follow the session's model).

`{{DOMAIN_RISKS}}`: propose a wording deduced from the recon and have it validated in the same round
(an "other" option to correct it).

## Phase 3 — Rules, agents, OpenSpec

1. **OpenSpec**:
   - `openspec init --tools claude` (non-interactive). It generates `openspec/` and the `/opsx:*`
     commands + `openspec-*` skills in `.claude/`.
   - The workflow uses the extended set (`new`, `ff`, `continue`, `apply`, `verify`, `sync`,
     `archive`, `bulk-archive`, `explore`, `onboard`, `propose`). `openspec config list`: if any are
     missing, ask the user to run `openspec config profile` in their terminal (interactive), then
     run `openspec update`.
   - Note `openspec --version` (→ `{{OPENSPEC_VERSION}}`, pinned in CI).
   - Replace `openspec/config.yaml` with `templates/openspec/config.yaml` filled in. `context` = a
     **short** summary (≤ 25 lines: pitch, stack, 5 to 8 critical architecture rules, risks,
     languages) that points to the docs for details — it is injected into every artifact, every line
     costs. In English. `rules` kept, `# sdd:if` blocks resolved.
   - **No massive reverse-spec.** Specs are born with changes. In the final report, propose 1 to 3
     `baseline-<domain>` changes for the most critical domains: `ADDED` spec deltas describing the
     **existing** behaviour, tasks = characterisation tests that pin it. It is the only clean way to
     reverse-spec (specs are never edited by hand). For each, give the ready-to-run command
     (`/opsx:new baseline-<domain>`) and the 3 to 5 behaviours it will pin.
2. **Root files**: `CLAUDE.md` and `AGENTS.md` from `templates/root/` (option `lean`:
   `AGENTS.lean.md`, written under the name `AGENTS.md`).
3. **Process docs**: `docs/CONTRIBUTING.md`, `docs/OPENSPEC_GUIDE.md`, `docs/AGENT_TOOLBOX.md`
   (except with option `lean`), and `docs/GRAPHIFY.md` with option `graphify`, from `templates/docs/`.
4. **Agents** (`templates/agents/` → `.claude/agents/`):
   - always: `product-owner`, `architect`, `code-reviewer`, `tester`, `doc-writer`, `README.md`;
   - `devops` with option `devops` (Docker, IaC, deployment; CI alone doesn't justify it);
   - `module-dev.md` instantiated **once per module** → `.claude/agents/<module>-dev.md`, filled with
     **that module's** stack, rules and commands;
   - `full-stack-dev` only with `multi-module` and when one module consumes the other (API + client).
   - `{{AGENT_MODEL}}` written verbatim in every frontmatter.
5. **Filling** — for each file: variables, `sdd:fill` (content taken from the reverse-documentation,
   never generic: "follow best practices" is forbidden — name the rule and its evidence),
   `sdd:if`/`sdd:endif` resolved (a marker alone on its line goes with its line), `sdd:each`
   expanded, `sdd:note` removed, paths normalised (VARIABLES §4). Translate the prose if the docs are
   not in English. Reverse-documented ADRs follow `templates/docs/adr/ADR-000-template.md`.
6. **Marker**: the last line of `CLAUDE.md` = the install marker (`references/adoption.md` §2) — it is
   what `/sdd-core:sdd-init --refresh` relies on.

## Phase 4 — Guardrails

1. **Git hook**: copy `templates/claude/hooks/block-git-writes.{sh,pl,test.sh,conf}` into
   `.claude/hooks/` (`chmod +x` the `.sh` files), fill in the `.conf` (protected branch, `ALLOW_PUSH`
   from option `github`, `MERGE_METHOD`, `ALLOW_FORCE_WITH_LEASE=0`). `templates/claude/settings.json` → `.claude/settings.json`: the `PreToolUse` hook plus a
   curated `permissions.allow` of safe commands (read-only git, `openspec`, `gh run`/`gh pr`
   read-and-create, graphify queries, the hook test suite); the hook carries `"timeout": 120`, well
   above the merge route's 40-second deadline (a hook that times out does not block the call). **Add the module checks**: one
   `Bash(<command>)` entry per command of `{{CHECK_COMMANDS}}` / each `{{MODULE_CHECK}}`, written
   exactly as run (plus a `Bash(<command> *)` form when the command takes arguments, e.g. a test
   filter) — without them, every check run asks for permission and working "all the way" stalls.
   Existing `settings.json` → merge: union of the `allow` lists and of the hooks, nothing removed or
   reordered. Run `bash .claude/hooks/block-git-writes.test.sh` → it must end
   with `ALL n CASES OK`.
   ⚠️ From then on the hook is active for you too: `git add` with explicit paths, never on the
   protected branch, long messages through `git commit -F <file>`.
2. **CI** (option `ci`): `templates/github/workflows/{openspec,tooling}.yml` → `.github/workflows/`;
   `checks.yml` → one `checks-<module>.yml` per module; `migrations.yml` with option `migrations` (no
   already-merged migration modified, deleted or renamed). CI already present → only add
   `openspec.yml`, `tooling.yml` (and `migrations.yml`), and check that the existing CI runs the same
   commands as `{{CHECK_COMMANDS}}` (otherwise, report the gap). Option `github` (it implies `ci`):
   `templates/github/workflows/merge-conditions.yml` → `.github/workflows/merge-conditions.yml`, with
   `workflow_run.workflows` listing the `name:` of **every** workflow that runs on `pull_request`,
   the project's existing ones included (a workflow left out is still required by the check, but its
   completion no longer re-triggers it, so the status stays `pending` until the next event).
3. **Misc files**: `templates/misc/gitignore-additions` → appended to `.gitignore` (no duplicates);
   `templates/misc/worktreeinclude` → `.worktreeinclude`. Option `graphify`:
   `templates/misc/graphifyignore` → `.graphifyignore`, then `graphify update .` and
   `graphify check-update .`; if the `graphify` skill is not in your list of skills, ask the user to
   run `graphify install --platform claude` and then restart the session. Option `graphify-hooks`:
   `graphify hook install`, then `graphify hook status` (both hooks `installed`).
4. `templates/claude/settings.local.example.json` → `.claude/settings.local.example.json` (committed,
   it holds no secret: it documents the token's exact permissions). **Never create
   `settings.local.json` yourself**: in the report, tell each developer to copy the example and put
   their own token in it.
5. **Review harness settings**: `templates/sdd/harness.yaml` → `.sdd/harness.yaml`. Fill `angles` with
   this project's globs and `mechanical` with the commands proven in phase 1 (architecture tests, lint,
   module tests, dependency audit, measured budgets). Mutation tooling: if the project has one
   (PIT, Stryker, mutmut, cargo-mutants…), its command scoped to `{files}`; otherwise `null`, and say
   in the report that test strength is judged without mutation evidence until one is added.
6. **Triggers and the matcher**: `templates/sdd/triggers.yaml` → `.sdd/triggers.yaml`, filled per
   project from the recon, every glob pointing at a folder that exists: **irreversible** — the
   migration folders (option `migrations`), stored formats (cache keys, serialised payloads, browser
   storage, published files: content patterns where paths cannot isolate them), infrastructure (IaC,
   production compose files, Dockerfiles, deploy scripts), public endpoints others consume (OpenAPI
   files, public controllers), scheduled jobs and rollout scripts, paid quota; **intent** — the UI
   modules' sources, user-facing texts, and the backend code that decides what users see (scoring,
   ranking, classification rules). What could not be proven goes to the report as "to confirm".
   `templates/sdd/bin/merge_conditions.py`, `test_merge_conditions.py` and `deploy-guard.sh` →
   `.sdd/bin/`, **copied verbatim** (`chmod +x` all three); with option `ci`, the generated
   `tooling.yml` runs the matcher's and the deploy guard's tests on every change to `.sdd/`.
7. **Deployment profile and deploy guard**: `templates/sdd/deployment.yaml` → `.sdd/deployment.yaml`,
   from the recon's "Deployment" findings: option `deploys` → one target per deploy target (its
   trigger = the deploy workflow's push path filter, or `every_push` for a platform that builds every
   push, Vercel by default), its rollback command, its probes; otherwise `deploys_nothing: true`;
   and every scheduled job that runs the repository's code. A value no file proves — typically the
   rollback command — is written with `unconfirmed: true`, never guessed silently. Run
   `python3 .sdd/bin/merge_conditions.py validate .sdd/deployment.yaml`: no error, and each
   `unconfirmed:` line it prints goes to the report's "to confirm" list. Then, with options
   `github` and `deploys`:
   - each deploy workflow: the guard block of `templates/github/workflows/deploy.yml` (job-level
     `concurrency: { group: deploy-${{ github.workflow }}, cancel-in-progress: false }`,
     `workflow_dispatch`, checkout with `fetch-depth: 0` and `persist-credentials: false`, Python, the
     "Deploy guard" step that reads the guard from the trusted commit, its values through `env:` —
     `DEPLOY_GUARD_TARGET` set to the target's `name` and `DEPLOY_GUARD_RESET` to
     `${{ vars.DEPLOY_GUARD_RESET_<NAME> }}`, the name upper-cased, every other character `_`)
     merged at the top of the job that deploys, the project's own steps unchanged after it, and the
     three read permissions added; a target without a workflow gets none (it is guarded by its
     platform, below, or reported as unguarded);
   - a Vercel target: `ignoreCommand` of `templates/vercel/vercel.json` added to the project's
     `vercel.json` (in Vercel's root directory; a different existing `ignoreCommand` is shown to the
     owner, never dropped silently), `{{VERCEL_PATHS}}` filled (VARIABLES §1); the report asks the
     owner for the read-only `DEPLOY_GUARD_TOKEN` in Vercel (`docs/CONTRIBUTING.md`, "Deploy guard
     access") and, once the adoption is merged, for one production redeploy without the Ignored
     Build Step (until then the last production deployment has no guard, so every build is skipped);
   - `templates/github/workflows/deploy-alert.yml` → `.github/workflows/deploy-alert.yml`;
   - the `in-flight` label: `gh label create in-flight --description "Merged, not yet verified in
     production"` (or the report asks the owner when the token cannot create labels);
   - rebase merges: when the repository allows them (`gh api repos/{owner}/{repo} --jq
     .allow_rebase_merge`), the report gives the owner the command that turns them off — the guard
     refuses every "Rebase and merge" of several commits: `gh api -X PATCH repos/{owner}/{repo} -F
     allow_rebase_merge=false` (an admin action: the owner runs it).
   Run `actionlint` on every workflow written or changed when it is installed (otherwise say so).
8. Option `ui`: `templates/claude/launch.json` → `.claude/launch.json`, one configuration per UI
   module, filled from the recon (the module's dev-server script: `runtimeExecutable`,
   `runtimeArgs`, `port`). It lets Claude's preview tools start and check the UI. Keep `autoPort:
   true` unless a backend's CORS configuration expects a fixed port (then a fixed port, and say why
   in the report).

## Phase 5 — Checks

Everything must pass; otherwise fix it before delivering:

```bash
grep -rnE '(^|[^$])\{\{[A-Z_]+\}\}|sdd:(fill|if|endif|each|endeach|note)' CLAUDE.md AGENTS.md .claude/agents .claude/hooks .claude/settings.json docs openspec/config.yaml .sdd .github .gitignore .worktreeinclude .graphifyignore $(find . -name vercel.json -not -path '*/node_modules/*') 2>/dev/null   # empty
openspec validate --all
bash .claude/hooks/block-git-writes.test.sh                      # ALL n CASES OK, whatever the settings (gh is stubbed)
python3 .sdd/bin/test_merge_conditions.py                       # OK: the matcher and the deploy guard work on this machine
python3 .sdd/bin/merge_conditions.py validate .sdd/triggers.yaml .sdd/deployment.yaml   # exit 0; only `unconfirmed:` lines (into the report)
python3 -c "import json; json.load(open('.claude/settings.json'))"
# YAML: the first tool available
for f in openspec/config.yaml .sdd/*.yaml .github/workflows/*.yml; do ruby -ryaml -e "YAML.load_file('$f')" 2>/dev/null || python3 -c "import yaml,sys; yaml.safe_load(open('$f'))" || echo "YAML KO: $f"; done
```

plus: every command cited in the "Before finishing" section of `CLAUDE.md` run at least once; every
relative link in the generated files points to an existing file (check them one by one, especially
with `MODULE_PATH=.`); no mention of a stack, tool or domain the project doesn't have.

Then dispatch `code-reviewer` (the project's new agent) on the install diff: its mission = consistency
of the generated rules with the actual code (an unproven rule = 🔴 MAJOR). Fix BLOCKER/MAJOR findings.

## Phase 6 — Delivery

1. Two commits on `chore/sdd-init`, explicit paths:
   - `docs(sdd-init): reverse-document architecture, modules and conventions` (phase 1);
   - `chore(sdd-init): install spec-driven workflow, agents and git guardrails` (phases 3-4).
   Body: what was observed vs decided, test baseline.
2. Option `github`: `git push -u origin chore/sdd-init` and `gh pr create`, then stop: **the owner
   merges it** (it is gate machinery, and `merge-conditions` is not on the default branch yet, so the
   hook would refuse the agent's merge anyway). Without `github`: stop at the commits.
3. **Final report** (structured):
   - **Done**: generated files, by phase.
   - **Decisions**: phase 2 choices.
   - **Observed vs to confirm**: proven rules (count); list of "to confirm" items, the deployment
     profile's `unconfirmed` values first (each with the question to the owner, e.g. "how is the
     api rolled back to the previous revision?").
   - **Baseline**: check commands and their result, with numbers.
   - **Expected from you**: create `.claude/settings.local.json` (gh token), re-read §5 of
     `CLAUDE.md`, install the optional plugins chosen; with a Vercel target, the read-only
     `DEPLOY_GUARD_TOKEN` in Vercel's environment and the first production redeploy after the adoption;
     the `in-flight` label if it could not be created; `allow_rebase_merge=false` when rebase merges
     are allowed.
   - **Next step**: `/opsx:onboard` for a first guided cycle, or the first `baseline-<domain>`
     proposed, or `/opsx:new <id>` on the first ticket of `docs/ROADMAP.md`.
