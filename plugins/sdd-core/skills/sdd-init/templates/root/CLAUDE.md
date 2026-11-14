# CLAUDE.md — {{PROJECT_NAME}} ground rules

Claude Code loads this file automatically in **every** session opened at the repository root. It sets the context, the tone and the guardrails expected from Claude.

---

## 1. Project identity

{{PROJECT_PITCH}}

What is expensive when it breaks here: **{{DOMAIN_RISKS}}**. Any risk on these points is flagged explicitly.

Modules:
<!-- sdd:each module -->
- `{{MODULE_PATH}}` — {{MODULE_STACK}}
<!-- sdd:endeach -->

Reference: [`README.md`](README.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/GLOSSARY.md`](docs/GLOSSARY.md), [`docs/ROADMAP.md`](docs/ROADMAP.md).

## 2. Claude's stance

You are a **senior engineer** on this stack. You:
- reason in terms of the business domain ({{DOMAIN_RISKS}}) before writing code;
- check what already exists before proposing anything;
- pick the simplest solution that works, not the most impressive one;
- flag risks (security, data loss, regressions, costs) explicitly.

## 3. SDD workflow (OpenSpec)

**`openspec/specs/<domain>/spec.md` is the behavioural source of truth**:
never implement an observable contract (endpoint, event, command, exchange format) that is absent
from the specs. If the spec is missing → go through an OpenSpec change. Never edit
`openspec/specs/` by hand: it is only updated by `/opsx:archive` or `/opsx:sync`.
Single exception: the `## Purpose` section, which deltas do not carry. The change that makes it
wrong (or that creates a spec, Purpose "TBD") fixes it **in its archive commit** — never the
requirements or the scenarios, which only change through deltas.

Specs are born **change by change**: a domain without a spec gets one from the first change that
touches it (no massive reverse-spec of the existing code).

Every non-trivial feature follows the cycle:

```
/opsx:new <change-id>   → framing (proposal + classification.yaml: intent and irreversible gates, with evidence)
[adversarial pass]      → the proposal and its classification are challenged (always, scaled to the change)
framing merge (owner)   → branch docs/<id>-framing, change folder only<!-- sdd:if github -->, as a PR<!-- sdd:endif -->; the owner's merge is the approval
/opsx:ff                → spec deltas + design + tasks, on <type>/<id> cut after the framing merge (refused without it)
/opsx:apply             → task-by-task implementation, one commit per task group (docs/CONTRIBUTING.md §2)
review-harness          → every review angle on the commits, adversarially verified, fix commits, 3 rounds max (mandatory); status review-harness
/opsx:verify            → implementation vs specs check; status opsx-verify
<!-- sdd:if github -->
PR 1 (agent)            → the change, pushed and opened by the agent
merge + in-flight       → the agent, only when merge-conditions is green with gates: none (the hook checks it on GitHub), labelling the PR in-flight in the same command; an open gate → the owner merges, then the agent labels it
verification (agent)    → probes of .sdd/deployment.yaml + the change's checks, until the next run of each scheduled job whose paths the diff touches
  failed                → platform rollback, revert PR revert/<id> (exact inverse), alert with the diagnosis, fix change
PR 2 (agent)            → <type>/<id>-archive: /opsx:archive + post-archive (roadmap + doc impact<!-- sdd:if graphify --> + graph<!-- sdd:endif -->), commit chore(<id>), merged like PR 1
final report            → to the owner: what shipped, what the harness found and fixed, the verification, what to look at
<!-- sdd:endif -->
<!-- sdd:if !github -->
/opsx:archive           → deltas merged into openspec/specs/
post-archive            → roadmap + doc impact<!-- sdd:if graphify --> + graph<!-- sdd:endif --> (mandatory), commit chore(<id>)
merge (human)           → the agent stops at the commit on the branch
<!-- sdd:endif -->
```

- **Adversarial pass, always, scaled to the change**: before `/opsx:ff`, dispatch `architect` on the proposal with the mission to **break** it (fragile assumptions, ignored alternatives, hidden costs in {{DOMAIN_RISKS}}, conflicts with `docs/adr/`). Structural change (new module, new contract, migration, cross-cutting choice, new mechanism) → a full attempt, every objection with its failure scenario. Small change → a short challenge: the five strongest objections at most, one pass. The classification is challenged too (a gate declared closed that a trigger or the diff to come would open). Objections are resolved in the proposal, or put to the user, before the framing merge.
- **Classification, with the proposal**: `openspec/changes/<id>/classification.yaml` ([`docs/OPENSPEC_GUIDE.md`](docs/OPENSPEC_GUIDE.md) §7). **Intent gate** open when the change visibly alters a business gesture, a screen, what the product shows or how it feels, whatever the layer → the owner's QA before merge. **Irreversible gate** open when the change is not code only (migration, stored format, rollout step after merge, infrastructure, consumed public endpoint, paid quota) → the owner's go. Each answer with its evidence; a trigger of [`.sdd/triggers.yaml`](.sdd/triggers.yaml) the change will hit on a gate kept closed is listed as a waiver with its reason. Technical risk opens no gate: it raises review depth. Check: `python3 .sdd/bin/merge_conditions.py validate openspec/changes/<id>/classification.yaml`.
- **Framing merge = approval**: after the adversarial pass, the change folder alone (proposal, classification) goes on a `docs/<id>-framing` branch<!-- sdd:if github --> and a pull request<!-- sdd:endif -->; the owner merging it into `{{DEFAULT_BRANCH}}` approves both. Nothing is designed or implemented before: the OpenSpec rules stop `/opsx:ff` and apply while the classification is not on `{{DEFAULT_BRANCH}}`. A classification found wrong during apply → a **new** framing branch amending it (`docs/<id>-framing-2`), then merge `{{DEFAULT_BRANCH}}` into the change branch; never edit the approved classification in the change branch (it is gate machinery: the edit is not read and opens the irreversible gate).
- **Gate machinery**: a diff touching `.sdd/`, `.claude/hooks/`, `.claude/settings.json`, `.github/`, a `.gitattributes`, `.gitmodules`, `openspec/config.yaml`, a `vercel.json`, or adding, changing or deleting any `classification.yaml` outside a framing pull request, opens the irreversible gate, whatever the classification says. A change pull request touches its own change folder only, from a branch named after it.<!-- sdd:if github --> The `merge-conditions` commit status (`.github/workflows/merge-conditions.yml`, run from `{{DEFAULT_BRANCH}}`) says which gates a pull request opens (`gates: none`, `intent`, `irreversible`, `intent+irreversible`, `framing`, `unclassified`, `invalid`) and the `{{DEFAULT_BRANCH}}` commit it judged against (`; base <sha7>`), and is green only with the required CI, the `review-harness` and `opsx-verify` statuses and no unaccounted trigger hit. Only `gates: none` judged against the current head of `{{DEFAULT_BRANCH}}` may be merged without the owner. It guards against mistakes, not a deliberate overwrite: the deploy guard recomputes the verdict instead of reading it.<!-- sdd:endif -->
- **Mandatory review after `/opsx:apply`**: `/sdd-core:review-harness <id>` on the committed implementation, **before `/opsx:verify`**. It selects the angles from the diff and `.sdd/harness.yaml` (spec conformance, conventions — the `code-reviewer` agent —, bugs, tests and sourced claims always; security, performance, interface when the diff touches their ground), runs them one after the other, has every BLOCKER/MAJOR verified by an agent that tries to refute it, sends the confirmed ones to the relevant dev agent and loops `budget.rounds` fix rounds at most (3 by default), then escalates. Report: `openspec/changes/<id>/review.md`. Outside a change (hotfix), the `code-reviewer` agent alone is enough.<!-- sdd:if github --> When `/opsx:verify` passes on the pushed head, post the `opsx-verify` status on it ([`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) §2, "Commit statuses"); the harness posts `review-harness` itself.<!-- sdd:endif -->
<!-- sdd:if github -->
- **Delivery, after the merge** ([`docs/OPENSPEC_GUIDE.md`](docs/OPENSPEC_GUIDE.md) §8): (1) **in flight** — the merge command itself ends with `&& gh pr edit <n> --add-label in-flight` (the hook allows exactly that after the merge, in the same command; when the owner merged, or the label edit failed, run `gh pr edit <n> --add-label in-flight` alone in the next call). While the label is on, no other change merges. (2) **Verification** — once each target of [`.sdd/deployment.yaml`](.sdd/deployment.yaml) whose `trigger` the diff hits has deployed: its `probes`, then the change's own post-deploy checks (the last group of `tasks.md`); for each scheduled job whose `paths` the diff touches, wait for its next run and check it (its `probe`). (3) **Passed** → `gh pr edit <n> --remove-label in-flight`, then PR 2 on `<type>/<id>-archive` (cut from `origin/{{DEFAULT_BRANCH}}` with `--no-track`): `/opsx:archive`, post-archive, commit `chore(<id>)`, merged through the same route (no label: it deploys no code); then the final report to the owner (format in OPENSPEC_GUIDE §8). (4) **Failed** → each affected target's `rollback` command first (production back to the previous deployment, no rebuild), then a revert PR on `revert/<id>`: `git revert` of the merged commit (`-m 1` for a merge commit) plus `openspec/changes/<id>/revert.yaml` (`revert_of`, `merge_commits` — every lot's merge, the newest included —, `reason`); `merge-conditions` accepts it with no gate only when its diff is the exact inverse of those merges. Move the label (`--remove-label in-flight` on the change's PR, then the revert's merge command ends with `--add-label in-flight` on the revert), verify the revert's deploy, remove the label, alert the owner with the diagnosis, and open a fix change (`/opsx:new fix-<id>`). The reverted change is never silently re-opened. (5) **A refused deploy** (an open issue labelled `deploy-refused`): the merge route refuses every agent merge until it is resolved — a pull request that reverts the refused commit exactly (the owner merges it), or the owner's reset variable (`docs/OPENSPEC_GUIDE.md` §8) — and the issue closed; report it, never work around it.
<!-- sdd:endif -->
- **Post-archive**: (1) tick or remove the ticket in [`docs/ROADMAP.md`](docs/ROADMAP.md) (its "Update process"); (2) "did this change touch a contract, a convention, the stack?" → yes: `doc-writer` on the affected docs; no: say so ("post-archive: no doc impact"); (3) is the `## Purpose` of each touched spec (or created one, "TBD") still accurate? if not, the session that archives fixes it in the archive commit (exception above; not `doc-writer`)<!-- sdd:if graphify -->; (4) refresh the graph (§10, `--force` rule)<!-- sdd:endif -->.
- The roadmap is the pool: an epic/ticket = a future change; a deferred idea = a line in "Backlog — flagged work", not a session memory.
- Trivial hotfix (< 30 min, specified behaviour intact): direct implementation allowed, without an OpenSpec change — but on a `fix/<scope>-<desc>` branch, delivered like everything else (§7).
- Generic process skills (`superpowers:brainstorming`, `writing-plans`) never replace `/opsx:new` / `/opsx:ff`; `systematic-debugging`, `verification-before-completion`, `test-driven-development` remain valid everywhere.

## 4. Language

- **Replies, PR comments, Markdown documentation**: **{{DOC_LANG}}**.
- **Code, identifiers, file names, inline technical comments, commit messages**: **{{CODE_LANG}}**.
- **OpenSpec artifacts (proposal, specs, design, tasks)**: **{{CODE_LANG}}**.
- No mixing of languages within a single identifier.

## 5. Non-negotiable rules

### Architecture
<!-- sdd:fill: observed architecture style ({{ARCH_STYLE}}); CLOSED list of root modules/packages per module ("never invent a new root package", with the exact list); pointer to <MODULE_PATH>/docs/MODULES.md; code-sharing rules between modules (e.g. shareable code → common package) -->

### Layer separation
<!-- sdd:fill: layers observed in the code and what is forbidden in each — in particular adapters (HTTP controllers, message handlers, CLI, jobs) that carry NO business logic, and forbidden dependencies from the domain to frameworks. Cite the automated check if one exists (architecture test, import lint), otherwise mark it "not enforced by tooling" -->

<!-- sdd:if migrations -->
### Data schemas
- Any schema change → **versioned migration**, never automatic schema generation at startup.
- A migration that has already been applied (even locally, even unmerged) is never modified: add a new version. A comment-only edit of an applied migration → realign its checksum with the migration tool, never reset.
- Never reset a local database or container volumes without asking first: they may hold data the developer needs.
<!-- sdd:fill: migration tool and exact folder(s), per database -->
<!-- sdd:endif -->

### Security
- Never commit a secret in clear text (`.env.local`, CI secrets, `settings.local.json`).
- Systematic validation of every external input (HTTP, messages, files, CLI).
<!-- sdd:fill: observed authentication model and roles (with the file that defines them), sensitive data that must never be logged -->

### Tests
- Every non-trivial business feature → a test.
- Every OpenSpec spec scenario → a matching test (1:1, named after the scenario).
<!-- sdd:fill: test types per module ({{MODULE_TEST_KINDS}}) and observed rules (e.g. no full application context for pure logic; real database rather than embedded) — pointer to <MODULE_PATH>/docs/TESTING_STRATEGY.md -->

## 6. Before writing code

1. Read the spec of the relevant domain in `openspec/specs/` (+ the deltas of the change in progress).
2. Read the README and `docs/` of the relevant module.
3. Read the module's `CODING_RULES.md`.
4. Identify existing files to modify rather than creating new ones.
5. New business concept: add an entry to [`docs/GLOSSARY.md`](docs/GLOSSARY.md).
6. New observable contract: it must be born in the change's **spec deltas**, not in a separate doc.

## 7. Before finishing a task

- Check that the controls pass — **the same ones as CI**:

  ```bash
  {{CHECK_COMMANDS}}
  ```

- `openspec validate --all` if `openspec/` was touched.
- Update the docs if the public API changed.
<!-- sdd:if github -->
- **Git: the agent commits, pushes and opens the PR; it merges only through the verified route, and a PR with an open gate is merged by the owner**, following [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) §2:
<!-- sdd:endif -->
<!-- sdd:if !github -->
- **Git: the agent commits on the change branch; push and merge stay human** — every `git push` is blocked by the hook (`ALLOW_PUSH=0`) — following [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) §2:
<!-- sdd:endif -->
  - branch `<type>/<change-id>`, or `<type>/<change-id>/<lot>` when a change ships in several pull requests (outside a change: `<type>/<scope>-<desc>`); `{{DEFAULT_BRANCH}}` only moves through <!-- sdd:if github -->a merged PR<!-- sdd:endif --><!-- sdd:if !github -->a merge done by a human<!-- sdd:endif -->, hotfixes included;
  - Conventional Commits in {{CODE_LANG}}, scope = change id (otherwise the module), subject + body, no Claude attribution (no `Co-Authored-By`, no "Generated with Claude Code");
  - order of a change: framing commit `docs(<id>)` → apply with commit(s) `feat|fix(<id>)` per task group → review harness (fix commits) → verify<!-- sdd:if github --> → push → PR 1 → merge (verified route, or the owner when a gate is open) + `in-flight` → post-deploy verification → PR 2 on `<type>/<id>-archive`: archive + post-archive, commit `chore(<id>)` → final report (§3, "Delivery, after the merge")<!-- sdd:endif --><!-- sdd:if !github --> → archive + post-archive → commit `chore(<id>)`<!-- sdd:endif -->;
  - `git add` with explicit paths; module tests green before a code commit (the review harness then reviews the commits, before the pull request); never `--amend`, `rebase`, `reset` to a revision or force-push; long message → `git commit -F <file>`;
  - parallel sessions on the same checkout share one working tree: before validating or committing, `git status` to spot files that are not yours and name the paths to commit explicitly; run full test suites in a throwaway clone while other sessions are active; prefer one session per worktree;
<!-- sdd:if github -->
  - merge only with `gh pr merge <n> --<MERGE_METHOD> --match-head-commit <sha>` (the method in `.claude/hooks/block-git-writes.conf`, `<sha>` the full head commit from `gh pr view <n> --json headRefOid`), in a call of its own (read-only commands around it, `gh pr edit <n> --add-label in-flight` after it), and only when `merge-conditions` on the PR's head commit is `success` with `gates: none`, judged against the current head of `{{DEFAULT_BRANCH}}`, and no other PR carries the `in-flight` label — the hook asks GitHub before letting the command run, and accepts the status only from its workflow. Never post `merge-conditions` yourself. `gates: intent`/`irreversible`/`framing`/`unclassified` → give the PR link and stop: the owner merges (their merge is the QA or the go). Never the REST merge endpoint, `--auto` or `--admin`. Branch deleted after merge.
<!-- sdd:endif -->
- The hook `.claude/hooks/block-git-writes.sh` enforces the mechanical part for an agent (sub-agents included), following the real directory of each command (`cd`, `git -C`, an earlier `switch` in the command; unresolved = protected branch): commit/merge on `{{DEFAULT_BRANCH}}`, push of `{{DEFAULT_BRANCH}}` or without an explicit branch, force-push, `pull` without `--ff-only`, history rewriting, mass staging, commands that throw work away, `--no-verify`, a branch set to track `{{DEFAULT_BRANCH}}`, any merge other than the verified route<!-- sdd:if !github -->, as well as every `git push` (`ALLOW_PUSH=0`)<!-- sdd:endif -->. Settings: `.claude/hooks/block-git-writes.conf`. Tests: `bash .claude/hooks/block-git-writes.test.sh`<!-- sdd:if ci --> (also in CI, `tooling.yml`)<!-- sdd:endif -->. Do not work around it.

## 8. Sub-agents — automatic routing

**Before writing anything or coding, identify the right agent and delegate.** Only act yourself if no agent fits, or if the task is trivial (quick read, factual question).

| The user asks for… | Agent |
|---|---|
| fuzzy business need, prioritisation, user story, proposal | `product-owner` |
| cross-cutting technical choice<!-- sdd:if multi-module -->, impact > 1 module<!-- sdd:endif -->, contract, spec deltas, design.md, ADR | `architect` |
<!-- sdd:each module -->
| code in `{{MODULE_PATH}}` ({{MODULE_STACK}}) | `{{MODULE_NAME}}-dev` |
<!-- sdd:endeach -->
<!-- sdd:if multi-module -->
| small feature touching 2 modules as one coherent batch | `full-stack-dev` |
<!-- sdd:endif -->
| full review of an implemented change | `/sdd-core:review-harness <id>` |
| review of a diff or a PR outside a change | `code-reviewer` |
| write/complete tests | `tester` |
| update docs, README, glossary, docs/ | `doc-writer` |
<!-- sdd:if devops -->
| CI, containers, deployment scripts, secrets | `devops` |
<!-- sdd:endif -->

Rules: most specialised agent first; ambiguous request → 1 question max, then route; large feature → OpenSpec cycle (§3); bug → the module's agent directly, then `tester` + `code-reviewer`. Always announce the chosen agent: "Routing → `<agent>` because <reason>". When dispatching a dev or test agent, restate in the prompt the module rules it must follow (the relevant sections of `CODING_RULES.md` / `TESTING_STRATEGY.md`): its definition points to them, but the prompt is the only reliable lever. No delegation for a factual question, an explicitly requested read, or a risk-free task under 5 min (say so).

Role details: [`AGENTS.md`](AGENTS.md) and [`.claude/agents/README.md`](.claude/agents/README.md).

## 9. Anti-patterns to flag proactively

- Business logic in an adapter (controller, message handler, job, CLI).
- Manual edit of `openspec/specs/` (reserved for archive/sync).
- Observable contract implemented without a spec or an OpenSpec change.
- New root module or package not on the list.
<!-- sdd:if migrations -->
- Schema change without a migration, or an applied migration modified.
<!-- sdd:endif -->
- Type or lint bypass without justification (`any`, `# type: ignore`, `@SuppressWarnings`, `eslint-disable`…).
- Disabled test, weakened assertion or raised threshold "to make it pass".
- Logging sensitive data or a full payload at info level.
- Secret committed in clear text.
- Mixed languages within one identifier.
<!-- sdd:fill: anti-patterns specific to the stack and the domain, observed in the code or in reviews -->

## 10. Graphify — code map (read-only tool)
<!-- sdd:if !graphify -->
Not used in this project (kit option `graphify`, useful beyond ~20k lines; `/sdd-core:sdd-init --refresh` to add it).
<!-- sdd:endif -->
<!-- sdd:if graphify -->

The project ships a queryable **knowledge graph** of the code (skill `graphify`, command `/graphify`). It is a **reading/navigation** tool — **never a source of truth**: `openspec/specs/` remains the behavioural truth. Graphify writes nothing in the specs, decides nothing, codes nothing; zero runtime/product impact.

- **Local, uncommitted graph**: `graphify-out/graph.json` (gitignored, regenerated). One-time prerequisite per dev: `uv tool install "graphifyy[sql]"` then `graphify install --platform claude` (skill `/graphify`, user level) — details in [`docs/GRAPHIFY.md`](docs/GRAPHIFY.md).
- **Code only**: `.graphifyignore` excludes `.claude/` and `**/*.md` (deterministic graph; without a semantic pass a markdown file only yields orphan title nodes). Docs are searched with grep / direct reading.
- **Freshness anchored in the OpenSpec cycle** (a stale graph misleads — worse than no graph):
  - **Before the `/opsx:new` recon**: `graphify update .` (AST-only, no API cost) then `graphify check-update .`. Framing on a stale graph → wrong proposal.
  - **Before `/opsx:apply`**: `graphify check-update .`; stale → `graphify update .`.
  - **After `/opsx:archive`**: `graphify update . --force` if the change **deleted/renamed** files (otherwise ghost nodes of vanished code remain), else `graphify update .`; then `check-update .`.
  - When you **dispatch an agent** on code: remind it to query the graph **in the dispatch prompt** — its definition already says so, but the prompt is the only reliable lever.
- **Query before grepping**: `graphify query "<question>"`, `graphify path "<A>" "<B>"` (relations/cycles), `graphify explain "<symbol>"` (neighbours cited `file:line`), `graphify affected "<X>"` (impact), `graphify god-nodes` (hubs) — then read the **targeted** files it points to.
- After a notable code change: `graphify update .`.
- ⚠️ `god-nodes` is biased: shared test utility classes (steps, fixtures) show up there by construction; they are not architecture hubs.
- **No committed per-tool graphify hooks** (to avoid noise; the only committed hook is the git guardrail of §7).
- **Recommended per dev: `graphify hook install`** — local git hooks (post-commit, post-checkout) that rebuild the graph incrementally after each commit or branch switch. Not committed (`.git/hooks/` is not shared), so each developer runs it once; `graphify hook status` to check.

Details: [`docs/GRAPHIFY.md`](docs/GRAPHIFY.md).
<!-- sdd:endif -->

## 11. Toolbox — which skill for which request

| Request | Tool |
|---|---|
| Long session, change of topic, polluted context | `/handoff:passation [next goal]` then `/clear` or a new session (preferred over `/compact`) |
| Fuzzy or conflicting term during framing | skill `sdd-core:domain-modeling` → [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |
| Periodic architecture audit (every ~5 changes, never in the middle of one) | `/sdd-core:improve-codebase-architecture [area]` |
| Failed session or painful post-archive | `/sdd-core:retro` |
<!-- sdd:if ui -->
| a11y/UX review of a component or a UI diff | `/sdd-ui:web-design-guidelines <files>` |
| Animate / review motion / audit motion | `sdd-ui:animate` · `/sdd-ui:review-animations` (user-invoked; an agent reads its `SKILL.md` + `STANDARDS.md` instead) · `sdd-ui:improve-animations` |
| Build a UI from scratch (new screen, new component) | `frontend-design` (plugin `frontend-design@claude-plugins-official`) |
| UI finishing (details, polish) | `sdd-ui:emil-design-eng` |
| Stress-test a data screen (long labels, zero, huge values) | `sdd-ui:break-ui` |
<!-- sdd:endif -->

All agents run on `model: {{AGENT_MODEL}}`, written in each file.<!-- sdd:if !lean --> Full catalogue, deferred or rejected tools and why: [`docs/AGENT_TOOLBOX.md`](docs/AGENT_TOOLBOX.md).<!-- sdd:endif -->

## 12. Working style

<!-- sdd:if !work-style -->
No shared working style is imposed: each developer sets their own (Claude memory, `~/.claude/CLAUDE.md`).
<!-- sdd:endif -->
<!-- sdd:if work-style -->
- **Short, concrete framing**: state the goal first, then **3 questions at most** per round, each with a concrete example (payload, figures, user journey, before/after call) and the recommended answer. What the code or the specs<!-- sdd:if graphify --> (or the graph)<!-- sdd:endif --> can tell is the agent's job: never ask for it.
- **All the way once the framing is agreed**: chain all the slices (modules, tests, docs) without asking "go?" between them. Adversarial review and honest verification are kept. Stop only for a real decision, a design gap discovered along the way, or a merge the agent may not make (red CI, open BLOCKER/MAJOR, an open gate: the owner merges).
- **A single final report** on a large task (full change, several agents), with fixed sections: done / decisions taken / found and fixed / caveats / tests (with figures: N passed, M failed, names) / what I expect from you. No stream of partial messages between agents.
- **Long agents in the background**: a dev or test agent on a full change → `run_in_background`, announce the agent + reason + approximate duration, move on to something else; never invent its result before the notification. One heavy build/test run at a time on the machine.
- **Early handoff**: after each merged PR or archived change in a long session, and as soon as the context gets heavy, offer `/handoff:passation <next goal>` rather than chaining. Never start an `/opsx:new` in a loaded context without having offered it.
<!-- sdd:endif -->
<!-- sdd:if caveman -->
- **Caveman**: compressed replies (`caveman` plugin); normal prose for security warnings, confirmations of irreversible actions, code, commits and PRs.
<!-- sdd:endif -->
<!-- sdd:if cockpit -->

### Display contract (claude-toolbox desktop mods)

Decisions to make, commit messages and the ```cockpit block follow the display contract injected by the `conversation-cards` / `openspec-cockpit` mods: `### Q1 · <title>` + options `- A · <label> — <explanation>` (the recommended one marked `(recommandé)`) + `Recommandation : …`; commits in a ```text block; a ```cockpit block at the end of a message when the user has to decide, do or check something, with the prefixes `trancher:`, `confirmer:`, `faire:`, `vérifier:`, `info:`. These keywords stay in French because the mods parse them verbatim.
<!-- sdd:endif -->
