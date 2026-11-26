---
name: improve-codebase-architecture
description: Periodic architecture audit — scan the codebase's hot spots for deepening opportunities (shallow modules, leaking seams, untestable interfaces), present them as a visual HTML report, then frame the one the user picks. Run it only when the user asks for an architecture audit or accepts one you proposed (every few changes), never on your own initiative and never mid-change.
argument-hint: "[module, subsystem or pain point to focus on]"
---

# Improve Codebase Architecture

Adapted from mattpocock/skills `improve-codebase-architecture` (MIT); its design vocabulary and
reference files live in the `sdd-core:codebase-design` skill, next to this one.
Surface architectural friction and propose **deepening opportunities**: refactors that turn
shallow modules into deep ones. The aim is testability and agent-navigability.

Read [VOCABULARY.md](../codebase-design/VOCABULARY.md) first and use its terms exactly (**module**, **interface**,
**depth**, **seam**, **adapter**, **leverage**, **locality**, the deletion test, "one adapter =
hypothetical seam, two = real"). Domain names come from `docs/GLOSSARY.md`.

Read-only on source code: this skill produces a report and a framing, never a refactor.

## Ground rules

- `openspec/specs/` is the behavioural source of truth; a deepening must not change observable
  behaviour (APIs, events, messages, UI contracts). A candidate that would is a product change,
  not a refactor — say so.
- **The project's architecture rules are fixed** — read them in `CLAUDE.md` ("Non-negotiable
  rules"), `docs/ARCHITECTURE.md` and each module's `<module>/docs/MODULES.md` /
  `CODING_RULES.md`: fixed root packages or layers, adapters that hold no business logic, a
  domain that doesn't depend on frameworks, shared-code placement in a monorepo, known
  dependency directions (ex. a module that is a **sink** and must not depend on others). A
  deepening never breaks them silently.
- Automated architecture rules (ex. ArchUnit, import-linter, dependency-cruiser, lint
  boundaries — found in the test suite or CI) are enforced invariants, not suggestions: a
  candidate that needs one relaxed is flagged as reopening an architecture decision.
- Respect the conventions and ADRs (`docs/adr/`); don't re-litigate them. Surface an ADR conflict
  only when the friction is real enough to reopen it, flagged in the card.
- Critical paths (the ones listed as costly to break in `CLAUDE.md` §Project identity / the domain risks —
  ex. payment, ingestion → processing → notification) get the highest bar: a candidate there
  states its effect on latency and on the risk of losing or corrupting data.

## 1. Explore

**Scope before you scan (YAGNI).** If the user named a direction, take it. Otherwise:

1. Hot spots: `git log --oneline -60 --name-only` → the files and areas that keep coming back.
2. If `graphify-out/` exists: `graphify check-update .` (then `graphify update .` if stale) —
   never trust a stale graph. Hubs and blast radius: `graphify god-nodes` (⚠️ ignore test
   step/fixture base classes — ex. Cucumber step classes — high degree by construction),
   `graphify affected "<symbol>"` on the hot spots, `graphify explain` on suspected shallow
   modules, `graphify path "<A>" "<B>"` to confirm a suspected coupling. Without a graph: the
   module's dependency/import structure (grep imports, the build's module graph).

Then dispatch a read-only sub-agent (remind it to query the graph before grepping, if there is one) to walk the
hot spots and note friction:

- understanding one concept requires bouncing between many small modules;
- **shallow** modules: interface nearly as complex as the implementation;
- pure functions extracted for testability while the bugs live in how they're called (no **locality**);
- tightly-coupled modules leaking across their seams;
- untested parts, or parts hard to test through their current interface.

Apply the **deletion test** to every suspect. See [DEEPENING.md](../codebase-design/DEEPENING.md) for dependency
categories (ex. a database or broker runnable in tests via Testcontainers / an in-memory stand-in =
local-substitutable; a third-party SaaS API = true external).

## 2. Present candidates as an HTML report

Write a self-contained HTML file to `$TMPDIR/architecture-review-<timestamp>.html` (nothing lands
in the repo), `open` it, and give the absolute path. Follow [HTML-REPORT.md](HTML-REPORT.md):
one card per candidate (files, problem, solution, wins, before/after diagram, strength badge
`Strong` / `Worth exploring` / `Speculative`, ADR callout if any), then a **Top recommendation**.
3–6 candidates max. Don't propose interfaces yet.

Then ask: "Which of these would you like to explore?"

## 3. Framing loop (not a question barrage)

Once the user picks a candidate, frame it **with** them:

- Goal first, then invoke the Skill tool with `grilling:grilling` and grill the user on the
  candidate: its rounds (five questions at most, each with a concrete example — code excerpt,
  before/after call site — and your recommended answer) replace any ad-hoc question list.
- Facts are your job: look them up (graph, code, specs) instead of asking.
- Cover: constraints, dependencies (category per `../codebase-design/DEEPENING.md`), shape of the deepened module,
  what sits behind the seam, which tests survive (interface = test surface; replace, don't layer).
- A wide-blast candidate (its callers — `graphify affected` or grep — cross more than one module) is framed as
  add → migrate callers → remove, each step green.
- To compare alternative interfaces, use [DESIGN-IT-TWICE.md](../codebase-design/DESIGN-IT-TWICE.md).
- New or sharpened domain term → propose it for `docs/GLOSSARY.md` (see the `sdd-core:domain-modeling` skill).

## 4. Outcome

- Accepted candidate → **one line** in `docs/ROADMAP.md`, section "Backlog — flagged
  work" (item | description | size | origin), to be run later as an OpenSpec change.
  No code here.
- Whatever the outcome, update the line `Last architecture audit:` of `docs/ROADMAP.md` (its
  "Update process" section) to today's date: the post-archive step counts the changes archived
  since that date to propose the next audit (`CLAUDE.md` §3).
- Rejected with a load-bearing reason → offer to record it (ADR in `docs/adr/` if it meets the
  three criteria of `sdd-core:domain-modeling`, otherwise a note in the relevant architecture doc) so future
  audits don't re-suggest it. Skip ephemeral reasons ("not now").
