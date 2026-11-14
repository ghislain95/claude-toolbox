# Reverse-documentation — checklist

Goal: describe the project **as it is**, with evidence for every claim, precisely enough for the
rules and agents generated afterwards to be right. No value judgements, no "should": what would be
desirable goes into the backlog, not into the reverse-documentation.

## 1. Detect the modules and commands

Look for dependency and build files, at any depth (excluding `node_modules`, `vendor`, `target`,
`dist`, `build`, `.venv`):

| Ecosystem | Files | Commands (to read, not to guess) |
|---|---|---|
| JS / TS | `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json` | `scripts` (`test`, `lint`, `type-check`, `build`); package manager = the lockfile present |
| Python | `pyproject.toml`, `setup.cfg`, `requirements*.txt`, `tox.ini`, `noxfile.py` | `[tool.pytest]`, `[tool.ruff]`, `[tool.mypy]`, `uv`/`poetry`/`hatch` scripts |
| JVM | `pom.xml`, `build.gradle(.kts)`, `settings.gradle` | `./mvnw test`, `./gradlew check`; JDK version (`maven.compiler.release`, toolchain) |
| Go | `go.mod`, `go.work` | `go test ./...`, `go vet`, `golangci-lint` if configured |
| Rust | `Cargo.toml` (workspace) | `cargo test`, `cargo clippy`, `cargo fmt --check` |
| .NET | `*.sln`, `*.csproj` | `dotnet test`, `dotnet format --verify-no-changes` |
| Ruby | `Gemfile`, `Rakefile` | `bundle exec rspec`, `rubocop` |
| PHP | `composer.json` | `scripts`, `phpunit`, `phpstan` |
| Others | `Makefile`, `justfile`, `Taskfile.yml`, `docker-compose*.yml`, `Dockerfile` | declared targets |

**Source of truth for commands, in order**: CI (`.github/workflows`, `.gitlab-ci.yml`,
`Jenkinsfile`, `azure-pipelines.yml`…) > the project's scripts > the README. If CI and the scripts
diverge, note the gap (it goes into the report) and keep what CI runs.

**Module** = a unit with its own dependency file, testable on its own. A JS monorepo with `apps/*`
and `packages/*`: one module per app, and the shared packages grouped together if small.

## 2. Split the recon

One `Explore` sub-agent per module (+ one cross-cutting), launched **in the same message**. Give each
one: the module path, the §3 sections to fill in, the instruction "every claim cites `file:line`;
whatever you can't prove, write it under *to confirm*", and "if `graphify-out/graph.json` exists,
query `graphify query/explain/path` before grepping".

## 3. What each report must contain

### Per module
1. **Identity**: the module's role in one sentence, entry point(s) (`main`, HTTP server, CLI,
   worker, serverless handler, front-end bundle).
2. **Stack**: language + version, framework(s) + pinned version, database(s), broker, ORM / client,
   migration tool (→ option `migrations`), test library.
3. **Structure**: tree of the first 2 levels of the code, with the role of each folder.
4. **Observed architecture**: layers and dependency direction (who imports whom — check by sampling
   imports, not by folder names), where the business logic lives, where the adapters live (HTTP, DB,
   queue, external), architecture rules **already enforced by tooling** (ArchUnit, import-linter,
   dependency-cruiser, eslint boundaries, Go internal packages…).
5. **Exposed contracts**: HTTP / GraphQL / gRPC routes, topics, events, CLI, database schema
   (migrations folder), with their definition file.
6. **Conventions**: naming, error handling, logging, config / secrets (environment variables,
   files), input validation, formatting and lint (configs present).
7. **Tests**: kinds (unit, integration, e2e, BDD), location, naming conventions, fixtures, what is
   mocked; command and **actual result** of the baseline.
8. **Domain vocabulary**: entities, aggregates, states, roles, statuses — as named in the code (they
   seed the glossary).
9. **Hot spots**: most-changed files (`git log --format= --name-only | sort | uniq -c | sort -rn |
   head -20`), largest files, notable TODO/FIXME.
10. **To confirm**: what seems true without evidence.

### Cross-cutting
- CI: jobs, triggers, path filters, what they run.
- Infra: Docker / compose, IaC, deployment scripts, environments.
- Deployment (feeds `.sdd/deployment.yaml`): what a push to the default branch deploys — workflows on
  `push` to it (their path filters, platform, the deploy command), hosting configuration
  (`vercel.json` and Vercel's root directory, `netlify.toml`, `fly.toml`, `app.yaml`, cloudbuild
  files), each with the file:line that proves it; how each target is rolled back to the previous
  deployment without a rebuild (a script, a runbook, a documented command — none found: say so, it
  becomes `unconfirmed`); health endpoints or smoke tests usable as probes; scheduled jobs that run
  the repository's code (`on: schedule`, cron, Cloud Scheduler, IaC) with their schedule and the code
  they run.
- Existing docs: README, `docs/`, ADRs, CONTRIBUTING — what they say **and** where they contradict
  the code.
- Git history: commit convention already in use (`git log --oneline -30`), branch naming, merge vs
  squash.
- Security: where secrets live, `.env` files committed by mistake (report them, never print the value).

## 4. Turning the recon into rules

| Found | Becomes |
|---|---|
| Rule respected everywhere and enforced by tooling (architecture test, lint) | Non-negotiable rule in `CLAUDE.md` §5, with the name of the check |
| Rule respected everywhere, not enforced | Non-negotiable rule + backlog line "enforce this rule with a check" |
| Rule respected with exceptions | The module's `CODING_RULES.md`, exceptions listed; not non-negotiable |
| Implicit convention, different from place to place | "to confirm" → question to the user at gate 1 |
| Visible structural choice (framework, database, auth, architecture) | Reverse-documented ADR |
| Debt, dead code, major TODO | `docs/ROADMAP.md` backlog |
| Domain risk (money, health, personal data, security, real time) | `{{DOMAIN_RISKS}}` + `proposal` rule in `openspec/config.yaml` |
