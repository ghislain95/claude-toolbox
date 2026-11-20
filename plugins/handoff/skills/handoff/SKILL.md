---
name: passation
description: Writes a handoff document to resume work in a fresh session (/clear or new conversation) without dragging along the dead ends of the current context. File in .claude/passation/ + copy to the clipboard when available.
argument-hint: "[goal of the next session]"
disable-model-invocation: true
allowed-tools: Write, Bash(mkdir -p .claude/passation), Bash(date *), Bash(command -v *), Bash(LC_ALL=en_US.UTF-8 pbcopy *), Bash(LC_ALL=en_US.UTF-8 pbpaste), Bash(LC_ALL=en_US.UTF-8 pbpaste *), Bash(wl-copy *), Bash(wl-paste *), Bash(xclip *), Bash(cmp *), Bash(echo OK), Bash(git status *), Bash(git log *), Bash(git branch *), Bash(openspec list), Bash(openspec list *)
---

# Passation (handoff)

Why: `/compact` summarises the conversation, but keeps its shape. The dead ends, the wrong
assumptions and the failed debugging stay in. A handoff starts again from scratch with only what
matters. The next session must be able to pick up **exactly** where things stand, without
re-reading this conversation.

If `$ARGUMENTS` is given, it describes the goal of the next session: tailor the whole document to
that goal (whatever doesn't serve it goes).

## 1. Check before writing (not from memory alone)

- `git status --short`, `git log --oneline -5` and `git branch --show-current` for the real state.
- `openspec list` if an OpenSpec change is in progress.
- Every "it's done" claim must be confirmed by a file, a test run or a commit. If it can't be checked
  now, it is marked **assumed**.

## 2. Write the file

Path: `.claude/passation/YYYY-MM-DD-HHMM-<topic-kebab>.md` (gitignored folder; `mkdir -p` if
missing). The local time (hours + minutes, no separator) tells apart several handoffs on the same
day: read it with `date +%Y-%m-%d-%H%M`, never from memory. Prose in the language of the project's
docs (`CLAUDE.md` §Language; English by default). Identifiers, paths and commands as they are.
If `.claude/passation/` is not gitignored yet, tell the user (don't edit `.gitignore` yourself during
a handoff).

Fixed structure. An empty section is written "—"; it is not removed.

```md
# Handoff — <topic> (<YYYY-MM-DD HH:MM>)

> Next session: read this document, restate the goal and the next step to me,
> then **wait for my GO** before acting.

## Goal
<1–2 sentences: what we are trying to achieve, and why.>

## Where things stand
- OpenSpec change: `<id>` — cycle step: framing | adversarial pass | ff | apply | review | verify | commit | archive | post-archive (or "none")
- Branch: `<branch>` — git state: <clean | N modified uncommitted files: which ones>
- <2–4 bullets of factual state>

## Decisions taken
- <decision> — why: <reason> — ✅ validated by the user | 🟡 proposed, not validated

## Tried and failed (don't redo)
- <attempt> → <why it failed / what it taught us>

## Established facts
- ✔ verified: <fact> (evidence: `<file:line>` | `<command>` | commit `<sha>`)
- ? assumed: <unverified fact>

## Key files
- `<path>` — <role in one line>

## Open questions (for the user)
- <question>

## Next step
1. <concrete, immediate action>
2. …

## Suggested tools
- <skill / agent / command> — <what for>

## Mandatory way of working
- <The project's language rules, taken from `CLAUDE.md` §Language.>
- Framing **with** the user: goal first, few questions, one concrete example each. Proposal
  validated by them **before** `/opsx:ff`. Once framing is validated, take the change all the way
  (back end, front end, tests, docs) **without asking for a GO between slices**; only stop for a
  real decision or a design gap.
- `code-reviewer` review of the uncommitted diff before `/opsx:verify`.
- Git: per `docs/CONTRIBUTING.md` §2 and `CLAUDE.md` — `<type>/<change-id>` branch, never on the
  protected branch, Conventional Commits with subject + body, scope = change id. Order: review →
  `/opsx:verify` → implementation commit(s) → `/opsx:archive` + post-archive → archive commit → PR →
  merge: by the agent only through the verified route (`merge-conditions` green with `gates: none`),
  by the owner when a gate is open. The `block-git-writes.sh` hook enforces the mechanical part,
  the merge route included (it checks `merge-conditions` on GitHub before letting the merge run).
- <Environment pitfalls found during the session (runtime version, environment variable,
  port…) — e.g. "the build tool needs a specific runtime version, the default shell has another one".>
- If `graphify-out/` exists: refresh the graph (`graphify check-update .`) before relying on it.
```

## Content rules

- **Don't copy what already exists** (proposal, design, tasks, specs, ADRs, commits, diffs): point to
  it by path. The handoff holds what is written **nowhere else**: spoken decisions, dead ends,
  assumptions, intentions.
- **Dead ends = the most valuable section.** A failed debugging session that isn't recorded will be
  done again.
- **Mark statuses honestly.** A decision mentioned but not confirmed by the user is 🟡.
- Mask secrets (keys, passwords, tokens, signed URLs) and personal data (no real user, customer or
  patient data).
- Dense: aim for 40–120 lines. No chronological account of the session.

## 3. Deliver

1. Clipboard (optional, depending on what is installed — `command -v pbcopy wl-copy xclip`):
   - macOS: `LC_ALL=en_US.UTF-8 pbcopy < <path>`. **The `LC_ALL` prefix is mandatory**: the agent's
     shell has no locale, and `pbcopy` then reads UTF-8 as MacRoman ("é" becomes "√©"). Check the
     round trip: `LC_ALL=en_US.UTF-8 pbpaste | cmp -s - <path> && echo OK`.
   - Linux Wayland: `wl-copy < <path>` then `wl-paste | cmp -s - <path> && echo OK`.
   - Linux X11: `xclip -selection clipboard < <path>` then
     `xclip -selection clipboard -o | cmp -s - <path> && echo OK`.
   - No tool, or the check fails: don't announce "copied"; it is not an error, the file path is
     enough.
2. Reply in 3 lines max: the file path, the clipboard status ("copied (verified)" or "not copied"),
   and the sentence to paste if the user prefers to point to the file:
   `Read .claude/passation/<file>.md and pick up exactly where we left off.`

Don't start any other work: the handoff closes the session.
