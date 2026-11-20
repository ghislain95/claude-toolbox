# Roadmap

> **Status**: <!-- sdd:fill: state in one line + date of the last resync with the code ({{INSTALL_DATE}} at install time) -->
> **Audience**: engineers (Claude agents included), product owner, reviewers.
> **Goal**: <!-- sdd:fill: goal of the next version, taken from the README / docs / existing issues; with no source: "To be confirmed by the product owner." — do not ask a question for this -->

For product context, read [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`GLOSSARY.md`](GLOSSARY.md) first.

The roadmap is the workflow's **pool**: an epic/ticket = a future OpenSpec change
(`/opsx:new`); a deferred idea = a line in "Backlog — flagged work", not a session
memory.

---

## Vision

<!-- sdd:fill: 3-5 lines taken from the README and existing docs: what the product enables, for whom; with no source: "To be confirmed by the product owner." (invent nothing, ask no question) -->

## Out of scope

<!-- sdd:fill: what this version explicitly does not aim for — or "To be defined with the product owner." -->

## Phasing

### Order agreed on {{INSTALL_DATE}}

<!-- sdd:fill: order of the epics if it already exists (docs, issues); otherwise "To be defined with the product owner." — any decision that changes it will be dated here -->

## Progress ({{INSTALL_DATE}})

Count of tickets ticked `✅` over the number of tickets in each epic's table. Legend: ✅ delivered · 🟡 partial (ticket open) · ⬜ not started.

| EPIC | Title | State | Tickets delivered | Notable remainder |
|---|---|---|---|---|
<!-- sdd:fill: one line per real epic (issues, existing backlog); none → remove the table and write "No epic yet: the first framing (`/opsx:new`) will create one." -->

---

<!-- sdd:fill: real epics if any exist (issues, existing backlog), each in the format: `## EPIC n — title`, **User story** "As a … I can … so that …", **Tickets** table (# | Description | Size S/M/L), **Dependencies**. None → nothing here. Features ALREADY present in the code do not become tickets: they are described in ARCHITECTURE.md -->

---

## Backlog — flagged work (outside epics)

Work identified along the way, not yet attached to an epic. Each item
becomes an OpenSpec change to frame (`/opsx:new`) when it is prioritised.

| Item | Description | Size | Origin |
|---|---|---|---|
<!-- sdd:fill: debt or gaps found during the reverse documentation (significant TODO/FIXME, missing tests on a critical module, missing architecture check…), one line each, Origin = "sdd-init ({{INSTALL_DATE}})" — or one line "— | Nothing flagged | — | —" -->

---

## Update process for this roadmap

- Last architecture audit: none yet — `/sdd-core:improve-codebase-architecture` writes its date here; the post-archive step proposes the next one once five changes are archived after it (`CLAUDE.md` §3).

- Each completed ticket is ticked or removed. Ticking = prefixing the description with `✅` and citing the change that delivered it ("— delivered by `<change-id>` (date)"), at post-archive (`CLAUDE.md` §3). A closed "Backlog — flagged work" line is removed.
- Prefix legend:
  - `✅` delivered: `` | 1.1 | ✅ <description> — delivered by `<change-id>` (YYYY-MM-DD) | M | ``. The date is the **folder prefix** in `openspec/changes/archive/` (uniform, verifiable convention). Without an archived change (hotfix, tooling): `` delivered by `<short hash>` (commit date) ``. Any caveat (test skipped outside CI, test double…) goes at the end of the line: ` — caveat: …`; only tick if the promised behaviour exists.
  - `🟡` partial: `` | 3.2 | 🟡 <description> — partial: delivered by `<id>` (date); remaining: <what is missing> | M | ``. A `🟡` is never "almost ticked": it is a ticket still open, whose line says exactly what remains.
  - No prefix = not done; if useful, a ` — ⚠️ <finding>` suffix (no tick).
  - A gap between a ticket's text and the delivered code is fixed in the line, compactly: `(actual: …)`.
- At each tick, recount the "Progress" table (`✅` tickets over the epic's number of tickets) and update its date.
- Keep the "Order agreed" of the Phasing section up to date: any decision that changes it is dated there.
- Each new ticket follows the format `EPIC X — # — Description — Size (S/M/L)`.
- Any major epic evolution = an ADR in `docs/adr/`, then an update here.
- The `product-owner` agent is the guardian of this document's business consistency.
