# Claude Code agents — {{PROJECT_NAME}}

Each `*.md` file in this folder defines a specialised **subagent**. The main Claude picks them on
its own from their `description` ("USE WHEN / DO NOT USE"); you can also list them with `/agents`.
Workflow and conventions: [`/AGENTS.md`](../../AGENTS.md).

## Routing table

**Before writing or coding, identify the right agent and delegate.** Act yourself only when no
agent fits or the task is trivial (quick read, factual question).

| The user asks… | Agent |
|---|---|
| "I want feature X", "we should be able to Y", fuzzy business need, prioritisation, user story, proposal | `grilling` in the main session (a sub-agent cannot interview), then `product-owner` with the settled decisions |
| "how should we do X", cross-cutting choice<!-- sdd:if multi-module -->, impact on > 1 module<!-- sdd:endif -->, new external contract, spec deltas, design.md, ADR, adversarial pass | `architect` |
<!-- sdd:each module -->
| implementation in `{{MODULE_PATH}}` ({{MODULE_STACK}}) | `{{MODULE_NAME}}-dev` |
<!-- sdd:endeach -->
<!-- sdd:if multi-module -->
| small coherent feature spanning several modules | `full-stack-dev` |
<!-- sdd:endif -->
| "review this diff", "validate my PR", "look at what I did"; after a hotfix outside a change | `code-reviewer` |
| full review of an implemented OpenSpec change | `/sdd-core:review-harness <id>` (runs `code-reviewer` as one angle) |
| write / complete tests, regression test | `tester` |
| update docs, README, glossary, `docs/`; post-archive | `doc-writer` |
<!-- sdd:if devops -->
| infra, containers, CI, secrets, production configs | `devops` |
<!-- sdd:endif -->

### Routing rules
- Several agents fit → the one that **maximises specialisation**<!-- sdd:if multi-module --> (the module's agent rather than `full-stack-dev` when the task touches a single module)<!-- sdd:endif -->.
- Ambiguous request → **at most 1 question** to the user, then route.
- Large feature → OpenSpec cycle: `grilling` (main session) → `product-owner` (proposal) → `architect` adversarial pass
  → `architect` (deltas + design + tasks) → dev agents (tasks) → `tester` → `/sdd-core:review-harness`
  (which runs `code-reviewer` as its conventions angle) →
  `/opsx:verify` → commit → `/opsx:archive` → post-archive (`doc-writer` if docs are impacted).
- Bug → the module's dev agent (reproduce, root cause), `tester` (failing test), fix,
  `code-reviewer`.
- Always announce the chosen agent before delegating: "Routing → `<agent>` because <reason>".

### When not to delegate
- Factual question ("where is X defined?") → answer directly.
- File read explicitly requested → do it.
- Task < 5 min, single-shot, risk-free → do it, and say it could have been delegated.

## Model and tools
- **Every agent runs on `model: {{AGENT_MODEL}}`**, written explicitly in each file rather than
  inherited: a session started on a cheaper model does not silently degrade an agent.
- Tools are those of each agent's frontmatter (source of truth). `architect` and
  `product-owner` have `Write`/`Edit`, restricted by instruction to their deliverables
  (`openspec/changes/<id>/`, `docs/adr/`; `proposal.md`); their `Bash` is for reading.
- `code-reviewer` has no `Edit`: it reports, it does not fix.
- Every agent has `Skill`: its definition names the skills it invokes and when. Without `Skill` in
  `tools`, an agent cannot invoke a skill at all, whatever its text says. User-invoked skills
  (`disable-model-invocation`) stay the user's: an agent proposes them, it never runs them.

## Adding an agent
1. Create `<name>.md`:
   ```yaml
   ---
   name: <name>
   description: USE WHEN <concrete triggers>. DO NOT USE <neighbouring cases → other agent>.
   tools: [Read, Edit, Write, Bash, Grep, Glob, Skill]
   model: {{AGENT_MODEL}}
   ---
   ```
2. Describe mission, mandatory reading, hard rules, workflow, the skills it invokes and when,
   anti-patterns, deliverable.
3. Update the routing table above, [`/AGENTS.md`](../../AGENTS.md) and `CLAUDE.md`.
4. Test it by invoking it on a small task.
