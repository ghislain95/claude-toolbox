# claude-toolbox

One catalog for every Claude Code tool of this toolbox: the spec-driven workflow, standalone skills
and desktop-app mods. Add it once, install what you need. What each skill does and when it fires,
auto or proposed by the agent: [`CATALOG.md`](CATALOG.md) — or ask your agent, with the prompt at its
top, which plugins would help in your project.

```bash
claude plugin marketplace add ghislain95/claude-toolbox
```

| Plugin | Category | What it is |
|---|---|---|
| `sdd-core` | workflow | The spec-driven development workflow (below) |
| `sdd-ui` | skill | Optional UI review and polish skills |
| `handoff` | skill | `/handoff:handoff`, a handoff document to resume in a fresh session |
| `grilling` | skill | `grilling` and `/grilling:grill-me`: the agent interviews you on a plan's decisions before anything is built |
| `local-qa` | skill | `/local-qa:qa-prepare`, a local QA environment for a change that disturbs no other project, and the QA brief |
| `openspec-cockpit`, `conversation-cards`, `session-hud`, `background-tasks` | mod | Desktop app only, see [`mods/README.md`](mods/README.md) |

> **Coming from `sdd-kit`?** The catalog was renamed. A marketplace keeps the name it was added
> under, so replace it once: `claude plugin marketplace remove sdd-kit` (this uninstalls its plugins
> and deletes their saved data), then add `ghislain95/claude-toolbox` and reinstall. Projects set up
> with the former kit keep working: their `sdd-kit: installed` marker is still recognised.
>
> **Updating `sdd-core` in place** (auto-update included): an update does not install a dependency
> added since, and without it `sdd-core` refuses to load. To 0.3.0: run
> `claude plugin install handoff@<catalog name>` once; to 0.4.0: run
> `claude plugin install local-qa@<catalog name>` once (both when coming from 0.2.0); to 0.5.0: run
> `claude plugin install grilling@<catalog name>` once.

## The spec-driven workflow (`sdd-core`)

A **spec-driven** development workflow for Claude Code that you can install in any project, whatever
the language: the OpenSpec cycle, specialised sub-agents, mandatory review, mechanical git
guardrails and CI.

A project's rules can't be copied from another project. So `/sdd-core:sdd-init` starts by
**reverse-documenting the actual code** (modules, stack, CI commands, observed architecture,
vocabulary), and only generates rules and agents from what it has proven.

```
/opsx:new (grilling) → adversarial pass → /opsx:ff → /opsx:apply → review-harness → /opsx:verify
         → commit → /opsx:archive → post-archive → PR → merge (the agent when merge-conditions reports
           no open gate, checked by the hook on GitHub; the owner otherwise)
```

## Set up a project with a single prompt

1. Open Claude Code **at the root of the project** (CLI, desktop app or IDE extension).
2. Copy the prompt below and paste it as is.
3. Claude installs the tools and plugins, reverse-documents the code, generates the rules, the
   agents, the git guardrail and the CI, then commits everything on a `chore/sdd-init` branch. It
   only stops you at three points: before installing a tool on your machine, to validate what it
   understood of the code, and for one round of choices (language, options, merge method).
4. When it is done, restart Claude Code: the agents, the hook and the `/opsx:*` commands are loaded.

Allow 30 to 90 minutes depending on the size of the project. The same prompt, run again on a project
that is already set up, updates it to the latest version of the kit while keeping your changes.

```text
Install the spec-driven development workflow from claude-toolbox in this project (https://github.com/ghislain95/claude-toolbox): spec-driven development with OpenSpec, specialised agents, mandatory review, git guardrail and CI. Go through the steps in order, without skipping any.

1. Prerequisites — check with Bash: `node -v` (≥ 20), `openspec --version`, `jq --version`, `perl -v`, `gh auth status`, `git status`. For each missing tool, give me the install command (npm install -g @fission-ai/openspec@latest, brew install jq, brew install gh…) and wait for my go-ahead before installing anything on my machine. Without jq, the git guardrail would block every one of your git commands: this one is blocking.

2. Claude Code plugins — first run `claude plugin marketplace list`. If it shows a marketplace named `sdd-kit` (the former name of this catalog), remove it before anything else: `claude plugin marketplace remove sdd-kit` (it uninstalls its plugins and deletes their saved data; tell me before running it). Then run through Bash:
   claude plugin marketplace add anthropics/claude-plugins-official
   claude plugin marketplace add ghislain95/claude-toolbox
   claude plugin install sdd-core@claude-toolbox
   The first line is needed even if it seems redundant (it is a no-op when the official marketplace is already there): sdd-core depends on superpowers from that marketplace and won't load without it. The install should report "+ 4 dependencies: superpowers, handoff, grilling, local-qa"; check with claude plugin list that sdd-core, superpowers, handoff, grilling and local-qa are enabled.
   If sdd-core is already installed, update instead: claude plugin marketplace update claude-toolbox, then claude plugin update sdd-core@claude-toolbox, then claude plugin install handoff@claude-toolbox, claude plugin install grilling@claude-toolbox and claude plugin install local-qa@claude-toolbox (an update does not install a dependency added since; without them, sdd-core refuses to load).
   If the project has a web interface, also offer me: claude plugin install sdd-ui@claude-toolbox and claude plugin install frontend-design@claude-plugins-official.
   Ask me whether I use the Claude desktop app. If yes, offer the optional desktop mods (OpenSpec cockpit pane, message cards, session band, background-tasks pane): claude plugin install openspec-cockpit@claude-toolbox, conversation-cards@claude-toolbox, session-hud@claude-toolbox, background-tasks@claude-toolbox (one command each). If I take them, tick the `cockpit` option in phase 2 of the setup.

3. OpenSpec profile — run `openspec config list`. The workflow needs these workflows: propose, explore, new, continue, apply, ff, sync, archive, bulk-archive, verify, onboard. If any are missing, ask me to run `openspec config profile` in my terminal (it is interactive), pick the custom profile, tick them all, then carry on.

4. Project setup — newly installed plugins only load in the next session, so don't look for /sdd-core:sdd-init now. Read ~/.claude/plugins/marketplaces/claude-toolbox/plugins/sdd-core/skills/sdd-init/SKILL.md directly and follow it to the letter, with ~/.claude/plugins/marketplaces/claude-toolbox/plugins/sdd-core/skills/sdd-init/ as the base directory (templates/, references/). If the last line of CLAUDE.md (or of .claude/CLAUDE.md) contains "claude-toolbox: installed" (or "sdd-kit: installed", from before the rename), the project is already set up: follow the skill's --refresh mode. Respect its stopping points: the validation gate after the reverse-documentation (for a project with its own agent setup, the mapping table, before any write), and the round of questions in phase 2. Only ask me for choices; anything the code, the CI or git can tell you, look it up yourself. Never work on the main branch.

5. Wrap-up — give me the final report the skill describes, then tell me to restart Claude Code to load the agents, the hook and the /opsx:* commands. Remind me to turn on auto-update for this marketplace (/plugin → Marketplaces → claude-toolbox → Enable auto-update): it is off by default for third-party marketplaces, so without it I won't get new versions of the kit. My first step after that will be /opsx:onboard (a first guided cycle) or the first baseline-<domain> change you proposed.

Full guide if needed: ~/.claude/plugins/marketplaces/claude-toolbox/GUIDE.md
```

What the prompt changes on your machine, outside the project: it adds the `claude-toolbox` marketplace and
enables the `sdd-core`, `superpowers`, `handoff`, `grilling` and `local-qa` plugins (plus `sdd-ui`, `frontend-design` and the desktop
mods if you accept them) in `~/.claude/settings.json`, so for all your projects. `sdd-core` holds
skills and one session-start hook: it only speaks in a project set up with an older kit (see
[Staying up to date](#staying-up-to-date)), takes a few milliseconds and stays silent everywhere
else. `superpowers` adds a session-start hook that loads its guide to using skills; the desktop mods
change the desktop app's display. To remove the kit:
`claude plugin uninstall sdd-core@claude-toolbox`, then `claude plugin marketplace remove claude-toolbox`.
Context cost: the skill descriptions of `sdd-core` and its dependencies from this catalog add
about a thousand tokens to every session (`claude plugin details <plugin>@claude-toolbox` shows the
breakdown per plugin).

## Contents

| Plugin | Contents |
|---|---|
| **`sdd-core`** | `/sdd-core:sdd-init` (reverse-documentation + workflow install, `--refresh` to update), `/sdd-core:review-harness` (full review of a change, with its eight `review-*` angles), `/sdd-core:retro`, `sdd-core:domain-modeling`, `sdd-core:codebase-design`, `/sdd-core:improve-codebase-architecture`, and the templates (agents, `CLAUDE.md`, OpenSpec rules, git hook, CI). Depends on `superpowers`, `handoff`, `grilling` and `local-qa` |
| **`handoff`** | `/handoff:handoff` — handoff document to resume in a fresh session; usable in any project, installed with `sdd-core` |
| **`grilling`** | `grilling` (auto) and `/grilling:grill-me` — interview in rounds over a plan's decisions, each with its recommended answer, before building; usable in any project, installed with `sdd-core` |
| **`local-qa`** | `/local-qa:qa-prepare` — local QA environment for a change on a machine shared with other projects and agents (inventory, reuse of compatible services, the rest on free ports, isolated database when the change migrates), the owner's QA brief, and `--cleanup` of exactly what it started; usable in any project, installed with `sdd-core` |
| **`sdd-ui`** (optional) | `web-design-guidelines`, `break-ui`, `emil-design-eng`, `animate`, `review-animations`, `improve-animations` |
| **Desktop mods** (optional, desktop app only) | `openspec-cockpit`, `conversation-cards`, `session-hud`, `background-tasks` — in [`mods/`](mods/README.md) |

What `sdd-init` installs in the project: see [`GUIDE.md`](GUIDE.md) §3.

## Manual install (without the prompt)

In Claude Code:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin marketplace add ghislain95/claude-toolbox
/plugin install sdd-core@claude-toolbox
```

`superpowers`, `handoff`, `grilling` and `local-qa` come with it as declared dependencies, provided the official marketplace
is added (first line; harmless if it already is).

Then, in the project to set up:

```
/sdd-core:sdd-init
```

The full guide (prerequisites, what happens, day-to-day use, pitfalls) is in [`GUIDE.md`](GUIDE.md).

## Staying up to date

There are two levels, and both matter:

1. **The plugin on your machine.** Auto-update is **off by default** for third-party marketplaces
   like this one. Turn it on once: `/plugin` → **Marketplaces** → `claude-toolbox` → **Enable
   auto-update**. Claude Code then checks in the background during a session and tells you when a
   new version is ready (`/reload-plugins` or a restart applies it). Without auto-update:
   `claude plugin marketplace update claude-toolbox && claude plugin update sdd-core@claude-toolbox`.
2. **Each project you set up.** The files `sdd-init` generated (CLAUDE.md, agents, hook, CI…) are
   copies: a new kit version doesn't change them. In each project, run the install prompt again (or
   `/sdd-core:sdd-init --refresh`): it applies what comes from the kit and keeps your local edits.
   You don't have to remember it: when you open a session in a project set up with an older kit,
   `sdd-core` shows a one-line notice (and Claude mentions it in its first reply).

What changed in each version: [`CHANGELOG.md`](CHANGELOG.md). Publishing a version (maintainers):
[`MAINTAINING.md`](MAINTAINING.md).

## Credits

Vendored skills keep their upstream `LICENSE` and a `SOURCE.md` (upstream repository, commit,
changes): `mattpocock/skills`, `emilkowalski/skills`, `vercel-labs/agent-skills`. The git guardrail
hook is adapted from `mattpocock/skills` (`git-guardrails-claude-code`, MIT).
