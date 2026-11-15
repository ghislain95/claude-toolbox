<!-- sdd:note: do not generate with the lean option (single module, small project); remove this comment -->
# {{PROJECT_NAME}} — Agent toolbox

Catalogue of the skills, hooks and checks adopted for AI-assisted development of {{PROJECT_NAME}},
**and of those rejected, with the reason**, so the evaluation is not redone. Base: the
`claude-toolbox` catalog (plugins `sdd-core`<!-- sdd:if ui --> and `sdd-ui`<!-- sdd:endif -->), installed by `/sdd-core:sdd-init`.

The everyday "request → tool" table is in [`CLAUDE.md` §11](../CLAUDE.md).
This document is the full catalogue. Every tool added or removed is recorded here, with its date.

## 1. Principles

- **OpenSpec is the process.** "Full cycle" packs (spec → plan → build → test → review →
  ship) overlap with what OpenSpec already does; we take ideas from them, not the plugins.
- **Never a whole plugin that duplicates superpowers.** Competing `tdd` / `debugging` /
  `code-review` skills trigger at random. We *vendor* the useful skill, alone.
- **Read before installing.** A `SKILL.md` becomes instructions for the agent: read it in
  full, check there are no scripts or side effects, then copy it into
  `.claude/skills/<name>/` with `LICENSE` and `SOURCE.md` (repository, commit, date, modified or not).
- **Few skills.** Every skill description enters the context of every session and
  may trigger out of place. A skill that is not used is removed.
- **A mechanical rule becomes a check, not an instruction** (hook, architecture test, lint,
  CI). Written instructions are reserved for judgement calls.

## 2. Adopted

| Tool | Source | What it is | When |
|---|---|---|---|
| OpenSpec (`/opsx:*`) | [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) (npm CLI `@fission-ai/openspec`) | Specs as source of truth + changes (proposal, deltas, design, tasks), archive that merges the deltas | Every non-trivial feature ([`OPENSPEC_GUIDE.md`](OPENSPEC_GUIDE.md)) |
| superpowers | official plugin `claude-plugins-official` | `brainstorming`, `systematic-debugging`, `test-driven-development`, `verification-before-completion`… | Everywhere, except as a replacement for `/opsx:new` / `/opsx:ff` |
| `/handoff:passation` | `handoff` (ideas: mattpocock `handoff`) | Handoff document: goal, state, decisions, tried and failed, verified vs assumed facts, key files, next step, working style. Written to `.claude/passation/` (gitignored) + clipboard | Before `/clear` or a new session, as soon as the context gets heavy or the topic changes |
| `/local-qa:qa-prepare` | `local-qa` | Local QA environment for a change on a machine shared with other projects and agents: inventory of containers and listening ports by project and worktree, compatible services reused, the rest started on free ports and recorded in `.claude/qa/started.json` (gitignored), a database of its own when the change carries a migration; the owner's brief (link, 3 to 6 gestures with expected results, before/after captures); `--cleanup` stops only what it started | Intent gate open, after the agent's own QA, before the owner's merge |
| `/sdd-core:review-harness` | `sdd-core` | Full review of an implemented change: angles selected from the diff and `.sdd/harness.yaml` (`review-spec-conformance`, `review-conventions`, `review-bugs`, `review-tests`, `review-security`, `review-performance`, `review-interface`, `review-sourced-claims`), every BLOCKER/MAJOR verified by an agent that tries to refute it, three fix rounds at most, report in `review.md` | After `/opsx:apply`, before `/opsx:verify` |
| `sdd-core:domain-modeling` | `sdd-core` (mattpocock, adapted) | Challenges terms against [`GLOSSARY.md`](GLOSSARY.md), proposes the canonical term, updates the glossary when the user decides | Framing, design; also read by `product-owner`, `architect`, `code-reviewer` |
| `/sdd-core:improve-codebase-architecture` | `sdd-core` (mattpocock, adapted) | Hotspot audit (git<!-- sdd:if graphify --> + graphify<!-- sdd:endif -->) → report of "shallow" modules → framing of the chosen candidate → line in [`ROADMAP.md`](ROADMAP.md), section "Backlog — flagged work" | By hand, every ~5 changes, never in the middle of one |
| `/sdd-core:retro` | `sdd-core` (mattpocock, adapted) | Retro on the agent's **environment**: navigation, automated checks, reviewer rules, steering files, tool economy | After a painful archive or a failed session |
<!-- sdd:if ui -->
| `/sdd-ui:web-design-guidelines` | `sdd-ui` (vercel-labs/agent-skills) | Accessibility / UX lint (`aria`, focus, forms, reduced motion…) as `file:line`, rules fetched online at each run | Review of every UI change |
| `sdd-ui:break-ui` | `sdd-ui` (emilkowalski/skills) | Worst-case data (long labels, huge counters, zero, missing fields) behind a DEV-only toggle; the user flips it and judges | Before shipping a data screen |
| `sdd-ui:emil-design-eng`, `sdd-ui:animate`, `/sdd-ui:review-animations`, `sdd-ui:improve-animations` | `sdd-ui` (emilkowalski/skills) | UI polish, building an animation in the right decision order, review of motion code, motion audit. ⚠️ `improve-animations` plans are **inputs** for `/opsx:new` or the roadmap, not a parallel process | Polishing a component, new transition, review of a diff that touches motion |
<!-- sdd:endif -->
| Hook [`block-git-writes.sh`](../.claude/hooks/block-git-writes.sh) | `sdd-core` (mattpocock `git-guardrails`, adapted) | `PreToolUse` on Bash: enforces the mechanical part of the git rules ([`CONTRIBUTING.md`](CONTRIBUTING.md) §2). Reads the command the way the shell does (heredocs, quotes, substitutions), follows the real directory (`cd`, `git -C`, `switch`). Settings in `block-git-writes.conf`. Measured cost: ~70-110 ms per call; a `gh pr merge` also costs the merge route's five `gh` queries to GitHub (a few seconds, one 40-second deadline, fail closed; the hook's timeout in `settings.json` is 120 s) | Always on ([`.claude/settings.json`](../.claude/settings.json)); also applies to sub-agents. Without `jq`, it blocks every `git`/`gh` command. Accepted false positives: an unescaped `$(…)` that would really run a forbidden git command, even inside a message → quote the heredoc delimiter (`<<'EOF'`) or use `git commit -F <file>`; a directory created in the same command before the `cd` counts as nonexistent → two calls; a `git switch <branch>; git commit` without `&&` is judged on the starting branch; a branch created from `origin/{{DEFAULT_BRANCH}}` needs `--no-track` (git would make it track `{{DEFAULT_BRANCH}}`). `git <op> --abort/--quit` stays allowed |
<!-- sdd:if ci -->
| GitHub Actions CI | `sdd-core` | [`openspec.yml`](../.github/workflows/openspec.yml): `openspec validate --all` (pinned CLI) + "specs modified without a change" guard. `checks-<module>.yml` (one per module, in [`.github/workflows/`](../.github/workflows/)) or the project's existing CI: each module's checks. [`tooling.yml`](../.github/workflows/tooling.yml): regression suite of the git hook | On every PR and push to `{{DEFAULT_BRANCH}}`, path-filtered |
<!-- sdd:endif -->
<!-- sdd:if graphify -->
| Deterministic graphify graph | graphify (`uv tool install "graphifyy[sql]"`, skill via `graphify install --platform claude`) | Queryable code map; [`.graphifyignore`](../.graphifyignore) excludes `.claude/` and `**/*.md`: the graph only contains code (see [`GRAPHIFY.md`](GRAPHIFY.md)) | Always; to search the docs: grep / direct reading |
<!-- sdd:endif -->
<!-- sdd:if caveman -->
| caveman | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | Compressed replies (~-75% tokens), status line | Developer's choice, at user level |
<!-- sdd:endif -->
<!-- sdd:if cockpit -->
| desktop mods (`openspec-cockpit`, `conversation-cards`, `session-hud`, `background-tasks`) | [claude-toolbox `mods/`](https://github.com/ghislain95/claude-toolbox/tree/main/mods) | Desktop app mods: OpenSpec cockpit, messages as cards, session band, background tasks | Desktop app only, at user level |
<!-- sdd:endif -->
<!-- sdd:fill: project-specific automated checks already in place (architecture test, import lint, migration guard…) — or nothing if none -->

### Ideas built into the agents (no new skill)

- **Hidden quality drop** (idea: addyosmani `constraint-driven-development`) → `code-reviewer`:
  new disabled or skipped test, warning suppression (`@SuppressWarnings`, `# type: ignore`,
  `@ts-ignore`, `eslint-disable`), weakened assertion, raised threshold or timeout, silent `catch`,
  `continue-on-error` in CI = BLOCKER unless justified in writing.
- **Sourced decisions** (idea: addyosmani `source-driven-development`) → `architect` and the
  `design` rule of `openspec/config.yaml`: a decision that depends on a library cites its source **at the
  version pinned in the repo**, otherwise it is marked "unverified".
- **Add → migrate → remove** (idea: mattpocock `to-tickets`) → `architect` and the `tasks` rule of
  `openspec/config.yaml`: a wide-radius change is split into three steps, each with a
  green build.
- **Facts are the agent's job** (idea: mattpocock `grilling`) → `product-owner`: during
  framing, never ask the user what the code, the specs or the graph can tell.
- **Adversarial pass** → `architect` and [`CLAUDE.md` §3](../CLAUDE.md): before `/opsx:ff` on a
  structural change, try to break the proposal (fragile assumptions, ignored
  alternatives, hidden costs, conflicts with an ADR).
- **Order tested according to the contract** → `tester`: an order assertion only if the spec imposes
  an order; otherwise an order-insensitive comparison, or a shuffled fixture for a sorting test.

## 3. Deferred: reconsider when the need appears

| Tool | Why not now | Trigger |
|---|---|---|
<!-- sdd:if ui -->
| impeccable (pbakaus) | Good general design pack, but it downloads a native binary, installs per-project hooks and duplicates other UI skills | Visual redesign: try it **instead of** another UI pack, not on top |
| addyosmani `/webperf` | Lighthouse / Core Web Vitals audit | Public production launch of a web front end |
<!-- sdd:endif -->
<!-- sdd:if graphify -->
| graphify semantic pass on the docs | No usable backend without an API key (see [`GRAPHIFY.md`](GRAPHIFY.md)) | API key for a cheap model available |
<!-- sdd:endif -->
<!-- sdd:fill: tools spotted during sdd-init but not installed, with their trigger — or remove the line -->

## 4. Rejected

| Tool | Reason |
|---|---|
| Whole mattpocock / addyosmani plugins | Collisions with superpowers; mattpocock's `implement` **commits on its own**; Addy's cycle duplicates OpenSpec |
| `grill-me` / `grilling` | Duplicates `brainstorming` and the `product-owner` framing |
<!-- sdd:if ui -->
| taste-skill | Its `SKILL.md` explicitly excludes "dashboards, data tables, multi-step product UI" |
| `minimalist-ui` | Its bans (no Inter, no shadows, no Lucide icons) clash with most existing design systems |
| anti-ai-slop (hallmark & co) | No reference source; marketing page generators |
<!-- sdd:endif -->
| Playwright MCP, agent-browser | Duplicate the app's built-in browser and Claude in Chrome. Revisit only for scripted E2E (Playwright test, not MCP) |
| `find-skills` | `npx skills find <query>` does the same |
| CI architecture guard based on `grep` | A real architecture test (ArchUnit, import-linter, dependency-cruiser…) does better and runs with the tests |
| "Token-saving" proxy that rewrites shell outputs (`git`, `grep`…) | JetBrains study: +7.6% cost at low effort (p=0.004), no gain at high effort; self-reported savings inflated because Claude Code already truncates outputs. Corrupted outputs observed: `git log` missing the last 2 commits, `grep` returning 0 results on a non-empty diff |
| Automatic per-request routing to a cheaper model | Mid-turn behaviour undocumented; explicit per-agent routing is kept |

## 5. Models and sessions

- **All agents run on `model: {{AGENT_MODEL}}`**, written explicitly in each
  `.claude/agents/*.md` rather than inherited: a session started on a cheaper model does not
  silently degrade an agent.
- **`/compact` or `/handoff:passation`?** `/compact` keeps the shape of the conversation, dead ends
  included. Prefer the handoff + a fresh session as soon as the topic changes or after a
  laborious debug.
- **Messaging between sessions** (`SendMessage` / `ListAgents`, native): possible, but the handoff
  covers the need more simply.
