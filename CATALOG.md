# claude-toolbox catalog

Every plugin and skill in this toolbox: what it does, when it fires, and who fires it. Pick à la
carte, or install `sdd-core` for the whole spec-driven workflow ready to use.

**Ask your agent.** In any Claude Code session, paste:

```text
Read https://github.com/ghislain95/claude-toolbox/blob/main/CATALOG.md (or
~/.claude/plugins/marketplaces/claude-toolbox/CATALOG.md if the marketplace is added), look at this
project and at what I already have installed (claude plugin list), and tell me which plugins of
claude-toolbox would help here, why, and the commands to install them. Install nothing yet.
```

## How a skill fires

The goal is that you never have to remember a skill. Each one has one of three modes:

| Mode | Who starts it | Examples |
|---|---|---|
| **auto** | The model, on its own, when the situation matches the skill's description. In a project set up with `sdd-core`, the agents too: each agent has the `Skill` tool and its definition names the skills it invokes and when | `grilling` at framing, `superpowers:test-driven-development` before production code, `sdd-core:domain-modeling` on a new term |
| **proposed** | You, after the agent proposes it in one line at a defined moment. These skills cost money or context, so they never start on their own | `/handoff:handoff` before a heavy phase, `/sdd-core:improve-codebase-architecture` after five archived changes |
| **manual** | You, when you want it | `/sdd-core:sdd-init`, `/grilling:grill-me` |

The moments at which skills are proposed are written in the `CLAUDE.md` that `sdd-init` generates
(§3, "What the agent proposes"). Outside an `sdd-core` project, a proposed skill is only proposed if
your own `CLAUDE.md` says when (one line is enough, e.g. "Propose `/handoff:handoff` when the
context gets heavy or before a long new task").

## Ready to use: `sdd-core`

```bash
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin marketplace add ghislain95/claude-toolbox
claude plugin install sdd-core@claude-toolbox
```

Installs `sdd-core` and its dependencies `superpowers`, `handoff`, `grilling` and `local-qa`. Then
`/sdd-core:sdd-init` in a project reverse-documents its code and installs the cycle, the agents, the
review, the git guardrail and the CI ([`README.md`](README.md), [`GUIDE.md`](GUIDE.md)).

What fires at each step of the cycle, once a project is set up:

| Step | Main session | Agents |
|---|---|---|
| Framing (`/opsx:new`) | `grilling` with you until the decisions are settled; `domain-modeling` on a new or disputed term | `product-owner` writes the proposal from the settled decisions |
| Adversarial pass | a `grilling` round on the open objections | `architect` tries to break the proposal |
| Design (`/opsx:ff`) | — | `architect`, with `codebase-design` on a structural change |
| Implementation (`/opsx:apply`) | routing to the dev agents | dev agents: `test-driven-development`, `systematic-debugging`, `verification-before-completion`; `tester` |
| Review | `/sdd-core:review-harness` and its angles | `code-reviewer` (conventions angle), verifiers, dev agents for the fixes |
| Verify, QA | `/opsx:verify`; `/local-qa:qa-prepare` proposed when the intent gate is open | — |
| Archive, post-archive | `/opsx:archive`; `improve-codebase-architecture` proposed after five archived changes; `retro` proposed after a painful review | `doc-writer` |
| Any time | `/handoff:handoff` proposed before a heavy phase or when the context gets heavy | — |

Generic process skills that would compete with the cycle (`superpowers:brainstorming`,
`writing-plans`, `executing-plans`, `subagent-driven-development`, `requesting-code-review`,
`finishing-a-development-branch`) are set aside phase by phase in the generated `CLAUDE.md`.

## Plugins and skills

### `sdd-core` — the spec-driven workflow

| Skill | Mode | What it does | When |
|---|---|---|---|
| `/sdd-core:sdd-init` | manual | Reverse-documents the project's code, then generates `CLAUDE.md`, the agents, the OpenSpec rules, the git hook and the CI from what it proved. `--refresh` brings a project up to the latest kit, keeping local edits | Once per project; again after each kit update |
| `/sdd-core:review-harness` | auto (a task of every change) | Full review of an implemented change: angles chosen from the diff, every BLOCKER/MAJOR checked by an agent that tries to refute it, three fix rounds at most, report in `review.md` | After `/opsx:apply`, before `/opsx:verify` |
| `review-*` (8 angles) | internal | Briefs the harness hands to its agents: spec conformance, conventions, bugs, tests, sourced claims, security, performance, interface | Run by the harness only |
| `sdd-core:domain-modeling` | auto | Challenges domain terms against `docs/GLOSSARY.md`, proposes the canonical one, updates the glossary once you decide | Framing, design, a new or conflicting term |
| `sdd-core:codebase-design` | auto | Deep modules, seams, dependency categories, "design it twice" | `architect` on a structural change |
| `/sdd-core:improve-codebase-architecture` | proposed | Hot-spot audit of the codebase, HTML report of deepening candidates, framing of the one you pick into a roadmap line | Every five archived changes, never mid-change |
| `/sdd-core:retro` | proposed | Retrospective on the agent's environment (navigation, checks, reviewer rules, steering files) | After a review that needed two fix rounds or more, or a failed session |

Depends on `superpowers` (official marketplace), `handoff`, `grilling`, `local-qa`.

### `grilling` — stress-test a plan before building it

| Skill | Mode | What it does | When |
|---|---|---|---|
| `grilling` | auto | Interviews you in rounds over a tree of decisions: five questions at most per round, each with the recommended answer; facts are looked up, never asked; ends with a "settled decisions" summary | "Grill me", a plan or design resting on decisions nobody took, framing, open review objections |
| `/grilling:grill-me` | manual | Starts a grilling session on what you describe | When you want to be challenged |

Works in any project. From `mattpocock/skills` (MIT), adapted.

### `handoff` — resume in a fresh session

| Skill | Mode | What it does | When |
|---|---|---|---|
| `/handoff:handoff [next goal]` | proposed | Writes `.claude/handoff/<date>-<topic>.md`: goal, state, decisions, dead ends, verified vs assumed facts, next step; copies it to the clipboard | Before a heavy phase, after a merge in a long session, when the context gets heavy or the topic changes. Preferred over `/compact` |

Works in any project. Files written before 0.2.0 are in `.claude/passation/`; the desktop mods read
both folders.

### `local-qa` — the owner's QA on a shared machine

| Skill | Mode | What it does | When |
|---|---|---|---|
| `/local-qa:qa-prepare <id>` | proposed | Local environment for a change beside the other projects' services (reuses what is compatible, starts the rest on free ports, its own database when the change migrates) and a QA brief: link, 3 to 6 gestures, before/after captures. `--cleanup` stops only what it started | A change that alters what the user sees or does (intent gate) |

### `sdd-ui` — optional, for projects with a web interface

| Skill | Mode | What it does |
|---|---|---|
| `sdd-ui:web-design-guidelines` | auto | Accessibility and UX lint of UI files, as `file:line` remarks |
| `sdd-ui:break-ui` | auto | Worst-case data (long labels, zero, huge counts, missing fields) to stress a screen |
| `sdd-ui:emil-design-eng` | auto | UI polish and the details that make an interface feel right |
| `sdd-ui:animate` | auto | Builds an animation, deciding in order: whether to animate, purpose, tool, properties, timing |
| `/sdd-ui:review-animations` | manual | Strict review of motion code (the review harness reads it for UI diffs) |
| `sdd-ui:improve-animations` | auto | Motion audit of a codebase and self-contained plans; the plans feed `/opsx:new`, not a parallel process |

### Desktop mods — Claude desktop app only

`openspec-cockpit` (OpenSpec cockpit pane), `conversation-cards` (messages as cards, display
contract), `session-hud` (session band), `background-tasks` (background pane). Details:
[`mods/README.md`](mods/README.md).

## Third-party tools the workflow relies on

| Tool | From | Used for |
|---|---|---|
| `superpowers` | `claude-plugins-official` | TDD, systematic debugging, verification before completion |
| OpenSpec (`/opsx:*`) | `@fission-ai/openspec` (npm) | Specs as the source of truth, changes, archive |
| `frontend-design` | `claude-plugins-official` | Building a UI from scratch (optional) |
| graphify | `graphifyy` (uv) | Queryable code map, for large codebases (optional) |
| caveman | `JuliusBrussee/caveman` | Compressed replies (optional, per developer) |

## Coming next

- `wayfinder` (from `mattpocock/skills`): planning an effort larger than one change as a map of
  decision tickets on the issue tracker, before framing the changes it yields.
