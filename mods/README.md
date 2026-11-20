# Desktop mods

Four mods for the Claude desktop app (Code tab): they change how Claude Code looks, and, for the cards, the shapes
Claude writes in so they can be drawn. Each one installs on its own; none needs another, and none needs the
`sdd-core` workflow.

| Mod | What you get | Where it shows |
|---|---|---|
| [`conversation-cards`](conversation-cards/README.md) | Claude's questions as cards with clickable options, its reports, checks to tick, commits to copy and « cockpit » action blocks as buttons; compact tool rows; the context in the spinner | The transcript, every project |
| [`session-hud`](session-hud/README.md) | One line above the prompt: context, cost or rate limit, session time, tool calls and errors, model, and how many tasks run in the background | Above the prompt, every project |
| [`background-tasks`](background-tasks/README.md) | A pane listing what runs in the background: dev servers with their port, workflow runs with their phases and agents, this session's agents | A side pane (`/arriere-plan`), every project |
| [`openspec-cockpit`](openspec-cockpit/README.md) | An OpenSpec dashboard: the change's progress, the cycle's step, the next action with its command, task groups, decisions, the last handoff; gate alerts and a status line | A side pane (`/cockpit`), only in projects with `openspec/` |

All four share one look, **Galet**: soft pastel surfaces, one tone per kind of card, no gradient, shadow or emoji,
in the app's light or dark theme.

## Before you install

- **The Claude desktop app**, Code tab, up to date (engine 2.1.326 or newer). In a terminal or an IDE the mods fall
  back to plain text or stay out of the way.
- **French interface.** The cards, panes and band speak French.
- **`openspec-cockpit` without the `sdd-core` workflow** works in any OpenSpec project: progress, cycle, next action,
  groups, handoff. Its « Décisions » section and its « review » gate read files the workflow writes
  (`verification/owner-points.md`, `.claude/handoff/` (or the older `.claude/passation/`), a `code-reviewer` agent); without them they stay empty.
- **`conversation-cards` adds a display contract to Claude's system prompt** (about 300 tokens): the shapes the
  cards read (questions as `### Q1 · …`, a closing « cockpit » block, commit messages in a `text` block). It also
  states this catalog's commit convention: subject `type(<change-id>): …` and no Co-Authored-By trailer. Turn it off
  with `/cartes contrat off` (the cards still draw what they recognise), or all the cards with `/cartes off`.
- **What the mods read**: the project's files (OpenSpec changes, handoffs, git), the session's own data, and, for
  `conversation-cards`, the one key of the desktop app's settings that says whether it is light or dark
  (`userThemeMode`). Nothing leaves your machine.

## Install

Add the catalog once (it is public):

```bash
claude plugin marketplace add ghislain95/claude-toolbox
```

Then install the mods you want, one command each:

```bash
claude plugin install conversation-cards@claude-toolbox
```

```bash
claude plugin install session-hud@claude-toolbox
```

```bash
claude plugin install background-tasks@claude-toolbox
```

```bash
claude plugin install openspec-cockpit@claude-toolbox
```

In Claude Code, `/plugin` does the same with menus. Open a new session (or run `/reload-plugins`) to load them.

**Turn on auto-update**, or you will not get new versions: it is off by default for a catalog like this one.
`/plugin` → **Marketplaces** → `claude-toolbox` → **Enable auto-update**. Without it:
`claude plugin marketplace update claude-toolbox`, then `claude plugin update <mod>@claude-toolbox`.

To remove one: `claude plugin uninstall <mod>@claude-toolbox`.

## Install from a local clone (to edit the mods)

```bash
claude plugin marketplace add <path to your claude-toolbox clone>
for mod in session-hud background-tasks conversation-cards openspec-cockpit; do
  claude plugin install "$mod@claude-toolbox" --scope user
done
```

A local clone is read in place: edit a mod here, then run `/reload-plugins` (or start a new session). Check and
test a mod before using it, from the clone's root:

```bash
claude plugin validate mods/openspec-cockpit
claude plugin test mods/openspec-cockpit
```

The mods need Claude Code 2.1.326 or newer (the desktop app's engine): the optional backdrop is set through
`$.theme.set` with a `scene`, which older builds name otherwise. Validate and test with a CLI at least as recent as
that engine: an older one reports errors the engine no longer raises.

## Developing

The look's tokens and SVG drawings live in `shared/sienne.ts` (the file keeps the name of the earlier Terre de
Sienne look); `shared/mode.ts` reads the app's light or dark mode (the desktop app's `userThemeMode`, else macOS's
appearance, else the session's `theme` setting), for the few native colours that differ between the two.
`scripts/sync-shared.sh` copies `shared/` into each mod.

Edit the files in `shared/`, never their copies under `<mod>/hooks/shared/`. To try the mods in a session that
hot-reloads its own mods folder:

```bash
mods/scripts/dev-sync.sh <session-id>
```
