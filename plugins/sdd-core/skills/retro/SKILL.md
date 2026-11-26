---
name: retro
description: Retrospective on a coding session (the current one by default) — suggests improvements to the agent ENVIRONMENT (navigation, automated checks, reviewer rules, steering files, tool economy) so future runs go better. Run it only when the user asks for a retro or accepts one you proposed (typically after an OpenSpec archive or a painful session), never on your own initiative.
argument-hint: "[session or change to review]"
---

# Retro

Adapted from mattpocock/skills `retro` (MIT). You are suggesting improvements to the
coding agent's **environment**, not to the product code. Present candidates; change nothing
without the user's GO.

## Steps

1. Read the primary sources for the session the user names (default: the current one). For an
   OpenSpec change, also read its artifacts (`openspec/changes/<id>/` or the archive) and the
   review findings.
2. Look for candidates in these categories:

- **Navigation** — how easy was it to find the right files? Hidden dependencies between files?
  Would a navigation pointer, or (if `graphify-out/` exists) a better `graphify` habit, have helped? _Use when_ the session
  spent long finding information.
- **Automated checks** — could a lint, type check, test, architecture rule (ex. ArchUnit, import-linter,
  dependency-cruiser), CI job or hook have caught
  a mistake the agent made? Read the repo's own checks first (each module's build/dependency
  file and its scripts — ex. `package.json`, `pyproject.toml`, `pom.xml`, `Makefile` — any
  architecture-rule tests, `.github/workflows/`, `.claude/hooks/`), so an existing-but-unwired check is the finding, not a reinvention. _Use when_
  the agent made a mechanical mistake.
- **Reviewer rules** — should `code-reviewer` (`.claude/agents/code-reviewer.md`) gain, lose or
  clarify a rule? Classify first: a **mechanical** violation (banned import, file location, root
  package, fixed pattern) gets a **deterministic check** (architecture-rule test, linter rule, hook, CI job)
  — default to building the check over writing the rule. Keep written rules for genuine judgement
  calls. _Use when_ the reviewer missed something.
- **Steering files** — `CLAUDE.md`, `AGENTS.md`, `.claude/CLAUDE.md`, module `CLAUDE.md`, agent
  definitions, `openspec/config.yaml`, memory feedback files: any instruction that belongs in a
  check instead? Any instruction that changes nothing (no-op)? `CLAUDE.md`/`AGENTS.md` load into
  every context: keep them to navigation pointers and rules that can't be automated.
- **Tool economy** — expensive or repeated tool calls that could be streamlined (blind grep where
  the graph answers, re-reading large files, dumping logs, re-running the full test suite when one
  test file would do)? _Use when_ a call was costly.
- **Information access** — was a crucial piece of information unavailable (server logs, message/queue
  traffic, a doc that doesn't exist)? _Use when_ the agent guessed.
- **Workflow** — did a step of the OpenSpec cycle (framing, adversarial pass, review, verify,
  post-archive, graph refresh if graphify is used) get skipped or misfire? Is a handoff
  (`/handoff:handoff`) overdue?

3. Present candidates **in order of severity**, each with: what happened (evidence), the proposed
   change, its kind (check / rule / pointer / tool), and the file it would touch.

## Reference: implementation vs review

The implementing agent carries the most context pressure (exploration, code, debugging); the
reviewer receives a diff and has the least. Coding standards are therefore best enforced at
**review** (or by a check), not by piling more instructions on the implementer.
