# Changelog

Versions of the `sdd-core` plugin, with what changed in the catalog around it. A version only reaches
users when the `version` in the plugin's `.claude-plugin/plugin.json` changes (see
[`MAINTAINING.md`](MAINTAINING.md)). After updating the plugin, run `/sdd-core:sdd-init --refresh` in
each installed project to bring its generated files up to date.

## 0.6.0 — 2026-11-20

Plugins: `sdd-core` 0.6.0, `wayfinder` 0.1.0 (new, optional). Projects need
`/sdd-core:sdd-init --refresh` for the agent to propose `wayfinder`: `CLAUDE.md` and
`AGENT_TOOLBOX.md` change.

### Added
- **`wayfinder`**, an à-la-carte plugin adapted from `mattpocock/skills` (MIT):
  `/wayfinder:wayfinder` charts an effort too big for one session as a map of decision tickets
  (grilling, research, prototype, task) with a destination, the decisions so far, the fog not yet
  specified and what is out of scope, then resolves one ticket per session. The map lives on GitHub
  issues when the repo has a GitHub remote (labels `wayfinder:*`, `gh`'s native sub-issues and
  blocking), otherwise under `docs/wayfinder/`; no `setup-matt-pocock-skills`. Grilling tickets
  invoke `grilling:grilling` (and `sdd-core:domain-modeling` when present), research tickets go to a
  sub-agent with web access, prototypes are throwaway artifacts or branches never merged. In an
  `sdd-core` project the destination is a list of changes ready for `/opsx:new`, each with its
  settled decisions; the map never writes OpenSpec artifacts and ends by proposing the `/opsx:new`
  runs. Depends on `grilling`; not a dependency of `sdd-core`.

### Changed
- The generated `CLAUDE.md` proposes `/wayfinder:wayfinder` before `/opsx:new` when a roadmap epic or
  a request clearly spans more than one change (§3, "What the agent proposes"; §11), and says how to
  install it when it is missing. `AGENT_TOOLBOX.md` adopts it.
- `CATALOG.md` documents `wayfinder` (no longer "Coming next").

## 0.5.0 — 2026-11-20

Plugins: `sdd-core` 0.5.0, `handoff` 0.2.0, `grilling` 0.1.0 (new); mods `openspec-cockpit` 0.15.1,
`conversation-cards` 0.2.1, `background-tasks` 0.2.1. Projects need `/sdd-core:sdd-init --refresh`:
the agents, `CLAUDE.md`, `AGENTS.md`, the OpenSpec guide, the toolbox, the roadmap and the
`.gitignore` additions change.

### BREAKING
- **New dependency `grilling`.** Updating `sdd-core` in place does not install it: run
  `claude plugin install grilling@claude-toolbox` once, otherwise `sdd-core` refuses to load.
- **`/handoff:passation` is now `/handoff:handoff`** and writes to `.claude/handoff/`. Files already
  in `.claude/passation/` stay readable: the mods read both folders, and the generated `.gitignore`
  keeps both.

### Changed
- **The agents can invoke skills.** Every generated agent had a `tools` list without `Skill`, so the
  skills their definitions named never fired (transcripts of three projects: zero
  `test-driven-development` calls, `domain-modeling` only from the main session). Each agent now has
  `Skill` and names the skills it invokes and when: `superpowers:test-driven-development`,
  `systematic-debugging` and `verification-before-completion` for the dev agents and `tester`;
  `sdd-core:domain-modeling` for `product-owner`, `architect`, `code-reviewer`, `doc-writer`;
  `sdd-core:codebase-design` for `architect` on a structural change; `sdd-ui:web-design-guidelines`
  for `code-reviewer` on a UI diff. `module-dev` writes each scenario's failing test before the code.
- **Framing grills the owner.** After `/opsx:new`, the main session runs `grilling` (rounds of five
  questions at most, each with its recommended answer, facts looked up rather than asked) and briefs
  `product-owner` with the settled decisions; `product-owner` no longer interviews (a sub-agent
  cannot) and returns what is still open. The adversarial pass's open objections go back to the
  owner as a grilling round. The working-style option's limit moves from three questions per round
  to five.
- **Skills by phase.** The generated `CLAUDE.md` names, for each phase, the skills to use and the
  superpowers process skills that must not replace them (`brainstorming`, `writing-plans`,
  `executing-plans`, `subagent-driven-development`, `requesting-code-review`,
  `finishing-a-development-branch`).
- **What the agent proposes, unasked.** User-invoked skills stay the user's, but the main session
  proposes them at set moments: `/handoff:handoff` before a heavy phase, after a merge in a long
  session or when the context gets heavy (no longer only in the working-style option);
  `/sdd-core:improve-codebase-architecture` once five changes are archived after the
  `Last architecture audit:` date the audit now writes in `docs/ROADMAP.md`; `/sdd-core:retro` after a
  review that needed two fix rounds or more.
- **`sdd-core:codebase-design`**, split out of `improve-codebase-architecture`: deep modules, seams,
  dependency categories and "design it twice", now usable while designing a change.
  `improve-codebase-architecture` grills the owner on the candidate it frames.
- `review-interface` invokes the `sdd-ui` skills instead of guessing their path in the plugin cache.
- The handoff template no longer carries its own, outdated copy of the cycle: it points to the
  project's `CLAUDE.md`.
- **`CATALOG.md`**: every plugin and skill, its mode (auto, proposed, manual) and when it fires, with
  a prompt that asks an agent which plugins to install for a project. `AGENT_TOOLBOX.md` adopts
  `grilling` (it was listed as rejected) and `codebase-design`, and gives each tool its mode.

## 0.4.0 — 2026-11-14

Plugins: `sdd-core` 0.4.0, `handoff` 0.1.1, `local-qa` 0.1.0 (new).

### BREAKING
- **New dependency `local-qa`.** `sdd-core` 0.4.0 depends on it. **Updating in place** (auto-update
  included) does not install a dependency added since: run
  `claude plugin install local-qa@claude-toolbox` once (`local-qa@<catalog name>` if you added the
  catalog under another name), otherwise `sdd-core` refuses to load
  (`Dependency "local-qa@…" is not installed`). A fresh `claude plugin install sdd-core@claude-toolbox`
  installs it with `superpowers` and `handoff`.
- **The git autonomy levels are gone** (details under "Changed"): the agent merges ungated pull
  requests through the verified route, the owner every gated one.
- **Deploy guard wiring.** A refresh (or a new install) with a GitHub remote and a deploy puts the
  guard at the top of each deploy job and in Vercel's `ignoreCommand`. Vercel then skips **every**
  production build until the owner sets the read-only `DEPLOY_GUARD_TOKEN` in Vercel and redeploys
  production once without the Ignored Build Step; a GitHub deploy job refuses any commit that did not
  come from a merged pull request with its CI green.
- **The agent's token** (`.claude/settings.local.json`) now needs **Issues: read** (the merge route
  lists `in-flight` pull requests and open `deploy-refused` issues) and **Commit statuses: read and
  write** (the agent posts `review-harness` and `opsx-verify`), and must have **no** `workflow`
  permission and **no** Variables write (only the owner changes workflows and sets the deploy guard's
  reset variables). Without Issues read, every agent merge is refused (fail closed).

### Added
- **`local-qa` plugin**, `/local-qa:qa-prepare`: the owner's intent QA of a change runs locally, on a
  machine other projects and agents share, and it only ever stops what it provably started. It
  inventories what runs (containers with their compose project and working directory, listening ports
  with each process's working directory, each mapped to its project and worktree); reuses a running
  service only when it belongs to the same project and is compatible (shared infrastructure; never
  code from another worktree; a database only when the change adds or edits no migration file and
  the database's applied migrations, read by a read-only `applied_migrations` command of the services
  spec, equal the worktree's — otherwise, when it cannot compare, or with `migrations: []` (a schema
  no migration file manages), a database of its own under the compose project
  `qa-<project>-<worktree>-<hash>`);
  starts the rest on free ports it reserves machine-wide (lock files, released at cleanup); starts
  processes through `launch` (a Gradle server with `--no-daemon`: the daemon would detach it, and the
  refusal says so) and records in `.claude/qa/started.json` only a process of this very
  worktree, started after the QA opened, descending from its `launch` or its recording shell, and not
  Claude Code, a desktop app or an IDE helper, and only a container with this QA's compose labels;
  and hands the owner a QA brief (link, 3 to 6 gestures with expected results, before/after
  captures) in the shape the `conversation-cards` mod draws as a QA card. `--cleanup` re-checks each
  entry (same process, same labels, full container id), escalates to SIGKILL and checks the process
  group is gone, keeps what it could not stop in `started.json`, and stops nothing else. The
  deterministic part is `scripts/qa_env.py` (standard library), with its tests. The templates call it at the intent gate
  (`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` "Who merges", `OPENSPEC_GUIDE.md` §3 and §7,
  `AGENT_TOOLBOX.md`); `.claude/qa/` is added to the generated `.gitignore`.
- **Adoption mode starts with a mapping table**: every existing rule file or section → its kit
  counterpart → keep / merge / replace / create / decide, with the reason, shown to the owner and
  approved before any file is written; the project's language, layout and project-specific rules are
  kept. `references/adoption.md` has a worked example.
- **The install marker records the toolbox commit**: `claude-toolbox: installed <version> (<commit>) on
  <date> …`, the commit read from Claude Code's record of the installed plugin. A version number does
  not name one template set (0.3.0 named five); a commit does.
- **Three-way `--refresh`**: base = the templates of the commit the project's marker records, fetched
  from the toolbox at that exact commit; ours = the project's file; theirs = the new template filled
  with the project's values; `git merge-file --diff3` merges. A local edit and a kit change on
  different lines are both kept; the same lines changed on both sides are reported to the owner,
  never resolved by picking a side. Every entry is checked and merged before anything is written (a
  failure writes nothing, and a failure while putting the files in place names what was and was not
  written); a file the project deleted is not created again; a CRLF file stays CRLF; a file still
  holding a conflict-marker line neither template carries, not UTF-8, or reached twice through a
  symlink is refused.
  Without a commit in the marker (projects set up before 0.4.0), or without the network, the former
  two-way comparison ("keep the local version when in doubt"), said in the report. Script
  `sdd-init/scripts/refresh_merge.py`, with its tests. Phase 5 runs `git diff --cached --check` on
  what is staged. Releases are tagged `sdd-core-v<version>` for people; the refresh does not read
  tags.
- The version check also reads the marker in `.claude/CLAUDE.md` (projects that keep their rules
  there); with a marker in both files it compares the highest version and names the conflict.
- **Review harness**: `/sdd-core:review-harness <id>` reviews an implemented change from eight angles
  (`review-spec-conformance`, `review-conventions`, `review-bugs`, `review-tests`, `review-security`,
  `review-performance`, `review-interface`, `review-sourced-claims`), backs opinions with mechanical
  checks, has every BLOCKER and MAJOR verified by an agent that tries to refute it, loops a bounded
  number of fix rounds within a budget, commits `review.md` and posts a `review-harness` status.
- `.sdd/harness.yaml`, generated by `sdd-init`; `--refresh` creates it when absent and never rewrites
  it.
- **The verified merge route** in the git guardrail: `gh pr merge <n> --<MERGE_METHOD>
  --match-head-commit <sha>`, alone in its command, is the only merge the hook lets an agent run,
  and only after asking GitHub itself, within one 40-second deadline, that `<sha>` is the PR's head,
  that the newest `merge-conditions` status of that commit was posted by its workflow and is
  `success` with `gates: none`, judged against the current head of the default branch, and that no
  other PR carries the `in-flight` label. Fail closed when `gh` is missing or a query fails or is
  late. Client-side: it stops mistakes, not a workflow added by the PR that overwrites the status.
  The hook entry in `settings.json` gets `"timeout": 120`; the agent's token needs Issues read.
- Guardrail cases ported from geomni's: the REST merge endpoint and other `gh api` merges or branch
  writes, GraphQL auto-merge, a branch set to track a protected branch (`-u`, `--track`, `branch -c`,
  or created from `origin/main` without `--no-track`), `commit -n`, `update-ref`. Also caught:
  abbreviated long options (`--no-verif`, `--forc`), `core.hooksPath`, `HUSKY=0`, quoted
  subcommands, wildcard and `:` refspecs, `subtree push`, `send-pack`, a posted `merge-conditions`
  status. The suite stubs `gh`, so it still runs offline and in CI.
- `.conf` settings `MERGE_METHOD` (`squash` or `merge`; `rebase` refused, because the deploy guard
  needs the default branch before the merge as one commit) and `ALLOW_FORCE_WITH_LEASE` (default
  `0`; never to a protected branch).
- **The deploy guard**, the server-side barrier: `.sdd/bin/deploy-guard.sh` (logic in
  `merge_conditions.py deploy-guard`), the first step of each deploy job and Vercel's
  `ignoreCommand`, its code read from the last deployed commit, never from the pushed one. It
  deploys a commit of the default branch only when it and every first-parent commit since the last
  deployment are merges of pull requests (their content exactly the merge) with no unaccounted
  trigger hit nor error and their required CI green, recomputed (never read from the
  `merge-conditions` status); a refused commit blocks later deploys until a merged pull request
  reverts it exactly. It does not enforce the owner's gates (owner and agent merges look the same).
  Templates: the guarded deploy job (`concurrency: deploy-<workflow>`, `workflow_dispatch`),
  `deploy-alert.yml` (a `deploy-refused` issue for each refusal), `vercel.json`. Vercel needs a
  read-only `DEPLOY_GUARD_TOKEN` (owner action). The merge route refuses an agent merge while a
  `deploy-refused` issue is open. A deploy job judges only the commits that change its target's
  paths; a target stuck anyway is unblocked by the owner with the repository variable
  `DEPLOY_GUARD_RESET_<TARGET>`. The trusted commit must be on the pushed commit's first-parent line.
- **Deployment profile** `.sdd/deployment.yaml` (targets with trigger, rollback and probes,
  scheduled jobs, or `deploys_nothing: true`), generated by `sdd-init` with unproven values marked
  `unconfirmed`; `merge_conditions.py validate` checks it and lists them.
- **Delivery steps** in the templates: the `in-flight` label in the merge command, the verification
  window (probes, the change's checks, the next run of each scheduled job the diff touches), the
  archive in a second pull request (`<type>/<id>-archive`), rollback then a revert pull request on
  `revert/<id>`, alert, fix change, and the final report format.
- Pull request kind `revert`: a PR adding `openspec/changes/<id>/revert.yaml` is accepted with no
  gate only when its diff is the exact inverse of the change's merges it lists (the newest
  included, all on the default branch's first-parent line); reverting an intent change that is not
  in flight opens the intent gate.
- `merge-conditions` and the guard count a workflow run whose jobs were all skipped as run; `**` in a
  trigger glob crosses a newline, and a file name holding a control character fails the check.

### Changed
- **BREAKING — the git autonomy levels are gone** (`autonomy-commit`, `autonomy-pr`,
  `autonomy-merge`, and `ALLOW_PR_MERGE` in `block-git-writes.conf`). Who merges is decided per pull
  request: the agent pushes and opens PRs, merges only through the verified route, and the owner
  merges every PR with an open gate. `ALLOW_PUSH` stays, with the same meaning (`0`: the agent never
  pushes; set from the `github` option for new installs). `sdd-init` no longer asks for a level; it
  asks for the merge method only when the repository allows both. The install marker drops its
  `autonomy:` field (older markers are still read). `--refresh` migrates an existing `.conf`:
  `ALLOW_PR_MERGE` removed, `MERGE_METHOD` added from the repository's merge settings,
  `ALLOW_FORCE_WITH_LEASE=0` added, `ALLOW_PUSH` and `PROTECTED_BRANCHES` kept; a project that had
  `ALLOW_PR_MERGE=0` now lets the agent merge its ungated PRs, and the refresh asks the owner first.
- The guardrail blocks `git switch -c <b> origin/main` (and `checkout -b`, `branch`, `worktree add
  -b`) when git would make the new branch track `main`: add `--no-track`.
- The cycle commits the implementation per task group **before** the review, which now runs on
  commits; the adversarial pass on proposals is always run, scaled to the change; `code-reviewer`
  alone remains the review for hotfixes, and is the conventions angle inside a change.
- Skill descriptions add about 810 tokens to every session with `sdd-core` and its two dependencies
  (`sdd-core` about 650, up from about 400; `handoff` about 55; `local-qa` about 100).
- `handoff` 0.1.1: the handoff document's git reminder follows the per-pull-request merge (verified
  route, owner on gated pull requests) instead of the autonomy levels.
- A change is delivered in two pull requests (with a GitHub remote): the change, then, after its
  post-deploy verification, the archive. Any `vercel.json`, not only the root one, is gate
  machinery. The `classification.yaml` key `revert_of` is removed (a revert carries `revert.yaml`).

Projects set up with 0.3.0: first `claude plugin install local-qa@claude-toolbox` (above), then
`/sdd-core:sdd-init --refresh`. It brings the new cycle into `CLAUDE.md`, `AGENTS.md`,
`CONTRIBUTING.md`, `OPENSPEC_GUIDE.md`, the agents and `openspec/config.yaml`, creates
`.sdd/harness.yaml`, `.sdd/triggers.yaml`, `.sdd/deployment.yaml` and `.sdd/bin/`, adds
`merge-conditions.yml` and, with a deploy, the deploy guard (above), replaces the hook and migrates
`block-git-writes.conf` (see "Changed"). Their markers carry no commit, so this first refresh
compares two ways (keeping the local version when in doubt) and writes the commit into the marker;
the next refresh merges three ways.

## 0.3.0 — 2026-11-12

### Changed
- **BREAKING — the catalog is renamed `claude-toolbox`** (repository `ghislain95/claude-toolbox`,
  marketplace `name` `claude-toolbox`). A marketplace keeps the name it was added under: remove
  `sdd-kit` and add `ghislain95/claude-toolbox` to switch (see the README). Until then, an existing
  `sdd-kit` install keeps working, once `handoff` is installed (next point).
- The handoff skill moves to its own plugin, `handoff`: `/sdd-core:passation` becomes
  `/handoff:passation`. `sdd-core` depends on it, so installing `sdd-core` installs it too. It still
  writes into `.claude/passation/`. **Updating in place** (auto-update included) does not install a
  dependency added since: run `claude plugin install handoff@<catalog name>` once, otherwise
  `sdd-core` 0.3.0 refuses to load (`Dependency "handoff@…" is not installed`).
- The install marker becomes `claude-toolbox: installed <version>`; the former `sdd-kit: installed`
  marker is still recognised by the version check and rewritten by `--refresh`. Refresh branches and
  commits are named `chore/sdd-init-refresh-<version>` and `chore(sdd-init)`.

### Added
- The four desktop mods live in the catalog under `mods/` (folded in from `claude-mods`, history
  kept), each entry with a category (`workflow`, `skill`, `mod`).
- `.sdd/triggers.yaml`: the toolbox's own release triggers.

Projects set up with 0.2.0: `--refresh` updates the `/handoff:passation` references in the generated
`CLAUDE.md`, `AGENT_TOOLBOX.md` and `OPENSPEC_GUIDE.md`.

## 0.2.0 — 2026-11-07

### Changed
- Everything is in English: README, guide (`TUTO.md` → `GUIDE.md`), skills, templates. Templates are
  now written in English and translated while being filled when a project chooses another docs
  language.
- No reference to the project the workflow was extracted from.

### Added
- `sdd-core` declares `superpowers@claude-plugins-official` as a dependency (the marketplace allows
  that cross-marketplace dependency). The official marketplace must be added first, otherwise
  `sdd-core` refuses to load: the install prompt and the docs do it.
- Curated `permissions.allow` in the generated `.claude/settings.json` (read-only git, OpenSpec,
  `gh run`/`gh pr`, graphify queries, hook tests) plus the module check commands, so "all the way"
  autonomy doesn't stall on permission prompts; `/fewer-permission-prompts` suggested afterwards.
- `graphify-hooks` option: `graphify hook install` (local git hooks keeping the graph fresh) is
  offered with `graphify` and recommended in the docs.
- `ui` option: `.claude/launch.json` generated from the UI modules' dev-server scripts (preview tools);
  `frontend-design` plugin suggested for building UI from scratch.
- CONTRIBUTING: waiting for CI with a fine-grained token (`gh run list` + one background
  `gh run watch --exit-status`), the token's exact permissions and expiry symptoms.
- CLAUDE.md: rules for parallel sessions on one checkout, restating module rules when dispatching an
  agent, never resetting a local database without asking (checksum realignment for comment-only
  edits of an applied migration), one heavy build at a time; agent fallback for the user-invoked
  `review-animations`; `graphify affected` in the add → migrate → remove task rule.
- README "Staying up to date", `CHANGELOG.md`, `MAINTAINING.md`.
- `sdd-core` session-start notice: in a project set up with an older kit than the installed plugin,
  a one-line message suggests `/sdd-core:sdd-init --refresh` (silent everywhere else).
- The desktop mods (`openspec-cockpit`, `conversation-cards`, `session-hud`, `background-tasks`) are
  listed in the marketplace and offered by the install prompt to desktop-app users.

Projects set up with 0.1.0: run `/sdd-core:sdd-init --refresh` (templates changed).

## 0.1.0 — 2026-11-07

- First release: `/sdd-core:sdd-init` (reverse-documentation, then OpenSpec, agents, git guardrail
  hook with autonomy levels, CI), `--refresh`, `passation`, `retro`, `domain-modeling`,
  `improve-codebase-architecture`; optional `sdd-ui` plugin; one-prompt install in the README.
