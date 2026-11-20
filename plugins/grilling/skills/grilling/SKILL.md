---
name: grilling
description: Interview the user in rounds about a plan, a design or a change before anything is built, until every decision it depends on is settled. Use when the user says "grill me", asks to stress-test or challenge a plan, when a framing or a design rests on decisions nobody has taken yet, or when an adversarial review returns objections the user must decide. Not for questions the code or the docs can answer.
---

# Grilling

Adapted from mattpocock/skills `grilling` (MIT).

Interview the user until you both share one understanding of the plan. Map it as a **design
tree**: every decision branches into the decisions that hang off it.

## Who grills

Only a session that is talking to the user. A sub-agent never grills: it cannot hear the answer.
A sub-agent that meets an open decision ends its result with an **Open decisions** list (each with
a concrete example and its recommended answer), and the main session turns that list into a round.

## Rounds

The **frontier** is every decision whose prerequisites are already settled: the questions you can
ask *now* without guessing at answers you have not heard yet. Ask the frontier in rounds of **five
questions at most**, the most consequential first; the rest wait for the next round. A question
whose answer depends on another question still open in the round belongs to a later round.

Each answer reshapes the tree: settled decisions push the frontier outward and unblock what hung
off them. Recompute the frontier after every round.

## Format of a question

If the session has a display contract for decisions (for example the one the claude-toolbox
`conversation-cards` mod injects: `### Q1 · <title>`, options `- A · <label> — <explanation>`, the
recommended one marked, then one recommendation line), follow it exactly. Otherwise:

```
### Q1 · <short title>
<one or two lines of context: why this decision matters now, with one concrete example —
figures, a payload, a user journey, a before/after call>
- A · <option> — <what it means, its cost or risk> (recommended)
- B · <option> — <what it means, its cost or risk>
Recommended: A, because <reason>.
```

Word each question so that accepting your recommendation is one word.

## Facts are your job

Finding facts is never the user's job. When a question needs a fact from the environment (code,
specs, docs, git history, tools), look it up yourself, or dispatch a sub-agent with a fresh context
to find it. Do not block on it: a running lookup is an unsettled prerequisite, so only the questions
downstream of it wait; ask the rest of the frontier now. The **decisions** are the user's: put each
one to them and wait.

## Vocabulary

When an answer introduces a domain term, or uses one that is fuzzy or conflicts with the project's
glossary, and a domain-modeling skill is available (`sdd-core:domain-modeling` in a project set up
with sdd-core), invoke it on that term before moving on.

## End

The session is done when the frontier is empty: every branch visited, nothing silently assumed.
Then write a **Settled decisions** summary — one line per decision, its answer, and who took it
(the user, or "recommendation accepted") — and ask the user to confirm it. Do not act on the plan
before they confirm. In a project with a workflow (for example OpenSpec framing), that summary is
the input of the next step: hand it over verbatim.
