# Contributing

Cross-cutting conventions for contributing to {{PROJECT_NAME}}.

---

## 1. Language

- **Prose** (issues, PRs, docs, review comments): **{{DOC_LANG}}**.
- **Code** (identifiers, file names, inline technical comments), **commit messages** and **OpenSpec artifacts**: **{{CODE_LANG}}**.
- No mixing of languages within a single identifier.

## 2. Git

Rules shared by humans and agents.
<!-- sdd:if github -->
Agents (sub-agents included) commit, push and open PRs **themselves**. An agent merges a PR only through the verified route (below: `merge-conditions` green with `gates: none`, checked on GitHub by the hook at merge time); a PR with an open gate is merged by the owner, whose merge stands for the go or the passed QA. The hook described below enforces the mechanical part.
<!-- sdd:endif -->
<!-- sdd:if !github -->
Agents (sub-agents included) commit on the change branch; push and merge stay human: **the agent never pushes**, every `git push` is blocked by the hook (`ALLOW_PUSH=0`). The hook described below enforces the mechanical part.
<!-- sdd:endif -->

### Branches
- `{{DEFAULT_BRANCH}}`: stable branch. It only moves **through <!-- sdd:if github -->a merged PR<!-- sdd:endif --><!-- sdd:if !github -->a merge done by a human<!-- sdd:endif -->**: never a direct commit or push, hotfixes included.
- OpenSpec change: `<type>/<change-id>` — e.g. `feat/user-invitations`, `fix/refresh-token-rotation`. A change delivered in several pull requests names each one `<type>/<change-id>/<lot>` (e.g. `feat/user-invitations/backend`): `merge-conditions` reads the segment after `<type>/` as the change id and ignores the lot. A branch whose id does not name the change folder it touches fails the check.
- Framing of a change: `docs/<change-id>-framing` (a reclassification: `docs/<change-id>-framing-2`, `-3`…) — the change folder only, merged before the change branch is cut.
<!-- sdd:if github -->
- Archive of a change: `<type>/<change-id>-archive` (e.g. `chore/user-invitations-archive`), cut after the post-deploy verification. Revert of a change whose verification failed: `revert/<change-id>`.
<!-- sdd:endif -->
- Outside a change: `<type>/<scope>-<desc>` — e.g. `fix/api-input-validation`, `docs/roadmap-resync`, `chore/tooling-hook-update`.

`<type>` = the branch's main Conventional Commits type; `<scope>` ∈ { <!-- sdd:fill: short module names ({{MODULE_NAME}}), plus `docs`, `tooling`, `ci` --> }; `<desc>` in kebab-case {{CODE_LANG}}.

- Session in a worktree created by the app (imposed branch name): rename the branch according to the convention before the first push (`git branch -m <name>`).
- A branch is deleted after merge, locally (`git branch -d`)<!-- sdd:if github --> and on the remote (`git push origin --delete <branch>`)<!-- sdd:endif -->.

### Commits — Conventional Commits
```
<type>(<scope>): <short imperative description>

<descriptive body: what changes + the key decisions>
```
Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`.

**Scope**
- A commit that belongs to an **OpenSpec change** has **the change id** as scope: `feat(user-invitations): …`, `chore(user-invitations): …`.
- Otherwise, the scope is the **module** (`<module>`, `<module>/<sub-domain>`), or `docs`, `ci`, `tooling` (dev/agent tooling outside a change: hooks, skills).

**Message = subject + descriptive body, always, in {{CODE_LANG}}.** Short imperative subject; the body says what changes (what) and the key decisions; never the one-liner alone. No Claude attribution: no `Co-Authored-By` trailer, no "Generated with Claude Code" mention.

**Commit rules**
- One commit = one coherent slice (a module, the tests, the docs…); no "wip" commits.
- Staging with **explicit paths** (`git add <paths>`): never `git add -A` / `.` / `-u`, nor `git commit -a` — a commit only carries what we decided to put in it.
- Before a **code** commit: checks of the touched module green (the same commands as CI). The review runs on the committed work before the pull request (review harness for an OpenSpec change, `code-reviewer` otherwise). Before any commit touching `openspec/`: `openspec validate --all`.
- Never rewrite: no `--amend`, no `rebase`, no `reset` to a revision, no force-push. A mistake is fixed with a new commit.
- A long message, or one that quotes commands (`--amend`, `` `git pull` ``…): write it to a file and use `git commit -F <file>` (`gh pr create --body-file <file>`), rather than `-m`.

### Sequence of an OpenSpec change
The same order as the cycle in [`CLAUDE.md`](../CLAUDE.md) §3:
0. **Framing**, on `docs/<id>-framing`: `docs(<id>): frame the change` — `proposal.md` and `classification.yaml` ([`OPENSPEC_GUIDE.md`](OPENSPEC_GUIDE.md) §7), checked with `python3 .sdd/bin/merge_conditions.py validate openspec/changes/<id>/classification.yaml`, after the adversarial pass. That branch carries nothing outside `openspec/changes/<id>/`<!-- sdd:if github -->; it is pushed and opened as a pull request titled `docs(<id>): frame the change`, which `merge-conditions` reports as `gates: framing`<!-- sdd:endif -->. **The owner merges it: that merge is the approval** of the proposal and of its classification — the only copy any check reads. Reclassifying later = a new framing branch `docs/<id>-framing-2` amending `classification.yaml` (and the proposal if its scope moved); the change branch waits for its merge, then merges `{{DEFAULT_BRANCH}}` in (`git merge origin/{{DEFAULT_BRANCH}}`, never a rebase).

Then on the `<type>/<change-id>` branch, cut from `{{DEFAULT_BRANCH}}` after the framing merge:
1. `docs(<id>): …` — deltas, design, tasks (`/opsx:ff`, refused while the classification is not on `{{DEFAULT_BRANCH}}`).
2. `/opsx:apply` with `feat|fix|…(<id>): …`, one commit per coherent implementation slice → `/sdd-core:review-harness <id>` (its fixes as further commits, its report as `docs(<id>): review report`) → `/opsx:verify` OK.
<!-- sdd:if github -->
3. Push the branch, PR 1, then the merge (below): by the agent through the verified route when `merge-conditions` reports `gates: none` — the same command ending with `&& gh pr edit <n> --add-label in-flight` —, by the owner otherwise (the agent then labels the PR `in-flight` in a call of its own).
4. Post-deploy verification ([`OPENSPEC_GUIDE.md`](OPENSPEC_GUIDE.md) §8): the probes of each target of [`.sdd/deployment.yaml`](../.sdd/deployment.yaml) the diff deployed, the change's own checks, and the next run of each scheduled job whose paths the diff touches. Passed → `gh pr edit <n> --remove-label in-flight`. Failed → the targets' `rollback` commands, a revert pull request on `revert/<id>` (`git revert` of the merge + `openspec/changes/<id>/revert.yaml`, nothing else: `merge-conditions` accepts only the exact inverse), the label moved to it until its deploy is verified, an alert to the owner with the diagnosis, a fix change.
5. PR 2 on `<type>/<id>-archive`, cut from `origin/{{DEFAULT_BRANCH}}` with `--no-track`: `/opsx:archive` + post-archive → `chore(<id>): archive change, sync specs, post-archive`, merged through the same route. Then the final report to the owner (format: [`OPENSPEC_GUIDE.md`](OPENSPEC_GUIDE.md) §8).
<!-- sdd:endif -->
<!-- sdd:if !github -->
3. `/opsx:archive` + post-archive → `chore(<id>): archive change, sync specs, post-archive`.
4. The agent stops at the last commit; a human pushes and merges.
<!-- sdd:endif -->

Outside a change (hotfix, tooling, docs): same path, shorter — branch `<type>/<scope>-<desc>`, `code-reviewer` review if code changes, commit(s)<!-- sdd:if github -->, PR; `merge-conditions` reports such a PR `gates: unclassified`, so the owner merges it<!-- sdd:endif -->.

### What the hook enforces
The hook [`.claude/hooks/block-git-writes.sh`](../.claude/hooks/block-git-writes.sh) (registered in [`.claude/settings.json`](../.claude/settings.json)) blocks, for an agent (sub-agents included):
- `commit`, `merge`, `revert`, `cherry-pick` on a protected branch. The branch is the one of the directory where the command really runs: the `cwd`, then each `cd`/`pushd`/`popd` and `git -C <dir>` (a subshell gives the directory back when it exits), and a `git switch|checkout <branch>` placed earlier in the same command — to a protected branch, counted immediately; to another branch, only if the next command is chained with `&&` (a failed switch stops the chain). A directory or branch that cannot be resolved (`$VAR`, `$(…)`, `cd -`, nonexistent directory) counts as protected: write literal paths, and run `git worktree add <dir>` in a separate call from the `cd <dir>` that follows;
- any push of a protected branch (including through `HEAD`, `@` or a `$…` reference while on it), a push without an explicit remote **and** branch (`git push -u origin <branch>`), force-push (`--force*`, `-f`, `+refspec`, `--mirror`, `--all`; `--force-with-lease` only with `ALLOW_FORCE_WITH_LEASE=1`, never to a protected branch)<!-- sdd:if !github --> — and here **every** `git push` (`ALLOW_PUSH=0`)<!-- sdd:endif -->;
- a branch set to track a protected branch: `branch -u`/`--set-upstream-to`, `--track`, `branch -c`/`--copy` of a branch that tracks it, or a branch created from `origin/{{DEFAULT_BRANCH}}` without `--no-track` (`git switch -c <branch> --no-track origin/{{DEFAULT_BRANCH}}`, `git worktree add --no-track -b <branch> <dir> origin/{{DEFAULT_BRANCH}}`; git's `branch.autoSetupMerge` decides when a start point is tracked);
- `pull` without `--ff-only`, with rebase, or, on a protected branch, of a branch other than itself;
- a push that writes a protected branch without naming it: a wildcard refspec (`refs/heads/*`), `:` (every matching branch), a destination or a branch to delete written `$…`; `git subtree push` to a protected branch, `git send-pack`; `git subtree add`/`merge`/`pull` on a protected branch;
- history rewriting: `rebase`, `commit --amend`, `reset` to a revision, `branch -f`, `update-ref`, `am`, `commit-tree`, `filter-branch`;
- mass staging: `add -A` / `.` / `./` / `..` / `*` / `-u`, `commit -a`;
- what throws work away: `reset --hard`, `clean -f/--force`, `checkout .`/`-f`, `switch --discard-changes`, `restore .`, `stash drop/clear`, `branch -D`/`-M`;
- skipped hooks: `--no-verify`, `commit -n`, `-c core.hooksPath=…` / `--config-env=core.hooksPath=…`, `HUSKY=0` (or `HUSKY_SKIP_HOOKS`) with a commit, merge or push;
- every blocked long option is also caught abbreviated, since git accepts any unambiguous prefix (`--no-verif`, `--forc`, `--amen`, `--har`), and a quoted subcommand is read unquoted (`git "push"`, `gh pr 'merge'`);
- through `gh api` (each call read on its own text; a `GET` with fields is a read): the REST merge endpoint (`…/pulls/<n>/merge`), `…/merges`, writes to `git/refs/heads/<protected>` or `contents/`, the GraphQL mutations `enablePullRequestAutoMerge`, `mergePullRequest`, `enqueuePullRequest`, `mergeBranch`, `createCommitOnBranch`, `updateRef(s)` (a GraphQL query read from a file or stdin is refused, since it cannot be checked), and posting a `merge-conditions` status (a status posted with `--input` is refused for the same reason: post `review-harness` and `opsx-verify` with `-f` fields);
- every `gh pr merge` except **the single merge route**: `gh pr merge <n> --<MERGE_METHOD> --match-head-commit <sha>`, where `<sha>` is the full head commit you checked (`gh pr view <n> --json headRefOid`), optionally `--delete-branch`, `--subject`, `--body`; never `--admin`, `--auto`, `-R`/`--repo` (before or after `pr`), `GH_REPO`/`GH_HOST`, another method. **It runs alone**: one merge per command, and around it only read-only git and gh commands (`git status`, `git log`, `gh pr view`, `gh run list`, a `GET` through `gh api`…), plus `gh pr edit <n> --add-label in-flight` after it — a push, a commit or a status written in the same command would change what was verified. Before letting it run, the hook asks GitHub itself — never the command line — from the directory where the command runs, within one 40-second deadline for all its queries: the PR is open and targets the default branch, and `<sha>` is its head (GitHub then refuses the merge if the head moves before it runs); the newest `merge-conditions` status **of that commit** was posted by its workflow (`github-actions[bot]`, not a person's token) and is `success` with a description starting `gates: none;`; the `base <sha7>` it names is the current head of the default branch; no other PR carries the `in-flight` label, whatever its state (read through the issues API, every page); no open issue carries `deploy-refused` (a deploy the guard refused, not resolved yet). Otherwise it blocks with the reason: an open gate → hand the merge to the owner; a stale base → wait for the re-judgement; `pending` → wait; another change in flight → wait until it is verified; a refused deploy → the owner resolves it. A failed or late query, an unreadable answer or no `gh` blocks the merge (fail closed). `gh pr merge <n> --disable-auto` alone, which only cancels an automatic merge, stays allowed.

**Settings** — [`.claude/hooks/block-git-writes.conf`](../.claude/hooks/block-git-writes.conf) (committed, read by the hook if present):

| Key | Default | Effect |
|---|---|---|
| `PROTECTED_BRANCHES` | `main\|master` | Protected branches, separated by `\|` (here `{{DEFAULT_BRANCH}}`) |
| `ALLOW_PUSH` | `1` | `1`: the agent pushes its branch (never a protected branch); `0`: every `git push` blocked (a human pushes — a project with no remote the agent may push to) |
| `MERGE_METHOD` | `merge` | `squash` or `merge`, one the repository allows: the method of the merge route (here `{{MERGE_METHOD}}`). `rebase` is refused — the deploy guard needs the default branch before the merge as one commit, which a rebase merge does not leave — and any other value blocks every agent merge |
| `ALLOW_FORCE_WITH_LEASE` | `0` | `1`: `git push --force-with-lease` (with or without `--force-if-includes`) allowed to a non-protected branch; `0`: blocked like any force-push |

Whether the agent may merge is decided per pull request by `merge-conditions`, not per project: there is no setting for it.

Before the checks, the command is read the way the shell reads it: escapes, `#` comments and quoted heredoc bodies are set aside, and quoted strings containing spaces (messages, PR bodies) are neutralised — their text is never read as an option or a command. What the shell executes (`$(…)`, backticks, including inside double quotes or an unquoted heredoc) is still checked.

Tests: `bash .claude/hooks/block-git-writes.test.sh`<!-- sdd:if ci -->, also run in CI on every change to the hook ([`tooling.yml`](../.github/workflows/tooling.yml))<!-- sdd:endif -->.<!-- sdd:if !lean --> Details: [`AGENT_TOOLBOX.md`](AGENT_TOOLBOX.md).<!-- sdd:endif --> It is a **guardrail against mistakes, not a sandbox** (deliberate `sh -c "…"`, `eval` are not covered); without server-side branch protection, the rule "`{{DEFAULT_BRANCH}}` only moves through <!-- sdd:if github -->a PR<!-- sdd:endif --><!-- sdd:if !github -->a human merge<!-- sdd:endif -->" relies on this hook and on this discipline. Without `jq`, the hook blocks every `git`/`gh` command until it is installed.

**Left to the user**, outside git: framing decisions, any spending commitment, any irreversible action on production or on data.

<!-- sdd:if github -->
### Commit statuses
Three statuses on a pull request's head commit decide whether it may merge (one per commit: a new push needs them again):
- `review-harness` — posted by `/sdd-core:review-harness` when its last pass ends (success: zero open BLOCKER/MAJOR and every selected angle ran).
- `opsx-verify` — posted by the agent when `/opsx:verify` passes on the pushed head (`failure` when it reports a CRITICAL issue):
  ```bash
  gh api "repos/{owner}/{repo}/statuses/$(git rev-parse HEAD)" \
    -f state=success -f context=opsx-verify -f description="<n> requirements verified, 0 critical"
  ```
- `merge-conditions` — posted by CI only, never by hand: required workflows green, `review-harness` and `opsx-verify` green (change pull requests), every trigger hit accounted for by the approved classification. Its description reads `gates: <gates>[ - <reason>]; base <sha7>`: the gates (`none`, `intent`, `irreversible`, `intent+irreversible`, `framing`, `unclassified`, `invalid`), when not green the reason, and the commit of `{{DEFAULT_BRANCH}}` the verdict was computed against. A verdict whose `base` is not the current head of `{{DEFAULT_BRANCH}}` is stale: every push to `{{DEFAULT_BRANCH}}` re-judges the open pull requests (`pending`, `re-judging: …`, first). Framing, archive, revert and unclassified pull requests need no `review-harness`/`opsx-verify`.
<!-- sdd:endif -->

### What is enforced where
- **Client-side, on the agent's machine — guards against mistakes**: the git hook above (commands only; a deliberate `sh -c`, `eval` or raw API call gets past it)<!-- sdd:if github -->; the merge route, which is part of that hook: it reads `merge-conditions` from GitHub at merge time and accepts it only from its workflow (`github-actions[bot]`), so it stops an agent that merges too early, with a gate open, on a stale verdict or on a status it posted itself, not a workflow added by the pull request that overwrites the status as the same bot; the `in-flight` label, which the merge route reads to keep one change at a time between merge and verified production — the hook refuses a merge while another pull request carries it; putting it on the merged pull request (in the merge command) and removing it once production is verified or rolled back are delivery steps the agent follows (§2, "Sequence of an OpenSpec change"), **honour-based**: a forgotten label lets the next change merge during a verification; the `review-harness` and `opsx-verify` statuses, **honour-based**: the agent posts them itself, so they prevent forgetting a step, not lying about it — `review.md` and the verify report in the pull request are what make them auditable<!-- sdd:endif -->; the OpenSpec rules that stop `/opsx:ff` and apply without an approved classification.
<!-- sdd:if github -->
- **Server-side, on GitHub**: `merge-conditions`, computed by a workflow that runs the definition, the triggers, the classifications and the path filters of `{{DEFAULT_BRANCH}}`, never those of the pull request, and never executes the pull request's code. A pull request cannot edit that definition, but it can overwrite the result: a workflow it adds posts statuses as the same `github-actions[bot]`, and the agent's token can post any status. So `merge-conditions` protects against mistakes only — it is the input of the client-side merge rule, and it says whether a merge is allowed, it does not prevent one. The **deploy guard** is the server-side barrier: `.sdd/bin/deploy-guard.sh`, the first step of every deploy job and Vercel's `ignoreCommand`, never trusts the status and never runs the pushed commit's code — it is read from the last deployed commit — and recomputes, for the pushed commit and every first-parent commit since the last deployment: a merged pull request merged **as** that commit, its content exactly the merge of that pull request, every trigger hit accounted for, the CI the pull request needed green. A refused commit blocks every later deploy of a target whose paths it changes until a merged pull request reverts it exactly, or the owner sets the target's reset variable `DEPLOY_GUARD_RESET_<TARGET>` (only the owner can: the agent's token has no Variables write); `.github/workflows/deploy-alert.yml` opens an issue labelled `deploy-refused` for each refusal, and while one is open the merge route refuses every agent merge ([`OPENSPEC_GUIDE.md`](OPENSPEC_GUIDE.md) §8). **It does not enforce the owner's gates**: the agent acts with the owner's token, so an owner merge and an agent merge look the same to GitHub; the gates are kept client-side (the merge route) and by the owner merging gated pull requests. Its other limits: the workflow files and `vercel.json` run from the pushed commit (the agent's token has no `workflow` permission, but a direct push by the owner is not stopped); a deploy made outside these pipelines (a manual `gcloud`/`vercel` command, Vercel's redeploy without the ignored build step) is not guarded.
- **Not enforced**: an agent deliberately working around the hook; on a private repository of GitHub Free there is no branch protection and no ruleset, so anyone holding a token that can push a branch can also push `{{DEFAULT_BRANCH}}` or merge a red pull request, and the agent acting with the owner's token cannot be told apart from the owner on GitHub (statuses, approvals, merges). A public repository, or GitHub Pro, can add a ruleset requiring `merge-conditions`.
<!-- sdd:endif -->
<!-- sdd:if !github -->
- **Not enforced**: with no GitHub remote there is no server-side check at all; the merge is a human's act, made after the review, the verify and the gates of the classification (intent QA, irreversible go).
<!-- sdd:endif -->

<!-- sdd:if !github -->
### Merge
- No GitHub remote: the branch is reviewed (review harness, or `code-reviewer` outside a change, with no open BLOCKER or MAJOR; for a change, `/opsx:verify` OK and change archived), then **a human** merges it into `{{DEFAULT_BRANCH}}` as a merge commit (`git merge --no-ff <branch>`).
<!-- sdd:endif -->
<!-- sdd:if github -->
### Pull Requests
- Title = subject of the main commit.
- Description in {{DOC_LANG}}: context, technical choices, impact, tests run<!-- sdd:if ui -->, screenshots<!-- sdd:endif -->. No Claude attribution.
- 1 PR = 1 topic (one OpenSpec change, or one fix). Outside a change, no mixing of modules without a reason.
- Green CI required, as one status: `merge-conditions` ([`.github/workflows/merge-conditions.yml`](../.github/workflows/merge-conditions.yml)). The other workflows in [`.github/workflows/`](../.github/workflows/) are path-filtered, so their absence proves nothing; `merge-conditions` recomputes, from the filters on `{{DEFAULT_BRANCH}}`, which of them the diff requires and waits for each to succeed on the head commit. A PR none of them concerns is still judged (gates, statuses, trigger hits). A PR that deletes, renames or filters out a required workflow, or adds one, fails with that reason (it is gate machinery: the owner merges it).
- Review: the review of the diff is mandatory (review harness for a change, `code-reviewer` otherwise); it counts as the approval when the developer is alone on the repository.
- Waiting for CI with a fine-grained token: `gh pr checks` may fail (it needs permissions such tokens often lack). Use `gh run list --branch <branch>` to find the runs, then a single `gh run watch <run-id> --exit-status` in the background — no polling loop.
<!-- sdd:endif -->
<!-- sdd:if github -->
- **Who merges** is decided per pull request, by `merge-conditions` on its head commit: `success` with `gates: none` → **the agent merges**, through the single route, in a call of its own: `gh pr merge <n> --{{MERGE_METHOD}} --match-head-commit <sha> --subject "<subject> (#<n>)" && gh pr edit <n> --add-label in-flight` (the label for a change or a revert pull request, not for framing or archive ones, which deploy no code), with `<sha>` the head you checked (`gh pr view <n> --json headRefOid`), which the hook lets through only after checking that status, who posted it, its base and the `in-flight` label on GitHub (§2, "What the hook enforces"); any open gate (`intent`, `irreversible`, `framing`, `unclassified`, `invalid`) → the agent gives the PR link and the status, then stops: **the owner merges**, and that merge stands for the QA or the go. A refused merge is never worked around (no REST call, no `--admin`, no `--auto`): wait (pending, stale base, a change in flight) or hand it to the owner.
- After the merge, in the main checkout: `git switch {{DEFAULT_BRANCH}} && git pull --ff-only`, then delete the branch (`git branch -d <branch>`, `git push origin --delete <branch>`). From a worktree, `{{DEFAULT_BRANCH}}` is already checked out elsewhere: only delete the remote branch; the local branch and the worktree are cleaned up from the main checkout (`git worktree remove` then `git branch -d`).
- Access: `gh` must see the repository. On the agent side, a token limited to the repository can be set as `GH_TOKEN` in `.claude/settings.local.json` (gitignored, copied into worktrees by [`.worktreeinclude`](../.worktreeinclude)). **Never in `settings.json`, which is committed.** Fine-grained token, limited to this repository, with exactly: Contents read/write, Pull requests read/write, Issues read (the merge route lists the pull requests labelled `in-flight` and the open `deploy-refused` issues through the issues API), Actions read (and no `workflow` permission: the agent never changes `.github/workflows/`; no Variables write: only the owner sets the deploy guard's reset variables), Commit statuses read/write (the agent posts `review-harness` and `opsx-verify`), Metadata read (template: [`.claude/settings.local.example.json`](../.claude/settings.local.example.json)). Tokens expire: a sudden 404 or 403 from `gh` on a repository that worked yesterday usually means an expired token. Such a token cannot create repositories — that needs a different token or the web UI. Without access, the agent pushes the branch and gives the user the link to open the PR — and it cannot merge: the merge route needs `gh` to read the status (fail closed).
- **Deploy guard access (owner, once)**: in GitHub Actions the guard uses the workflow's own `github.token` (the deploy job and `deploy-alert.yml` declare `contents: read`, `pull-requests: read`, `actions: read`). A platform outside GitHub Actions (Vercel) needs a fine-grained token limited to this repository, **read-only**: Contents, Pull requests, Actions, Metadata — set by the owner as `DEPLOY_GUARD_TOKEN` in the platform's environment variables (Vercel: Settings → Environment Variables, Production, with "Automatically expose System Environment Variables" on). Without it every production build is skipped; an expired one too. **Exposure**: Vercel hands that token to the whole build (the project's build scripts and dependencies can read it), which is why it is read-only and limited to this repository; never give it write access. The repository needs an `in-flight` label (`gh label create in-flight --description "Merged, not yet verified in production"`); `deploy-alert.yml` creates `deploy-refused` itself. **Rebase merges off** (owner, admin right): a "Rebase and merge" of several commits is always refused by the guard, so disable it: `gh api -X PATCH repos/{owner}/{repo} -F allow_rebase_merge=false`.
<!-- sdd:endif -->

## 3. Code style

<!-- sdd:each module -->
### `{{MODULE_PATH}}` ({{MODULE_STACK}})
- See [`{{MODULE_PATH}}/docs/CODING_RULES.md`](../{{MODULE_PATH}}/docs/CODING_RULES.md).
<!-- sdd:fill: 2-3 key rules of the module, taken from its CODING_RULES.md -->
<!-- sdd:endeach -->

## 4. Tests

<!-- sdd:each module -->
- **`{{MODULE_PATH}}`**: {{MODULE_TEST_KINDS}} — `{{MODULE_CHECK}}`. See [`TESTING_STRATEGY.md`](../{{MODULE_PATH}}/docs/TESTING_STRATEGY.md).
<!-- sdd:endeach -->

## 5. Documentation

- Every added feature updates the README of the relevant module if the public API changes.
- Every change to an observable contract **is born in the spec deltas** of the OpenSpec change (`openspec/changes/<id>/specs/`); the docs in `docs/` are updated afterwards, at post-archive (`doc-writer`).
- If a new business concept appears: entry in [`GLOSSARY.md`](GLOSSARY.md).
- A structural decision (technology, cross-cutting contract, architecture style): an ADR in [`adr/`](adr/).

## 6. Security

- Never commit a secret (`.env.local`, CI secrets, `.claude/settings.local.json`).
- Strict validation of every external input.
<!-- sdd:fill: project-specific security rules observed (auth, rate limiting, sensitive data not to log) -->
