# Maintaining the toolbox

How to publish a new version, and what users experience.

## Publishing a version

1. **Change** the skills, templates or docs on a branch (`feat/…`, `fix/…`, `docs/…`).
2. **Check**:
   ```bash
   claude plugin validate .
   claude plugin validate plugins/sdd-core
   claude plugin validate plugins/sdd-ui
   claude plugin validate plugins/handoff
   bash plugins/sdd-core/skills/sdd-init/templates/claude/hooks/block-git-writes.test.sh
   bash plugins/sdd-core/hooks/check-kit-version.test.sh
   uv run --with pyyaml python .sdd/bin/test_merge_conditions.py
   ```
   The same suites run in CI ([`tooling.yml`](.github/workflows/tooling.yml)), which also checks
   that `.sdd/bin/` is byte-identical to `plugins/sdd-core/skills/sdd-init/templates/sdd/bin/`
   (`cmp` of the two Python files there; `TemplateCopyTest` of the matcher's suite compares every
   file of the folder, `deploy-guard.sh` included, with its mode): change the template, then copy it.
   **`deploy-guard.sh`'s entry interface is frozen** (`<merged> <before> <trusted>`, `--vercel
   [globs]`, and `merge_conditions.py deploy-guard`'s options it uses): projects run the copy of their
   last deployed commit, older than the workflow step or `ignoreCommand` that calls it, so a changed
   interface refuses every deploy until the owner deploys by hand. Add, never rename or remove.
   For a template change, also dry-run `sdd-init` on a throwaway project (one module and several
   modules if the change concerns `multi-module`) and check that no `{{…}}` or `sdd:` marker is left.
3. **Bump `version`** in `plugins/<plugin>/.claude-plugin/plugin.json` of every plugin you changed
   (semver: a template or behaviour change is at least a minor bump). **Without a bump, users don't
   receive anything**: Claude Code keeps their cached copy until the version string changes. Keep the
   version in `plugin.json` only, not in the marketplace entry as well.
4. **Write the entry** in [`CHANGELOG.md`](CHANGELOG.md): what changed, and whether projects need
   `/sdd-core:sdd-init --refresh` to benefit from it (template changes do; a new skill doesn't).
5. **Pull request**, review, merge into `main`. The marketplace serves `main`.
6. Optional: `claude plugin tag` creates a `<plugin>--v<version>` git tag, needed only if another
   plugin wants to depend on a version range of this one.

## The desktop mods

The four desktop mods live under `mods/` (folded in from `ghislain95/claude-mods` with
`git subtree`). They are relative-path plugins like the others: bump the `version` in
`mods/<mod>/.claude-plugin/plugin.json` to ship a change, and check them with
`claude plugin validate mods/<mod>` and `claude plugin test mods/<mod>`.

The mods API moves with Claude Code, so check them with a `claude` at least as recent as the desktop
app's engine (`claude --version`; the desktop's own build is under
`~/Library/Application Support/Claude/claude-code/<version>/`). An older CLI reports errors the engine
no longer raises, such as "$ is passed to … imported from …" or `"ui.notify" is not an event`.

## Release triggers

`main` is production for everyone who installed from this catalog with auto-update on. The paths
listed in [`.sdd/triggers.yaml`](.sdd/triggers.yaml) under `irreversible` reach users' machines or
projects as soon as they are merged; a pull request touching one of them is merged by the owner, never
by an agent.

**How the toolbox's own merges are judged.** The toolbox runs the same check it ships:
[`merge-conditions.yml`](.github/workflows/merge-conditions.yml) runs from `main` on every pull
request (and again when `Tooling` completes, when the agent posts `review-harness` / `opsx-verify`,
and for every open pull request when `main` moves), reads `.sdd/triggers.yaml` and the change's
approved `classification.yaml` from `main`, requires
`Tooling` (no path filter, so always) to have succeeded on the head commit, and posts the
`merge-conditions` status with the open gates in its description. A change of this repository goes
through the same framing pull request as a project's (`docs/<id>-framing`, merged by the owner); a pull
request without an approved classification is `gates: unclassified` and merged by the owner. Changes
started before the check existed (`dev-factory`) have no classification and are judged unclassified.
The repository is public, so the ruleset on `main` can also require `merge-conditions` once it has run
once (it can only be required after GitHub has seen it); until the guardrail's verified merge route
ships, the owner merges every pull request anyway.

## Renaming the catalog (`sdd-kit` → `claude-toolbox`)

Rehearsed on a scratch `CLAUDE_CONFIG_DIR` on 2026-11-12, with the catalog added from a local clone:

- A marketplace keeps the name it was **added** under. After the `name` in `marketplace.json`
  changed, `claude plugin marketplace update sdd-kit` succeeded and the plugins stayed installed and
  enabled as `<plugin>@sdd-kit`.
- Adding the same source again is refused as already present (`Marketplace 'sdd-kit' already on
  disk`): the new name is only picked up by removing and re-adding.
- `claude plugin marketplace remove sdd-kit` uninstalls its plugins and deletes their saved options,
  secrets and data. Adding `claude-toolbox` then installing `sdd-core@claude-toolbox` works, with its
  dependencies.

- Updating `sdd-core` in place from 0.2.0 to 0.3.0 (`marketplace update` then `plugin update`)
  succeeds but leaves `sdd-core` failing to load: `Dependency "handoff@sdd-kit" is not installed`. An
  update never installs a dependency added since; `claude plugin install handoff@sdd-kit` fixes it.
  **Adding a dependency is a breaking change for in-place updates**: say so in the CHANGELOG with
  the install command.

So users of `sdd-kit` keep working until they choose to switch, once `handoff` is installed; the
README tells them how. Projects
set up with the former kit keep their `sdd-kit: installed` marker, which the version check still
reads.

## What users experience

- **Plugin, with auto-update on** (`/plugin` → Marketplaces → `claude-toolbox` → Enable auto-update): during
  a session, Claude Code refreshes the marketplace in the background, installs the new version and
  tells them; `/reload-plugins` or a restart applies it.
- **Plugin, with auto-update off** (the default for third-party marketplaces): nothing happens until
  they run `claude plugin marketplace update claude-toolbox && claude plugin update sdd-core@claude-toolbox`.
- **Projects**: the files `sdd-init` generated are copies. When a session opens in a project whose
  `CLAUDE.md` marker is older than the installed `sdd-core`, the plugin's session-start hook
  (`plugins/sdd-core/hooks/check-kit-version.sh`) shows a one-line notice.
  The files change only when someone runs
  `/sdd-core:sdd-init --refresh` (or the README's install prompt) in the project; it applies the kit's
  changes and keeps local edits. Say in the CHANGELOG when a refresh is worth it.

## Changing the git guardrail hook

The hook is copied into projects. Any change must keep `block-git-writes.test.sh` green and add the
cases it covers; projects get it through `--refresh`, which replaces the `.sh`/`.pl`/`.test.sh` files
and keeps the project's `.conf`.
