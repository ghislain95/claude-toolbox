# AGENTS.md — the Claude virtual team for {{PROJECT_NAME}}

<!-- sdd:note: lean option → do not use this file: generate AGENTS.md from AGENTS.lean.md -->

This document describes how to run a **product team** carried entirely by Claude Code, with specialised roles. Each role is defined by a file in [`.claude/agents/`](.claude/agents/) and can be invoked through the `/agents` command (or `claude --agent <name>`).

---

## 1. Why sub-agents?

- **Specialisation**: each agent has a targeted system prompt (PO, dev, reviewer…). It does not do another agent's job.
- **Clean context**: a sub-agent works in its own context. The main context stays light.
- **Rigour**: a reviewer agent is not softened by the author of the code (itself another agent).
- **Reproducibility**: the same task prompts the same role the same way.

---

## 2. Roles

| Agent | When to invoke it | Typical tools |
|---|---|---|
| **product-owner** | Frame a new business need, write a user story, prioritise, identify product impacts | Read, Grep, Glob, WebFetch, Edit, Write (`proposal.md`), Bash (read-only) |
| **architect** | Design a cross-cutting feature: spec deltas + `design.md`, adversarial pass, ADR if structural | Read, Grep, Glob, Edit, Write (change artifacts, ADR), Bash (read-only) |
<!-- sdd:each module -->
| **{{MODULE_NAME}}-dev** | Implement in `{{MODULE_PATH}}` ({{MODULE_STACK}}) following its `CODING_RULES.md` | Read, Edit, Write, Bash, Grep, Glob |
<!-- sdd:endeach -->
<!-- sdd:if multi-module -->
| **full-stack-dev** | Small feature touching two modules as one coherent batch | All |
<!-- sdd:endif -->
| **code-reviewer** | Review of a PR / a diff: strict, line by line, no praise | Read, Grep, Bash (git diff, checks) |
| **tester** | Write / complete tests (each module's tools: `<module>/docs/TESTING_STRATEGY.md`) | Read, Edit, Write, Bash |
| **doc-writer** | Update the docs after a feature (READMEs, `docs/`) | Read, Edit, Write |
<!-- sdd:if devops -->
| **devops** | CI, containers, build/deployment scripts, secrets | Read, Edit, Write, Bash |
<!-- sdd:endif -->

**All agents run on `model: {{AGENT_MODEL}}`**, written explicitly in each file rather than inherited from the session: a session started on a cheaper model does not silently degrade an agent. The tools and skills available as backup are catalogued in [`docs/AGENT_TOOLBOX.md`](docs/AGENT_TOOLBOX.md).

---

## 3. Typical workflow for a feature

The workflow relies on **OpenSpec**: the change artifacts
(`openspec/changes/<id>/` — proposal, spec deltas, design, tasks) are the
contract handed from one agent to the next.

```
1. product-owner     ← /opsx:new: proposal.md (intent, scope, non-goals)
1b. architect        ← adversarial pass on the proposal, if the change is structural
2. architect         ← /opsx:ff: spec deltas + design.md + tasks
3. <module>-dev      ← /opsx:apply: the module's tasks<!-- sdd:if multi-module --> (modules in parallel once the contract is stable)<!-- sdd:endif -->
<!-- sdd:if devops -->
3b. devops           ← /opsx:apply: if CI/infra/secrets are affected
<!-- sdd:endif -->
4. tester            ← 1 delta scenario = 1 test
5. commit            ← by the agent, one per task group, on the change branch (docs/CONTRIBUTING.md §2)
6. review-harness    ← every review angle on the commits, code-reviewer included (mandatory, before verify)
7. /opsx:verify      ← implementation vs specs, tasks ticked
<!-- sdd:if github -->
8. PR 1 + merge      ← the agent opens the change's PR; it merges only through the verified route
                       (merge-conditions success, gates: none, checked by the hook on GitHub) and
                       labels it in-flight in the same command; an open gate → the owner merges,
                       the agent then labels it
9. verification      ← the session that merged: probes of .sdd/deployment.yaml + the change's checks,
                       until the next run of each scheduled job the diff touches; failed → platform
                       rollback, revert PR (revert/<id>), alert to the owner, fix change
10. PR 2 (archive)   ← <type>/<id>-archive: /opsx:archive, post-archive (roadmap, doc-writer — docs/
                       does not contradict the merged specs; glossary — or "no doc impact", `## Purpose`
                       of the touched specs, fixed by the session that archives<!-- sdd:if graphify -->, graph refresh<!-- sdd:endif -->),
                       commit chore(<id>), merged like PR 1; then the final report to the owner
<!-- sdd:endif -->
<!-- sdd:if !github -->
8. /opsx:archive     ← deltas merged into openspec/specs/
9. post-archive      ← roadmap, doc-writer (docs/ does not contradict the merged specs;
                       glossary) or "no doc impact", `## Purpose` of the touched specs
                       (fixed by the session that archives)<!-- sdd:if graphify -->, graph refresh<!-- sdd:endif -->;
                       commit chore(<id>)
10. push + merge     ← a human (the agent never pushes)
<!-- sdd:endif -->
```

The reference cycle is in [`CLAUDE.md` §3](CLAUDE.md)<!-- sdd:if github -->; the specs only receive behaviour verified in
production: `/opsx:archive` happens in a second pull request, after the post-deploy verification of
the first ([`docs/OPENSPEC_GUIDE.md`](docs/OPENSPEC_GUIDE.md) §8)<!-- sdd:endif --><!-- sdd:if !github -->; `/opsx:archive` only happens **after**
the implementation commit, and the merge only after the archive<!-- sdd:endif -->.

At each step, the context is handed over through the previous agent's result (short summary + file paths).

---

## 4. Typical workflow for a bug

```
1. <module>-dev   ← reproduce locally + identify the root cause
2. tester         ← write a failing test
3. <module>-dev   ← fix; make the test pass
4. code-reviewer  ← minimal review (focus on the regression)
```

Bug that contradicts a spec → OpenSpec change `fix-<bug>`. Trivial hotfix (< 30 min, specified behaviour intact) → branch `fix/<scope>-<desc>` without a change.

---

## 5. Conventions shared by all agents

Each agent implicitly inherits `CLAUDE.md` and the `CODING_RULES.md` of the module it works in. In addition:

- **No agent** invents a root module or package.
- **No agent** commits a secret.
- **Git**: agents work on a branch following [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) §2; **no agent** commits or pushes on
  `{{DEFAULT_BRANCH}}`, force-pushes or rewrites history. The hook
  [`.claude/hooks/block-git-writes.sh`](.claude/hooks/block-git-writes.sh) enforces it, sub-agents
  included. A sub-agent dispatched for a slice only commits if its brief asks it to;
  otherwise the main agent commits after the review.
- Every agent that modifies code ends by running the module's checks, **the same as CI**:
<!-- sdd:each module -->
  - `{{MODULE_PATH}}`: `{{MODULE_CHECK}}`
<!-- sdd:endeach -->
- Every agent that changes an external contract makes it born in the spec deltas, then `doc-writer` documents it at post-archive.
<!-- sdd:if graphify -->
- Every agent that reads code queries the graph first (`graphify explain|affected|path|query`), after `graphify check-update .`.
<!-- sdd:endif -->

---

## 6. How to add a new role

1. Create `.claude/agents/<name>.md` with the following frontmatter:
   ```yaml
   ---
   name: <name>
   description: USE WHEN <concrete triggers>. DO NOT USE <counter-indications>.
   tools: [Read, Edit, Write, Bash, Grep, Glob]   # or a subset
   model: {{AGENT_MODEL}}
   ---
   ```
   An agent that must run read commands (graphify, git diff, tests) needs `Bash`.
2. Describe the **mission**, the **mandatory reading**, the **hard rules**, the **workflow**, the **expected deliverables** and the **anti-patterns**.
3. Update the table in section 2 above and [`.claude/agents/README.md`](.claude/agents/README.md).
4. Test it by invoking it on a small task.

The `description` is what the main Claude reads to route: concrete triggers ("USE WHEN…") and counter-indications ("DO NOT USE…") work better than a general sentence.

---

## 7. Invocation

In Claude Code:
```
/agents                              # lists the available agents
```

Or let the main Claude **delegate automatically**: it reads each agent's description and picks the right one according to the routing table in [`CLAUDE.md` §8](CLAUDE.md).
