#!/bin/bash
# SessionStart hook (sdd-core): tells the user when the current project was set up with an older
# claude-toolbox workflow than the installed sdd-core plugin, so they re-run the install prompt (or
# /sdd-core:sdd-init --refresh) to bring the project's generated files up to date.
# Silent and exit 0 in every other case: no CLAUDE.md, no install marker, same or newer version,
# unreadable files. Never blocks a session. No dependency beyond bash, grep, sed and sort.
# Marker written by sdd-init as the last line of CLAUDE.md (references/adoption.md §2), at the root or,
# for a project that keeps its rules in .claude/CLAUDE.md, there (the root one wins when both carry one):
#   <!-- claude-toolbox: installed 0.4.0 on 2026-11-13 — options: … -->
# Older markers end with `— autonomy: …` (the autonomy levels are gone); only the version is read.
# Projects set up before the catalog was renamed carry the former marker, still recognised:
#   <!-- sdd-kit: installed 0.2.0 on 2026-11-07 — options: … — autonomy: … -->

cat >/dev/null 2>&1   # SessionStart input is not needed

PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
MANIFEST="$PLUGIN_ROOT/.claude-plugin/plugin.json"

[ -f "$MANIFEST" ] || exit 0

VERSION_RE='[0-9]+\.[0-9]+\.[0-9]+'
installed=""
for CLAUDE_MD in "$PROJECT/CLAUDE.md" "$PROJECT/.claude/CLAUDE.md"; do
  [ -f "$CLAUDE_MD" ] || continue
  installed=$(grep -oE "<!--[[:space:]]*(claude-toolbox|sdd-kit): installed ${VERSION_RE}" "$CLAUDE_MD" 2>/dev/null | tail -n 1 | grep -oE "$VERSION_RE")
  [ -n "$installed" ] && break
done
current=$(grep -oE "\"version\"[[:space:]]*:[[:space:]]*\"${VERSION_RE}\"" "$MANIFEST" 2>/dev/null | head -n 1 | grep -oE "$VERSION_RE")
[ -n "$installed" ] && [ -n "$current" ] || exit 0
[ "$installed" = "$current" ] && exit 0

# Only warn when the project is behind the plugin (a project set up by a newer kit stays quiet).
newest=$(printf '%s\n%s\n' "$installed" "$current" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)
[ "$newest" = "$current" ] || exit 0

msg="claude-toolbox: this project was set up with sdd-core ${installed}; the installed sdd-core plugin is ${current}. Re-run the install prompt from the claude-toolbox README (or /sdd-core:sdd-init --refresh) to update the project's workflow files; local edits are kept. Changes: https://github.com/ghislain95/claude-toolbox/blob/main/CHANGELOG.md"
ctx="The project's sdd-core workflow files are older than the installed sdd-core plugin (${installed} < ${current}). Mention this once, in one line, at the start of your first reply, and suggest /sdd-core:sdd-init --refresh; do not run it unless the user asks."

printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg" "$ctx"
exit 0
