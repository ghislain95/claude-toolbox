---
name: qa-prepare
description: Prepares a local QA environment for a change on a machine shared with other projects and agents (inventory of what runs, reuse of what is compatible, the rest started on free ports and recorded), then hands the owner a QA brief (link, 3 to 6 gestures with expected results, before/after captures). `--cleanup` stops exactly what it started. Run it before handing an intent QA to the owner.
argument-hint: "[<change-id> | --cleanup]"
---

# qa-prepare — a local QA environment that disturbs no one

The owner's QA of a change runs on this machine, before merge. Other projects and other agents run here
too: their containers, dev servers and databases hold ports and data you do not own. You prepare an
environment where the change can be tried, without stopping, restarting or reconfiguring any of them,
then you hand the owner a short brief.

This folder (the base directory given when the skill is invoked) holds `scripts/qa_env.py`, the
deterministic half: inventory, the reuse-or-start plan, free ports, the record of what you started, and
the cleanup. Call it, read its JSON, and keep the judgement for yourself. Below, `QA` stands for
`python3 <base directory>/scripts/qa_env.py --root <worktree>`, `<worktree>` being the root of the
checkout holding the change.

`$ARGUMENTS` is `--cleanup` → go to §6. Otherwise it may name the change (OpenSpec change id, branch or
pull request); without it, the change is the current branch.

## Rules (hold them from start to finish)

1. **Only ever stop what you provably started.** No `docker stop|restart|rm|kill`, `docker compose
   down|up|restart` on a compose project that is not this QA's (`qa-<project>[-<worktree>]-<hash>`, given
   by the script), no `kill` of a PID, no edit of another worktree's files, no change to a shared
   service's configuration, users, schema or volumes. The only stop is `QA cleanup`, which stops what
   `QA record` accepted. A port you want is taken → another port, never the eviction of its holder.
2. **Never migrate a shared database**, and never reuse one whose applied migrations you cannot compare
   with the worktree's: the script reuses a database only when its history equals the worktree's
   migrations; otherwise this QA gets its own.
3. **Start processes through `QA launch`, record what you start right after it answers** (`QA record
   …`). What is not recorded is never stopped by the cleanup, and what is recorded is the only thing it
   stops.
4. **The change's own code always runs from this worktree.** A backend or frontend that runs from another
   worktree or the main checkout runs other code: it is never reused for this QA, whatever its port.

## 1. Pre-flight

- `git -C <worktree> status --short` and `git -C <worktree> log --oneline -3`: the change is committed or
  at least present in this worktree.
- `git -C <worktree> check-ignore -q .claude/qa/started.json` must succeed. If it fails, add `.claude/qa/`
  to the file `git -C <worktree> rev-parse --git-path info/exclude` names (local, nothing committed) and
  say so in the brief.
- `docker info` and `lsof -v` answer? The script reports `"docker": "unavailable"` or `"lsof":
  "unavailable"` instead of failing: without lsof, it cannot see who holds a port, so it relies on its
  bind test alone and you say so in the brief.

## 2. The services spec

Write `<worktree>/.claude/qa/services.json` (gitignored with the rest of `.claude/qa/`) — or use the
project's committed `.claude/local-qa.json` when it has one. Derive it from the project, never guess a
port: `.claude/launch.json` (dev servers and their ports), the compose files the worktree uses for
development, the dev-server scripts (`package.json`, `application*.yml`, `Makefile`), the README.

```json
{
  "services": [
    {"name": "db", "kind": "container", "compose_service": "postgres", "port": 5432, "container_port": 5432, "shared": true, "database": true},
    {"name": "cache", "kind": "container", "compose_service": "redis", "port": 6379, "shared": true},
    {"name": "backend", "kind": "process", "port": 8080},
    {"name": "frontend", "kind": "process", "port": 5173}
  ],
  "migrations": ["backend/src/main/resources/db/migration/**"]
}
```

- `port`: the default host port; `container_port`: the port inside the container (defaults to `port`).
- `shared: true` only for infrastructure the project's worktrees share during development (database,
  cache, object store, message broker, tile server): a running instance **of the same project** may be
  reused. Never for a service that runs the code being changed.
- `database: true`: the service holds a schema the change's migrations would alter. It needs the spec's
  `migrations`, and, to ever be reused, `applied_migrations`: a **read-only** shell command printing the
  migrations the running database has applied, one per line, run from the worktree with `QA_DB_HOST`
  and `QA_DB_PORT` set to the candidate's address, e.g. for Flyway on PostgreSQL
  `psql -h "$QA_DB_HOST" -p "$QA_DB_PORT" -U app -d app -tAc "select version from
  flyway_schema_history where success"` (credentials from the project's dev settings, never typed into
  the spec when they are secrets: an environment variable the project already defines). Without it, or
  when it fails, the database is never reused.
- `migrations`: globs of the project's migration files (with the spec-driven workflow: the migration
  paths of `.sdd/triggers.yaml`; otherwise the migration tool's folder). `**` crosses directories.
  `migration_id` (optional): a regex whose group 1, applied to each file name, gives the identifier
  `applied_migrations` prints — `^V([0-9_.]+)__` for Flyway's versions (default: the file name
  without its extension). The worktree's set and the database's set must be equal: one missing on
  either side → a database of this QA's own.

## 3. Inventory and plan

```bash
QA plan --spec <worktree>/.claude/qa/services.json --base origin/<default branch>
```

(`QA inventory` alone shows everything that runs: every container with its compose project, every
listening port with its process and working directory, each mapped to its project and worktree.)

`--base` is required when the spec has `migrations`. `plan` also **opens the QA**: it writes the
QA's start time into `.claude/qa/started.json` (a process started before it is never accepted) and
reserves each port it chooses with a machine-wide lock file (`$QA_PORT_LOCKS`, default
`/tmp/qa-ports-<uid>`), so another agent preparing at the same time takes another port; the cleanup
releases them, and a lock whose worktree no longer exists is reclaimed. Running `plan` again keeps the
start time and the ports already reserved.

For each service the plan says `reuse` (with the port, and whether this QA started it) or `start`
(with the reserved port, the compose project for a container, `default_port_taken_by` when the default
port is held — by whom, from which project and worktree — and, for a database, `isolated` with the
`reason`: the history differs, cannot be read, or `--pending-migration` declared a migration the
globs cannot see). `migrations` lists the change's own migration files against `--base`.

The script applies the mechanical rule: same project, not another worktree's QA, code services only
from this worktree, a database only with an equal history, whatever the service's kind. **You judge
the rest** before reusing; any doubt → start your own instead (it costs a container, never another
agent's afternoon):

- **Version** — the running container's image (`QA inventory` gives it) matches what the worktree's
  compose file asks for. The change bumps an image → start your own.
- **Configuration** — the change needs something the shared service lacks (a new bucket, queue,
  extension, user, environment variable, seed): creating it in the shared service is reconfiguring it
  → start your own.
- **Data shape** — the QA gestures will write data in a format the change introduces (a new stored
  format, a new cache key layout): other worktrees would read it → start your own.
- **Data needed** — the QA needs data a fresh instance does not have: fill your own instance (the
  project's seed or fixtures, or a dump **read** from the shared instance and restored into yours —
  `pg_dump` reads, it changes nothing), never the other way round.

## 4. Start what is missing

**Containers** — under the compose project the plan gives, from the worktree's own compose file, only
the services to start:

```bash
docker compose -p <compose_project> -f <worktree>/<compose file> up -d <compose service>
```

The port: if the compose file maps it through a variable (`"${DB_PORT:-5432}:5432"`), set the
variable; otherwise write `<worktree>/.claude/qa/compose.override.yml` and add it with a second `-f`:

```yaml
services:
  <compose service>:
    ports: !override
      - "<port>:<container_port>"
```

(`!override` needs Docker Compose 2.24.4 or later; without it the file's own port is still published
and clashes.) An isolated database: once it answers, fill it (§3, "Data needed"), then apply the
change's migrations to it, and only to it. Then:

```bash
QA record container --name <name> --service <compose service>
```

`record container` accepts a container only with both compose labels of this QA: its compose project
and a compose working directory inside this worktree (a container without compose labels is never
accepted, whatever its name). A container the plan reports `reuse` with `"started_by_this_qa": true,
"recorded": false` (left by an earlier preparation of this worktree) is recorded the same way.

**Processes** (backend, frontend) — start each one from its directory in the worktree, in the
background (Bash tool with `run_in_background`), **through `QA launch`**:

```bash
cd <worktree>/<module> && QA launch --name <name> -- <the dev-server command>
```

`launch` writes its own PID into `started.json` as a launcher of this QA, then becomes the command (same
PID). Use the plan's port, wired to the chosen ports of the other services through command-line flags
or environment variables (`--port`, `PORT=`, `SERVER_PORT=`, the database URL, the API URL the
frontend calls, the allowed CORS origin when the frontend's port moved). Never edit a tracked
configuration file for it: when a file is the only way, a gitignored local override the project already
supports (`.env.local`, a local profile). Once it answers (health endpoint, first page):

```bash
QA record process --name <name> --port <port>
```

`record process` accepts the process listening on that port only when all of these hold: it runs from
this very worktree (from the main checkout, a nested `.claude/worktrees/<x>` is another worktree); it
started after `plan` opened this QA; it descends from a `launch` of this QA (or from the shell running
`record`); it is not Claude Code, a desktop app or an IDE helper. A refusal means you were about to take
ownership of something that is not yours: the agent sessions and the owner's own dev servers listen
with their working directory in the project too.

## 5. Your own QA, then the brief

Try every point yourself first, with the browser or preview tools, and capture each one:
`<worktree>/.claude/qa/captures/<n>-before.png` and `<n>-after.png`. **Before** is the behaviour
without the change: production, or the main checkout's environment when it already runs — never by
switching branches or stashing in a shared checkout. When no before can be had (a new screen), say
so. A point that fails on your side is fixed before the owner sees anything.

Then hand the owner the brief, in the project's language, in this shape — the one the
`conversation-cards` desktop mod draws as a QA card (a `## QA` section, a preparation part, then one
checklist line per point with a bold title, the gesture and the expected result):

```markdown
## QA

**Préparation**
- Open http://localhost:<port>/<path>
- Running for this QA: backend :8081 and frontend :5174 (this worktree), database
  `qa-shop-<worktree>-<hash>` on :5434 (the change adds migration V42; port 5432 is held by another project's database, left
  alone); reused: the project's Redis on :6379.

**Vérifications**
- [ ] **<short title>** — Fais : <the gesture, concrete: where to click, what to type>. · Attendu : <what
  must be seen, checkable at a glance>. Captures : `.claude/qa/captures/1-before.png`, `1-after.png`.
```

- **3 to 6 points**, chosen from the change's visible effect (its spec scenarios and the intent the
  classification gave), each one gesture and one expected result. Fewer than 3 → the change probably
  did not need an intent QA; more than 6 → group or drop the minor ones.
- The card splits the line on the French markers `Fais :` and `Attendu :`. In English, write
  `Do: … · Expected: …`: the card then shows the line whole.
- End with what you need: an answer per point (OK, or what they saw instead).

Failed points → fix in the change, keep the environment running, re-brief only those points.

## 6. Cleanup (`--cleanup`)

When the owner reports the QA as passed, gives up on it, or the change leaves the QA stage (merged,
closed, sent back to framing):

```bash
QA cleanup --dry-run     # what would stop: only started.json's entries
QA cleanup
```

It stops each recorded process after checking it is still the process you started (same command,
same start time): SIGTERM to it, or to its process group when it leads one, then SIGKILL after a grace
period, and it reports `stopped` only once nothing of the group is left. It stops each recorded
container after checking again its full id and its compose labels. Then it removes this QA's compose
volumes and networks once its containers are gone, and releases the ports this QA reserved. An entry it
does not stop — `skipped` (the PID now runs another process, the container is no longer labelled for
this QA) or `failed` — stays in `started.json` and the command exits 1: report it, never stop anything
else in its place. Background tasks you started with the Bash tool can be stopped with their own tool
first; the cleanup then reports them `gone`. Report what stopped and what kept running (the reused
services, untouched).
