---
name: wayfinder
description: Plan an effort too big for one session (several changes, an epic, a migration) as a shared map of decision tickets, on GitHub issues or in docs/wayfinder/, and resolve them one per session until the way to the destination is clear. Charts a new map from a loose idea, or works the next ticket of an existing one.
argument-hint: "[a loose idea to chart | a map (issue number, URL or docs/wayfinder/<map>) [ticket]]"
disable-model-invocation: true
---

# Wayfinder

Adapted from mattpocock/skills `wayfinder` (MIT).

A loose idea has arrived, too big for one agent session and wrapped in fog: the way from here to
the **destination** isn't visible yet. Wayfinding finds that way instead of charging at the
destination. It charts the way as a **shared map**, then works its **decision tickets** (questions
whose resolution is a decision, not slices of a build) one at a time until the route is clear.

Arguments: `$ARGUMENTS`. A loose idea → [Chart the map](#chart-the-map). A map (issue number, URL,
or a folder under `docs/wayfinder/`), optionally with a ticket → [Work through the
map](#work-through-the-map). Nothing → list the open maps (see [Trackers](#trackers)) and ask which
one, or what idea to chart, in one question.

## Plan, don't do

Wayfinder is **planning**: each ticket resolves a decision, and the map is done when nothing is
left to decide before someone does the work. The pull to just do the work is the signal that you
have reached the edge of the map and it's time to hand off. An effort may override this in its
**Notes**, carrying execution into the map; absent that, produce decisions, not deliverables.

## The destination

Naming it is the first act of charting: it fixes the scope and shapes every ticket. It may be a
spec to hand off, a decision to lock before planning, or a change made in place (a data migration).
The map is domain-agnostic.

**In a project that uses `sdd-core`** (an `openspec/` folder and a `CLAUDE.md` describing the
`/opsx:*` cycle), the destination is always the same shape: **a list of changes ready for
`/opsx:new`**, in order, each with:

- a kebab-case change id and a one-line intent;
- its **settled decisions**, each linking the ticket that holds it;
- its dependencies on the other changes of the list;
- what stays out of it.

The map never writes OpenSpec artifacts (`openspec/changes/`, proposals, specs, tasks) nor the
roadmap: those belong to the cycle. When the last ticket closes, the map ends by **proposing the
`/opsx:new <id>` runs**, one line each with the decisions to hand to framing, so the framing
`grilling` starts from them instead of asking them again.

## Refer by name

Every map and ticket has a **name**: its title. In everything the user reads (narration, the map's
Decisions so far), refer to it by that name, with the link inside it, never by a bare number or
slug. A wall of `#42, #43, #44` is illegible; names read at a glance.

## Trackers

The map lives on **GitHub issues** when the repository has a GitHub remote (`gh repo view` succeeds
and `gh auth status` is logged in); otherwise in **local markdown** under `docs/wayfinder/`. Say
which one in the map's Notes; a map never moves between trackers. If the user asks for the other
tracker, use it.

### GitHub issues

| Operation | Command |
|---|---|
| Labels (once per repo) | `gh label create wayfinder:<name> --force` for `map`, `research`, `prototype`, `grilling`, `task` |
| Create the map | `gh issue create --title "<name>" --label wayfinder:map --body-file <file>` |
| Create a ticket | `gh issue create --title "<name>" --label wayfinder:<type> --parent <map> --body-file <file>` |
| Wire blocking | `gh issue edit <ticket> --add-blocked-by <n>[,<n>]` |
| Claim | `gh issue edit <ticket> --add-assignee @me` |
| Frontier | `gh issue view <map> --json subIssues`, then for the open children `gh issue view <n> --json number,title,labels,assignees,blockedBy,state`: open, no assignee, every `blockedBy` closed |
| Resolve | `gh issue comment <ticket> --body-file <file>`, then `gh issue close <ticket>` |
| Open maps | `gh issue list --label wayfinder:map --state open` |

Sub-issues and blocking are GitHub's native relationships: they render the frontier in GitHub's own
UI. If `gh` refuses them (older `gh`, GitHub Enterprise without the feature), fall back to the body:
a `Parent: #<map>` line in the ticket, a `- [ ] #<n> <name>` task list in the map, and a
`Blocked by: #<n>` line. Labels are only `wayfinder:*`, never a triage label like `ready-for-agent`:
tickets are decisions, not implementation work.

### Local markdown

```
docs/wayfinder/<map-slug>/
  map.md                  # the map body (below)
  01-<ticket-slug>.md     # one file per ticket, numbered in creation order
```

Each ticket file starts with front matter that carries what GitHub would:

```yaml
---
type: grilling          # research | prototype | grilling | task
status: open            # open | closed | out-of-scope
blocked_by: [01]        # ticket numbers
claimed_by:             # the user's name or "agent", set before any work
---
```

The frontier is the files with `status: open`, empty `claimed_by` and every `blocked_by` closed.
The resolution goes in a `## Resolution` section of the ticket file. Commit the map's files with
the rest of the work (they are a record, unlike a prototype); open maps are the folders whose
tickets are not all closed.

## The map

One map per effort: the GitHub issue labelled `wayfinder:map`, or `map.md`. Its tickets are its
sub-issues, or its sibling files. The map is an **index**, not a store: a decision lives in exactly
one place, its ticket; the map gists it and links.

```markdown
## Destination

<what reaching the end looks like, in one or two lines; in an sdd-core project, "a list of changes
ready for /opsx:new" plus what the effort is about>

## Notes

<tracker; domain; skills every session should consult; standing preferences for this effort>

## Decisions so far

- [<closed ticket name>](link): <one-line gist of the answer>

## Not yet specified

<in-scope fog you can't ticket yet (see Fog of war)>

## Out of scope

- [<closed ticket name>](link): <gist, and why it is past the destination>

## Changes ready for /opsx:new

<sdd-core projects only, filled as tickets close: id, intent, settled decisions (links), depends on,
leaves out>
```

Open tickets are **not** listed in the map: they are found by the frontier query.

## Tickets

A ticket's body is the question, sized to one agent session:

```markdown
## Question

<the decision or investigation this ticket resolves>
```

Its **type** is its label (or `type:`), never stated in the body. A session **claims** a ticket
before any work, so concurrent sessions skip it: an open, unclaimed ticket is free. A ticket is
**unblocked** when every ticket blocking it is closed; the **frontier** is the open, unblocked,
unclaimed tickets: the edge of the known. The answer is recorded on resolution; assets made while
resolving it are linked, not pasted.

## Ticket types

Every ticket is **HITL** (worked with the user, who speaks for themself) or **AFK** (the agent
alone). A HITL ticket only resolves through that live exchange: the agent never answers the user's
side of it.

- **Grilling** (HITL, the default): a conversation. Invoke the Skill tool with `grilling:grilling`,
  and with `sdd-core:domain-modeling` when that skill is available and the ticket names or disputes
  a domain term. The grilling's settled-decisions summary is the resolution.
- **Research** (AFK): a fact a decision waits on lies outside the working directory
  (documentation, a third-party API, a standard, prices). Dispatch a sub-agent (Agent tool,
  `general-purpose`) with WebSearch and WebFetch and a brief: the question, what the decision needs
  from the answer, and the instruction to cite every source with its date or version, to mark
  anything unverified as such, and to return an **Open decisions** list rather than deciding. Its
  findings, with sources, are the resolution; bulky notes go on a pushed throwaway
  `research/<ticket-slug>` branch (GitHub) or in `docs/wayfinder/<map>/research/` (local), linked
  from the ticket.
- **Prototype** (HITL): when "how should it look" or "how should it behave" is the question, make
  a cheap, rough, concrete thing to react to: an outline, a stub, a page published as a private
  Artifact when that tool is available, or code on a pushed `prototype/<ticket-slug>` branch. It is
  **never merged** and opens no pull request; the ticket links it, and the resolution records what
  the user decided after reacting to it.
- **Task** (HITL or AFK): manual work a decision is blocked on, with nothing to decide (sign up to
  a service to judge its API, get access, look at real data's shape). The agent does it alone where
  it can; otherwise it hands the user a precise checklist. The resolution records what was done and
  the facts later tickets depend on (where credentials are, URLs, counts), never a secret itself.

## Fog of war

The map is deliberately incomplete: don't chart what you can't see yet. **Not yet specified** holds
the dim view of what is coming (a suspected question, an area to revisit), in scope but not sharp
enough to ticket. Resolving a ticket clears the fog ahead of it.

**Fog or ticket?** Whether you can state the question precisely now, not whether you can answer it.
A sharp question becomes a ticket, even blocked. A vague one stays fog; don't pre-slice it: one
patch may become several tickets, or none.

## Out of scope

Fog only gathers toward the destination; work beyond it is out of scope, never fog. A ticket that
turns out to sit past the destination is **closed** (GitHub: `gh issue close --reason "not
planned"`; local: `status: out-of-scope`) with one line in **Out of scope**: the gist and why. It
stays out of Decisions so far, which records the route actually walked. Out-of-scope work comes back
only if the destination is redrawn, as a fresh map.

## Chart the map

The user brings a loose idea. In an sdd-core project, the idea may be a roadmap epic: read it in
`docs/ROADMAP.md` first.

1. **Name the destination.** Invoke `grilling:grilling` (and `sdd-core:domain-modeling` when
   available) to pin down what the map finds its way to. In an sdd-core project its shape is fixed
   (see [The destination](#the-destination)); grill what the effort covers and what it leaves out.
2. **Map the frontier.** Grill again, **breadth-first**: across the whole space, not deep on one
   thread, surfacing the open decisions and the first steps takeable now. **If there is no fog**
   (the way is already clear and fits one session, or one OpenSpec change), there is no map to make:
   say so, and propose `/opsx:new <id>` with the decisions settled, or ask the user how to proceed.
3. **Create the map**: Destination and Notes filled in, Decisions so far empty, the fog sketched
   into Not yet specified.
4. **Create the tickets you can state now**, then wire blocking in a **second pass** (tickets need
   numbers before they can point at each other). Write cross-references in that pass too, with real
   numbers: a placeholder `#<n>` links to an unrelated issue.
5. **Fire the research.** For each `research` ticket just created, dispatch its sub-agent (see
   [Ticket types](#ticket-types)), in parallel, then record each resolution and close the ticket.
6. **Stop.** Charting is one session's work: report the map's link, the frontier by name, and the
   next ticket to work.

## Work through the map

The user brings a map, and maybe a ticket. Without one, you pick the next decision.

1. **Load the map**: its body, not every ticket.
2. **Choose the ticket**: the one named, otherwise the first of the frontier. **Claim it** before
   any work.
3. **Resolve it** as its type says (read the label or `type:`, not the body). Fetch any related or
   closed ticket's full body when needed; invoke the skills the map's Notes name.
4. **Record the resolution**: post the answer (GitHub: a comment; local: `## Resolution`), close the
   ticket, and append its line to Decisions so far. In an sdd-core project, add the decision to the
   change it belongs to under **Changes ready for /opsx:new** (creating that change's entry if it is
   new).
5. **Update the map**: create newly surfaced tickets (create, then wire); graduate the fog the
   answer made specifiable, removing it from Not yet specified; rule out of scope what now sits past
   the destination; update or close the tickets the decision invalidates.
6. **One ticket per session**, research tickets excepted. Then propose `/handoff:handoff` with the
   next ticket as the goal, when that skill is available, rather than starting another ticket in
   this context.

When the frontier is empty and nothing is left in Not yet specified, the way is clear: close the
map (GitHub: `gh issue close <map>`; local: a `Status: done` line at the top of `map.md`) and hand
off. In an sdd-core project, that means listing the **Changes ready for /opsx:new** in order and
proposing each `/opsx:new <id>` run, one line each with the decisions it carries; the user starts
them.

The user may run unblocked tickets in parallel sessions: expect the tracker to change under you,
and re-read a ticket before claiming it.
