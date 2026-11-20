---
name: review-harness
description: Full review of an implemented OpenSpec change, before /opsx:verify — review angles selected from the diff, findings adversarially verified, bounded fix rounds, report in review.md. Not for a quick look at a diff (code-reviewer).
argument-hint: "[change-id]"
---

# Review harness

The harness stands in for the owner's eyes on every change that opens no human gate. Its rule:
**every opinion is checked by someone who tries to refute it, and backed by a mechanical check when
one exists.** Finding format for every angle: [`FINDINGS.md`](FINDINGS.md). Configuration schema and
defaults: [`HARNESS_CONFIG.md`](HARNESS_CONFIG.md).

You are the orchestrator: you dispatch agents and keep the count; you do not review or fix yourself.

## 0. Inputs

0. **Commit first**: the harness reviews commits. If `git status --porcelain` shows changes of the
   change (modified or untracked files), commit them on the change branch now, per the cycle's commit
   rules, before anything else; the review, its fixes and its status then all refer to commits.
1. **Change id**: the argument; otherwise the only directory under `openspec/changes/` other than
   `archive/`; otherwise ask the user. Note which of `proposal.md`, `design.md`, `tasks.md` and
   `specs/` exist: the angles need to know (a missing artifact is reported, not guessed).
2. **Diff range**: default branch = `git symbolic-ref --short refs/remotes/origin/HEAD` without its
   `origin/` prefix, else `git config init.defaultBranch`, else `main`. Base = `git merge-base HEAD
   origin/<default branch>` when that ref exists (a stale local branch would widen the diff), else
   `git merge-base HEAD <default branch>`. If that diff is empty (the change
   was committed on the default branch), base = the parent of the first commit that touched
   `openspec/changes/<id>/` (the empty tree, `git hash-object -t tree /dev/null`, when that commit is
   the root commit). Still empty → stop and tell the user there is nothing to review.
   Head = `HEAD`. Record **head reviewed first**. The angles receive the
   exact diff command, two-dot form: `git diff <base> <head>` (a three-dot range fails on the empty
   tree), and the list of changed files.
3. **Settings**: `.sdd/harness.yaml`. Missing file, or a conditional angle without a key → the
   defaults of `HARNESS_CONFIG.md` (said in the report); `angles.<angle>: []` turns the angle off; a
   key for an always-on angle is ignored (and reported as such).
4. **Clock and counter**: start time (`date +%s`); agent runs = 0.

## 1. Select the angles

Always: `spec-conformance`, `conventions`, `bugs`, `tests`, `sourced-claims` (the last one is cheap
and covers comments and commit messages, which every diff has).
**Documentation-only diff** (every changed file is prose: Markdown, text, images): `bugs` and `tests`
are not run, and the report says so with that reason.
Conditional: `security`, `performance`, `interface` — selected when a path of the diff matches a glob
of `angles.<angle>`.

Write the selection, with the reason for each angle left out, at the top of the report.

## 2. Review pass 1 — angles one after the other

For each selected angle, in the order above, dispatch **one** agent with: the change id, the diff
command and the changed files, whether the change branch is the default branch, the artifacts present,
the **absolute paths** of the angle's `SKILL.md` and of `FINDINGS.md` (from this skill's base
directory: `<base>/../review-<angle>/SKILL.md`, `<base>/FINDINGS.md`) for the agent to read and follow,
its `mechanical.<angle>` entries, `budget.effort`, `budget.bug_hunt_level` (for `bugs`), and the
instruction to answer in the format of `FINDINGS.md`.

- **Conventions** is dispatched as the project's `code-reviewer` agent itself, with the
  `review-conventions` skill as its brief, read from its path like every angle's. No `code-reviewer` agent → a general agent with that skill.
  Never ask an agent to dispatch another one.
- Agents run **sequentially**; never two heavy builds at once (`budget.heavy_builds`).
- Before each dispatch, apply the budget rule (§6).

Collect the findings; merge the same location and problem reported by two angles (keep the higher
severity, list both angles).

## 3. Verify every BLOCKER and MAJOR — one verifier per pass

Dispatch **one** verifier agent with all of this pass's BLOCKER and MAJOR findings, verbatim. Its
instruction: for each finding, try to **refute** it — the input cannot occur, the path is
unreachable, the spec allows it, the evidence is misread — and answer one of:

- `confirmed`;
- `confirmed, downgraded to <severity>` with the reason (the defect is real but smaller);
- `refuted` with the reason.

Refuted findings leave the fix list and stay in the report with the refutation. MINOR findings are not
verified: they join the first fix round when there is one (the developer fixes them when cheap), and
are otherwise listed in the report only.

## 4. Fix rounds — `budget.rounds` at most

A **fix round** = the developer fixes the confirmed BLOCKER and MAJOR findings, then a new review
pass checks the result. Review pass n+1 follows fix round n.

1. Findings that are not code — a missing `proposal.md`, `design.md` or `tasks.md`, a decision only the
   owner can take — are marked `owner` and escalated at once, outside the rounds; they keep the status
   at `failure` until resolved. Send the confirmed BLOCKER and MAJOR **code** findings, verbatim, to
   the developer agent: the one the
   project's routing table in `CLAUDE.md` names for the code concerned; none → the agent that
   implemented the change; none → a general agent. It **commits on the change branch** and runs the
   touched modules' tests green before handing back.
   Dispatch the developer only if the budget also covers the review pass that checks its fixes
   (§6); otherwise stop and escalate: fixes are never left unreviewed.
2. Next review pass, on the new commits: re-run the angles that produced those findings, **plus** `conventions` and
   `tests` whenever code changed, on the diff base..new head, then §3.
3. Stop when no BLOCKER and no MAJOR is open. After fix round `budget.rounds` with one still open:
   stop, write the report, escalate to the owner with the open findings and what was tried. Never
   start another round.

## 5. Report, commit and status

Write `openspec/changes/<id>/review.md`:

```markdown
# Review — <id>
Base: <sha> · Head reviewed first: <sha> · Head reviewed last: <sha of the last head a pass reviewed>
Review passes: <n> · Fix rounds: <n> (<m> reviewed) · Duration: <min> · Agent runs: <n>/<budget>
## Angles
| Angle | Ran | Why / why not | Mechanical checks |
## Findings
| # | Angle | Severity | Location | Verification | Status (fixed in round n / refuted / open / minor) |
## Finding lines
<each finding line verbatim, with its mechanical evidence indented below it>
## Refuted and downgraded
<finding line> — <verifier's reason>
## Not covered
<angles skipped for budget, checks impossible locally and moved to post-deploy, missing artifacts>
```

Commit it on the change branch (`docs(<id>): review report`), so it travels with the pull request.
The status below refers to the head reviewed last; the report commit only adds `review.md`.

Status on the head commit, when the branch is pushed:

```bash
gh api "repos/{owner}/{repo}/statuses/$(git rev-parse HEAD)" \
  -f state=<success|failure> -f context=review-harness \
  -f description="<passes> passes, <open> open BLOCKER/MAJOR"
```

- `success` only when zero BLOCKER and MAJOR are open **and** every selected angle ran. A budget stop
  is always `failure`, even with nothing open: the coverage is incomplete.
- No remote or branch not pushed yet → not posted; the report says "status not posted: no remote" or
  "posted after push". Posting refused (token without the commit-statuses permission) → say so in the
  report and to the user. Never claim a status that was not posted.

The status is set by the agent: it prevents forgetting the review, not lying about it. The report in
the pull request is what makes it auditable.

## 6. Budget

- **What counts as an agent run**: every agent you dispatch (angle, verifier, developer), and every
  forked skill an angle invokes (one `code-review` or `security-review` run = one agent run). Angles
  report the forks they made.
- **Rule**: a dispatch that would bring the runs above `budget.agent_runs`, or that starts after
  `budget.minutes` have elapsed, is not made.
- **Minimum to plan for**: pass 1 = selected angles + one fork per forking angle (`bugs`, `security`) +
  1 verifier; each fix round = 1 developer + the re-run angles + their forks + 1 verifier. With the five
  constant angles and one round: about 15 runs; with security selected and three rounds, about 32.
- When the rule stops you: finish the report, list what was not covered, post `failure`, tell the
  owner. Never raise the effort above `budget.effort`; never use an ultracode-scale fan-out.
