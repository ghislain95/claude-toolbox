#!/bin/bash
# Tests for check-kit-version.sh. Run: bash plugins/sdd-core/hooks/check-kit-version.test.sh
H="$(cd "$(dirname "$0")" && pwd)/check-kit-version.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/plugin/.claude-plugin"
printf '{\n  "name": "sdd-core",\n  "version": "0.2.0"\n}\n' > "$TMP/plugin/.claude-plugin/plugin.json"
fail=0; n=0

# t <expect: warn|quiet> <description> <CLAUDE.md content or __none__>
t() {
  local expect="$1" what="$2" content="$3" proj out
  n=$((n+1))
  proj=$(mktemp -d "$TMP/p.XXXX")
  [ "$content" = "__none__" ] || printf '%s\n' "$content" > "$proj/CLAUDE.md"
  out=$(echo '{}' | CLAUDE_PROJECT_DIR="$proj" CLAUDE_PLUGIN_ROOT="$TMP/plugin" bash "$H"; echo "rc=$?")
  case "$expect" in
    warn)  [[ "$out" == *'"systemMessage"'*'0.1.0'*'0.2.0'* && "$out" == *"rc=0" ]] || { echo "FAIL ($what): $out"; fail=1; } ;;
    quiet) [ "$out" = "rc=0" ] || { echo "FAIL ($what): $out"; fail=1; } ;;
  esac
  if [ "$expect" = warn ]; then
    printf '%s' "${out%rc=0}" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null \
      || { echo "FAIL ($what): output is not valid JSON"; fail=1; }
  fi
}

t quiet "no CLAUDE.md" "__none__"
t quiet "CLAUDE.md without marker" "# Project"
t quiet "same version" "# P
<!-- sdd-kit: installed 0.2.0 on 2026-11-07 — options: lean — autonomy: autonomy-pr -->"
t warn  "project behind plugin" "# P
<!-- sdd-kit: installed 0.1.0 on 2026-11-07 — options: lean — autonomy: autonomy-pr -->"
t quiet "project ahead of plugin" "# P
<!-- sdd-kit: installed 0.10.0 on 2026-11-07 -->"
t quiet "malformed marker" "<!-- sdd-kit: installed someday -->"
t warn  "last marker wins" "<!-- sdd-kit: installed 0.2.0 on 2026-11-01 -->
<!-- sdd-kit: installed 0.1.0 on 2026-11-07 -->"
t quiet "new marker, same version" "# P
<!-- claude-toolbox: installed 0.2.0 on 2026-11-12 — options: lean — autonomy: autonomy-pr -->"
t warn  "new marker, project behind plugin" "# P
<!-- claude-toolbox: installed 0.1.0 on 2026-11-12 — options: lean — autonomy: autonomy-pr -->"
t warn  "former then new marker, last wins" "<!-- sdd-kit: installed 0.2.0 on 2026-11-01 -->
<!-- claude-toolbox: installed 0.1.0 on 2026-11-12 -->"
t warn  "marker without autonomy field (current form), project behind plugin" "# P
<!-- claude-toolbox: installed 0.1.0 on 2026-11-13 — options: lean, github -->"
t quiet "unrelated tool's marker ending like ours" "<!-- other-sdd-kit: installed 0.1.0 on 2026-11-12 -->"
t quiet "unrelated tool's marker ending like the new one" "<!-- my-claude-toolbox: installed 0.1.0 on 2026-11-12 -->"

# A project that keeps its rules in .claude/CLAUDE.md (root CLAUDE.md absent, or without a marker).
# tc <expect> <description> <root CLAUDE.md content or __none__> <.claude/CLAUDE.md content>
tc() {
  local expect="$1" what="$2" root="$3" nested="$4" proj out
  n=$((n+1))
  proj=$(mktemp -d "$TMP/p.XXXX"); mkdir -p "$proj/.claude"
  [ "$root" = "__none__" ] || printf '%s\n' "$root" > "$proj/CLAUDE.md"
  printf '%s\n' "$nested" > "$proj/.claude/CLAUDE.md"
  out=$(echo '{}' | CLAUDE_PROJECT_DIR="$proj" CLAUDE_PLUGIN_ROOT="$TMP/plugin" bash "$H"; echo "rc=$?")
  case "$expect" in
    warn)  [[ "$out" == *'"systemMessage"'*'0.1.0'*'0.2.0'* && "$out" == *"rc=0" ]] || { echo "FAIL ($what): $out"; fail=1; } ;;
    quiet) [ "$out" = "rc=0" ] || { echo "FAIL ($what): $out"; fail=1; } ;;
  esac
}
tc warn  "marker in .claude/CLAUDE.md, no root CLAUDE.md" "__none__" "<!-- claude-toolbox: installed 0.1.0 on 2026-11-14 -->"
tc warn  "root CLAUDE.md without marker, marker in .claude/CLAUDE.md" "# P" "<!-- claude-toolbox: installed 0.1.0 on 2026-11-14 -->"
tc quiet "root marker wins over .claude/CLAUDE.md" "<!-- claude-toolbox: installed 0.2.0 on 2026-11-14 -->" "<!-- claude-toolbox: installed 0.1.0 on 2026-11-14 -->"
tc quiet ".claude/CLAUDE.md without marker" "__none__" "# P"

# Missing plugin manifest: quiet.
n=$((n+1))
proj=$(mktemp -d "$TMP/p.XXXX"); printf '<!-- sdd-kit: installed 0.1.0 on x -->\n' > "$proj/CLAUDE.md"
out=$(echo '{}' | CLAUDE_PROJECT_DIR="$proj" CLAUDE_PLUGIN_ROOT="$TMP/none" bash "$H"; echo "rc=$?")
[ "$out" = "rc=0" ] || { echo "FAIL (missing manifest): $out"; fail=1; }

[ "$fail" = 0 ] && echo "ALL $n CASES OK"
exit "$fail"
