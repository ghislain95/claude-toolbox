# Desktop mods

Claude Code mods (function-hook plugins) for the desktop app: a session band, the background tasks, Claude's
messages as cards, and an OpenSpec cockpit. They are plugins of the `claude-toolbox` catalog, category `mod`.
They lived in the `ghislain95/claude-mods` repository until they were folded in here, history included.

| Mod | What it does |
|---|---|
| [`session-hud`](session-hud/README.md) | Every project: the band above the prompt (context, cost or rate limit, time, tools, model, background count) and an optional animated backdrop for the window (`/fond`, off by default) |
| [`background-tasks`](background-tasks/README.md) | Every project: the « En arrière-plan » pane (`/arriere-plan`): services with their port, workflow runs with phases and agents |
| [`conversation-cards`](conversation-cards/README.md) | Every project: Claude's messages as cards (questions, reports, QA, cockpit block, commits), compact tool rows, the context in the spinner, the display contract (`/cartes`) |
| [`openspec-cockpit`](openspec-cockpit/README.md) | OpenSpec projects only: the dashboard pane (ring, cycle timeline, next action, groups, decisions, ritual, handoff), gate alerts, status line |

All four share one look, **Galet**: soft pastel surfaces with round corners and no visible rim, one tone per kind
of card (ochre for questions and asks, honey for choices and decisions, sage for QA and commits, rose for findings,
stone for the rest), flat drawings with no gradient, glass, shadow or sweeping light, no emoji. It follows the app's
light or dark theme: the few native colours that differ between the two (tiles and chips, white on light) are read
from the session's `theme` setting. Its tokens and SVG drawings live in `shared/sienne.ts` (the file keeps the name
of the earlier Terre de Sienne look), the mode reader in `shared/mode.ts`; `scripts/sync-shared.sh` copies `shared/`
into each mod.

## Install from GitHub

```bash
claude plugin marketplace add ghislain95/claude-toolbox
for mod in session-hud background-tasks conversation-cards openspec-cockpit; do
  claude plugin install "$mod@claude-toolbox"
done
```

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

Requires Claude Code 2.1.326 or newer (the desktop app's engine): the optional backdrop is set through `$.theme.set`
with a `scene`, which older builds name otherwise. Validate and test with a CLI at least as recent as that engine: an older one reports errors the engine no
longer raises.

## Developing

Edit the files in `shared/`, never their copies under `<mod>/hooks/shared/`. To try the mods in a session that
hot-reloads its own mods folder:

```bash
mods/scripts/dev-sync.sh <session-id>
```
