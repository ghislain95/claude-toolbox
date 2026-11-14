#!/bin/bash
# PreToolUse hook (Bash): git guardrail for agents. The rules it enforces: docs/CONTRIBUTING.md §2.
# Agents commit and push feature branches; main only moves through a merged PR.
# Blocked: commit/merge/revert/cherry-pick/subtree add on main; pushing main (also through HEAD, @,
# a $-expanded destination, a wildcard or `:` refspec, subtree push, send-pack), pushing without an
# explicit remote and branch, force-push (--force-with-lease only when ALLOW_FORCE_WITH_LEASE=1,
# never to main); a branch set to track main (-u, --set-upstream-to, --track, branch -c of a branch
# that tracks it, or a branch created from origin/main without --no-track); pull without --ff-only,
# with rebase, or (on main) of another branch; history rewriting (rebase, amend, am, commit-tree,
# filter-branch, update-ref, reset to a revision, branch -f); sweeping stages (add -A/./*/-u,
# commit -a); discarding work; skipped hooks (--no-verify, commit -n, core.hooksPath, HUSKY=0);
# through `gh api`: merging (REST merge endpoint, /merges, GraphQL merge and auto-merge mutations),
# writing a protected branch or contents, posting the merge-conditions status. Long options are also
# caught abbreviated (git accepts `--no-verif`, `--forc`), quoted subcommands unquoted (`git "push"`).
# The single merge route: `gh pr merge <n> --<MERGE_METHOD> --match-head-commit <sha>` (plus
# --delete-branch, --subject, --body), alone in its command (only read-only git/gh commands around
# it, and `gh pr edit <n> --add-label in-flight` after it), without -R/--repo, GH_REPO or GH_HOST.
# Before allowing it the hook asks GitHub itself, never the command line, within one 40-second
# deadline: the pull request is open, into the default branch, and <sha> is its head (GitHub then
# refuses the merge if the head moves); the newest `merge-conditions` status of that commit was
# posted by its workflow (github-actions[bot]) and is success with `gates: none`; the `base <sha7>`
# it judged against is the default branch's current head; no other pull request carries the
# `in-flight` label (issues API, every page); no open issue carries `deploy-refused` (a deploy the
# deploy guard refused, not resolved yet). Any failed or late query, or no gh, blocks.
# The branch is the one checked out where the command really runs: the tool call's cwd, then each
# `cd`/`pushd`/`popd` and `git -C <dir>` (subshells restore the directory), and a
# `git switch|checkout <branch>` earlier in the same command — to main at once, to another branch
# only when the next command is chained with && (a failed switch stops the chain). A directory or
# branch that cannot be resolved ($-expanded, `cd -`, a directory that does not exist) counts as main.
# Before the checks, the command is read the way the shell reads it (block-git-writes.pl): only
# what the shell runs is left, commit messages and PR bodies are never read as flags or commands.
# Adapted from mattpocock/skills (misc/git-guardrails-claude-code, MIT).
# A guardrail against mistakes, not a sandbox: deliberate evasions (sh -c "...", eval,
# `git --git-dir x commit`) are out of scope.
# Exit 2 = block the tool call and show stderr to the agent. Exit 1 = non-blocking error shown to the user.

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  if printf '%s' "$INPUT" | grep -qE '(^|[^[:alnum:]_-]|\\[nt])(git|gh)[[:space:]]'; then
    echo "block-git-writes: jq not found — git and gh commands stay blocked until jq is installed (brew install jq)." >&2
    exit 2
  fi
  exit 0
fi

COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
[ -z "$COMMAND" ] && exit 0
set -f

# Read the command the way the shell does (block-git-writes.pl, see its header). Without perl,
# only backslash-continued lines are joined. If the reader fails, git and gh commands are blocked.
HOOK_DIR=$(cd "$(dirname "$0")" && pwd)
if command -v perl >/dev/null 2>&1; then
  if ! NEUTRAL=$(printf "%s" "$COMMAND" | perl "$HOOK_DIR/block-git-writes.pl"); then
    if printf "%s" "$COMMAND" | grep -qE "(^|[^[:alnum:]_-])(git|gh)[[:space:]]"; then
      echo "block-git-writes: the shell reader (block-git-writes.pl) failed — git and gh commands are blocked." >&2
      exit 2
    fi
    exit 0
  fi
else
  NEUTRAL=${COMMAND//$'\\\n'/ }
fi

# Where a command starts: line start, after ; & | ( { ! or $(, after a shell keyword
# (if/then/do/else/while/until) or a wrapper (env, command, exec, nohup, time, sudo, xargs,
# timeout N), or after a VAR=value assignment.
START='(^|[;&|({!]|\$\(|(^|[[:space:]])((if|then|do|else|while|until|env|command|exec|nohup|time|sudo|xargs)|timeout[[:space:]]+[0-9]+[smhd]?|[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:]]*))[[:space:]])'
# A path or option value: double-quoted, single-quoted, or a word with backslash escapes.
VALUE='("([^"\\]|\\.)*"|'"'"'[^'"'"']*'"'"'|(\\.|[^[:space:]\\])+)'
# Global options before the subcommand: -C dir, -c key=value, --long[=value], -p/-P.
GOPT="[[:space:]]+(-[cC][[:space:]]+${VALUE}|--[a-z-]+(=[^[:space:]]+)?|-[pP])"
# A git invocation at a command position, optionally via a wrapper binary (rtk) or an absolute path.
GIT="${START}[[:space:]]*(rtk[[:space:]]+)?([^[:space:];&|()]*/)?git(${GOPT})*[[:space:]]+"
GH="${START}[[:space:]]*([^[:space:];&|()]*/)?gh[[:space:]]+"
# End of a subcommand word: whitespace, an operator, a redirection, or end of line.
END='([[:space:]]|[;&|)<>]|$)'
# Project settings: block-git-writes.conf next to this script, plain KEY=value lines, never sourced.
#   PROTECTED_BRANCHES  regex alternation of the branches that only move through a merged PR (main|master)
#   ALLOW_PUSH              1 = agents push their branch; 0 = every git push is blocked (a human pushes,
#                           e.g. no remote the agent may push to)
#   MERGE_METHOD            squash | merge: the method of the merge route (default merge). Any other
#                           value, rebase included, blocks every agent merge: the deploy guard needs
#                           the default branch before the merge as one commit, which a rebase merge
#                           does not leave.
#   ALLOW_FORCE_WITH_LEASE  1 = `git push --force-with-lease` allowed to a non-protected branch;
#                           0 (default) = blocked like any force-push
#   A former ALLOW_PR_MERGE line is ignored: whether the agent merges is decided per pull request.
conf() {
  local v
  [ -f "$HOOK_DIR/block-git-writes.conf" ] || return 0
  v=$(grep -E "^$1=" "$HOOK_DIR/block-git-writes.conf" | tail -n 1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]*$//; s/^["'"'"']//; s/["'"'"']$//')
  printf '%s' "$v"
}
PROTECTED_BRANCHES=$(conf PROTECTED_BRANCHES); ALLOW_PUSH=$(conf ALLOW_PUSH)
MERGE_METHOD=$(conf MERGE_METHOD); ALLOW_FORCE_WITH_LEASE=$(conf ALLOW_FORCE_WITH_LEASE)
[[ "$PROTECTED_BRANCHES" =~ ^[A-Za-z0-9._/|-]+$ ]] || PROTECTED_BRANCHES='main|master'
[ "$ALLOW_PUSH" = 0 ] || ALLOW_PUSH=1
[ "$ALLOW_FORCE_WITH_LEASE" = 1 ] || ALLOW_FORCE_WITH_LEASE=0
[ -n "$MERGE_METHOD" ] || MERGE_METHOD=merge
[[ "$MERGE_METHOD" =~ ^[a-z]{1,16}$ ]] || MERGE_METHOD=invalid
# The labels and statuses the merge route reads (dev-factory: merge-conditions.yml, delivery steps).
STATUS_CONTEXT=merge-conditions
IN_FLIGHT_LABEL=in-flight
# Put by .github/workflows/deploy-alert.yml on the issue it opens when the deploy guard refuses a commit.
DEPLOY_REFUSED_LABEL=deploy-refused
# Seconds all the merge route's GitHub queries together may take before the merge is blocked. It
# stays well under the hook's timeout in .claude/settings.json (120 s): a hook that times out does
# not block the call.
GH_DEADLINE=40
# Branches that only move through a merged PR.
PROTECTED="^(${PROTECTED_BRANCHES})$"
# Inside one command segment: git's global options, its subcommand, the rest.
GITCMD_RE="(^|[[:space:]/])git((${GOPT})*)[[:space:]]+([a-z][a-z-]*)(.*)"
C_RE="-C[[:space:]]+${VALUE}(.*)"
KEYWORDS='^[[:space:]]*((if|then|do|else|while|until|!)[[:space:]]+)*'
CD_RE="${KEYWORDS}(cd|pushd)(([[:space:]]+-[LPe@]+)*)([[:space:]]+${VALUE})?([[:space:]]|$)"
POPD_RE="${KEYWORDS}popd([[:space:]]|$)"

# `git [-C dir] merge|rebase|cherry-pick|revert|am --abort|--quit` only leaves an operation in
# progress (e.g. a conflict the user opened): it is neutralised before the checks, the rest of the
# command is still checked (`git rebase --abort && git push` stays blocked).
# A quoted string without spaces or shell characters is the bare word to the shell: `git "push"`,
# `gh pr 'merge'` are unquoted before anything is matched (twice: adjacent strings share a boundary).
ONEWORD='s#"([A-Za-z0-9._/@:+=,%^~-]*)"#\1#g; s#'"'"'([A-Za-z0-9._/@:+=,%^~-]*)'"'"'#\1#g'
CHECKED=$(printf '%s' "$NEUTRAL" | sed -E "$ONEWORD" | sed -E "$ONEWORD" \
  | sed -E 's/(^|[^[:alnum:]_.\/-])git([[:space:]]+-[cC][[:space:]]+[^[:space:]]+)*[[:space:]]+(merge|rebase|cherry-pick|revert|am)[[:space:]]+--(abort|quit)([[:space:]]|[;&|)]|$)/\1true\5/g')

# pfx <--option> <length>: ERE alternation of the option and its abbreviations down to <length>
# characters — git accepts any unambiguous prefix of a long option (`--no-verif`, `--forc`).
pfx() {
  local o=$1 n=$2 r=$1
  while [ "$n" -lt "${#o}" ]; do r="$r|${o:0:$n}"; n=$((n + 1)); done
  printf '(%s)' "$r"
}
# End of an option word: as END, or `=` and its value.
OEND='([[:space:]=]|[;&|)<>]|$)'

block() {
  echo "BLOCKED by .claude/hooks/block-git-writes.sh: '$COMMAND' — $1. Project git rules: docs/CONTRIBUTING.md §2." >&2
  exit 2
}

# check <pattern> <reason>: blocks when the pattern matches anywhere in the command.
check() {
  printf '%s' "$CHECKED" | grep -qE -- "$1"
  local rc=$?
  [ "$rc" -eq 0 ] && block "$2"
  if [ "$rc" -ne 1 ]; then
    echo "block-git-writes: pattern error (grep exit $rc) on '$1' — the guardrail is degraded." >&2
    exit 1
  fi
}

# matches <segment> <pattern>
matches() {
  printf '%s' "$1" | grep -qE -- "$2"
}

unquote() {
  local w=${1//\"/}
  printf '%s' "${w//\'/}"
}

# resolve_dir <base> <path>: the directory a cd/pushd/-C lands in, or "?" when it cannot be known.
resolve_dir() {
  local base=$1 p=$2
  [ "$base" = "?" ] && { echo "?"; return; }
  case "$p" in
    \"*\") p=${p#\"}; p=${p%\"} ;;
    \'*\') p=${p#\'}; p=${p%\'} ;;
    *) p=$(printf '%s' "$p" | sed -E 's/\\(.)/\1/g') ;;
  esac
  case "$p" in *'$'*|*'`'*|-|'') echo "?"; return ;; esac
  case "$p" in '~') p=$HOME ;; '~/'*) p="$HOME/${p#\~/}" ;; esac
  case "$p" in /*) ;; *) p="$base/$p" ;; esac
  [ -d "$p" ] || { echo "?"; return; }
  echo "$p"
}

top_of() {
  [ "$1" = "?" ] && { echo "?"; return; }
  git -C "$1" rev-parse --show-toplevel 2>/dev/null || echo "$1"
}

# A `git switch|checkout` earlier in the same command overrides the checked-out branch of its repo.
OV_TOP=
OV_BRANCH=
branch_of() {
  local top
  top=$(top_of "$1")
  [ "$top" = "?" ] && { echo "?"; return; }
  if [ -n "$OV_TOP" ] && [ "$top" = "$OV_TOP" ]; then
    echo "$OV_BRANCH"
    return
  fi
  git -C "$top" symbolic-ref --quiet --short HEAD 2>/dev/null
}

protected() {
  [ "$1" = "?" ] || [[ "$1" =~ $PROTECTED ]]
}

describe() {
  if [ "$1" = "?" ]; then echo "an unresolvable directory or branch (counts as main)"; else echo "$1"; fi
}

# track_switch <dir> <words...>
track_switch() {
  local dir=$1 w new= orphan=0 target= pos=0 top track=default
  shift
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    case "$w" in
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') shift ;;
      [0-9]'>'*|'>'*|'<'*) ;;
      -) pos=$((pos + 1)); [ -z "$target" ] && target=- ;;
      -c|-b|--create) new=$(unquote "$1"); shift ;;
      --orphan) new=$(unquote "$1"); orphan=1; shift ;;
      -t|--track|--track=direct) track=direct ;;
      --track=inherit) track=inherit ;;
      --no-track) track=no ;;
      --detach|-d) target=DETACHED ;;
      --) return ;;
      -*) ;;
      *) pos=$((pos + 1)); [ -z "$target" ] && target=$w ;;
    esac
  done
  top=$(top_of "$dir")
  if [ -n "$new" ] && [ "$orphan" = 0 ] && ! [[ "$new" =~ $PROTECTED ]] && tracks_protected "$dir" "$track" "$target"; then
    block "$new would track a protected branch: create it with --no-track (git switch -c $new --no-track <start>)"
  fi
  # `switch --track <remote>/<branch>` creates and switches to <branch>.
  if [ -z "$new" ] && [ "$track" != default ] && [ "$track" != no ] && [ -n "$target" ]; then
    set -- $(ref_branch "$top" "$target")
    [ "$1" = remote ] && target=$2
  fi
  if [ -n "$new" ]; then
    case "$new" in *'$'*) new="?" ;; esac
    switch_to "$top" "$new"
    return
  fi
  # `checkout <tree-ish> <paths>` restores files, it does not switch.
  [ "$pos" -ge 2 ] && return
  case "$target" in
    '') return ;;
    DETACHED) switch_to "$top" "" ;;
    -|*'$'*) switch_to "$top" "?" ;;
    *)
      if [[ "$target" =~ $PROTECTED ]] \
        || git -C "$top" show-ref --verify --quiet "refs/heads/$target" 2>/dev/null \
        || [ -n "$(git -C "$top" for-each-ref --count=1 --format='%(refname)' "refs/remotes/*/$target" 2>/dev/null)" ]; then
        switch_to "$top" "$target"
      fi
      ;;
  esac
}

# ref_branch <top> <ref>: "local <branch>" or "remote <branch>" for a start point or an upstream:
# refs/heads/x, refs/remotes/<r>/x, and <r>/x when <r> is a remote of the repository (any <r>/x when
# the repository cannot be resolved).
ref_branch() {
  local top=$1 r=$2
  case "$r" in
    refs/heads/*) echo "local ${r#refs/heads/}"; return ;;
    refs/remotes/*/*) r=${r#refs/remotes/}; echo "remote ${r#*/}"; return ;;
    */*)
      if [ "$top" = "?" ] || git -C "$top" remote 2>/dev/null | grep -qxF -- "${r%%/*}" \
        || git -C "$top" show-ref --verify --quiet "refs/remotes/$r" 2>/dev/null; then
        echo "remote ${r#*/}"
        return
      fi
      ;;
  esac
  echo "local $r"
}

# tracks_protected <dir> <track> <start point>: whether a branch created from <start point> gets a
# protected branch as its upstream. <track>: direct (--track), inherit (--track=inherit), no
# (--no-track) or default, which follows the repository's branch.autoSetupMerge as git does (true,
# git's default: only a remote-tracking start point is tracked). An unresolvable start point counts
# as main.
tracks_protected() {
  local dir=$1 track=$2 start=$3 top setup up
  [ "$track" = no ] && return 1
  top=$(top_of "$dir")
  if [ "$track" = default ]; then
    setup=
    [ "$top" = "?" ] || setup=$(git -C "$top" config --get branch.autoSetupMerge 2>/dev/null)
    case "$setup" in
      false|simple) return 1 ;;
      always) track=direct ;;
      inherit) track=inherit ;;
      *) track=remote ;;
    esac
  fi
  if [ -z "$start" ]; then
    [ "$track" = inherit ] || return 1
    start=$(branch_of "$dir")
    [ -n "$start" ] || return 1
  fi
  case "$start" in *'$'*|'?'|-) return 0 ;; esac
  set -- $(ref_branch "$top" "$start")
  if [ "$track" = remote ]; then
    [ "$1" = remote ] || return 1
  elif [ "$track" = inherit ] && [ "$1" = local ]; then
    up=
    [ "$top" = "?" ] || up=$(git -C "$top" config --get "branch.$2.merge" 2>/dev/null)
    up=${up#refs/heads/}
    [ -n "$up" ] && [[ "$up" =~ $PROTECTED ]]
    return
  fi
  [[ "$2" =~ $PROTECTED ]]
}

# check_branch <dir> <words...>: `git branch` never sets a protected branch as the upstream of
# another branch (-u, --set-upstream-to, or creating a branch that tracks it).
check_branch() {
  local dir=$1 w upstream= set_up=0 track=default other=0 copy=0 target first= second= count=0 up top
  shift
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    case "$w" in
      -u|--set-upstream-to) set_up=1; upstream=$(unquote "$1"); shift ;;
      --set-upstream-to=*) set_up=1; upstream=${w#*=} ;;
      -u?*) set_up=1; upstream=${w#-u} ;;
      -t|--track|--track=direct) track=direct ;;
      --track=inherit) track=inherit ;;
      --no-track) track=no ;;
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') shift ;;
      [0-9]'>'*|'>'*|'<'*) ;;
      --) ;;
      --create-reflog|--recurse-submodules|-q|--quiet) ;;
      -c|-C|--copy) copy=1 ;;
      -*) other=1 ;;
      *)
        count=$((count + 1))
        [ "$count" = 1 ] && first=$w
        [ "$count" = 2 ] && second=$w
        ;;
    esac
  done
  if [ "$set_up" = 1 ]; then
    target=${first:-$(branch_of "$dir")}
    [ -n "$target" ] && [ "$target" != "?" ] && [[ "$target" =~ $PROTECTED ]] && return
    case "$upstream" in *'$'*|'') block "the upstream cannot be resolved: name it literally, never a protected branch" ;; esac
    set -- $(ref_branch "$(top_of "$dir")" "$upstream")
    [[ "$2" =~ $PROTECTED ]] && block "never let a branch track $2: it would pull and push the protected branch (git branch --unset-upstream)"
    return
  fi
  # Copying a branch copies its upstream: `branch -c [<old>] <new>` tracks what <old> tracks.
  if [ "$copy" = 1 ] && [ "$other" = 0 ] && [ "$count" -ge 1 ] && [ "$count" -le 2 ]; then
    if [ "$count" = 2 ]; then target=$second; else target=$first; first=$(branch_of "$dir"); fi
    [[ "$target" =~ $PROTECTED ]] && return
    case "$first" in *'$'*|'?') block "the branch to copy cannot be resolved: name it" ;; esac
    top=$(top_of "$dir")
    up=
    [ "$top" = "?" ] || up=$(git -C "$top" config --get "branch.$first.merge" 2>/dev/null)
    up=${up#refs/heads/}
    [ -n "$up" ] && [[ "$up" =~ $PROTECTED ]] \
      && block "$target would track $up, copied from $first: create it with git switch -c $target --no-track <start>"
    return
  fi
  # Listing, deleting, renaming: no new upstream.
  [ "$other" = 0 ] && [ "$copy" = 0 ] && [ "$count" -ge 1 ] && [ "$count" -le 2 ] || return
  [[ "$first" =~ $PROTECTED ]] && return
  tracks_protected "$dir" "$track" "$second" \
    && block "$first would track a protected branch: create it with --no-track (git branch --no-track $first <start>)"
}

# check_worktree <dir> <words...>: `worktree add -b <new> <path> <start>` follows the same rule.
check_worktree() {
  local dir=$1 w new= track=default pos=0 start=
  shift
  [ "$(unquote "$1")" = add ] || return
  shift
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    case "$w" in
      -b|-B) new=$(unquote "$1"); shift ;;
      --track) track=direct ;;
      --no-track) track=no ;;
      --reason) shift ;;
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') shift ;;
      [0-9]'>'*|'>'*|'<'*) ;;
      -*) ;;
      *) pos=$((pos + 1)); [ "$pos" = 2 ] && start=$w ;;
    esac
  done
  [ -n "$new" ] || return
  [[ "$new" =~ $PROTECTED ]] && return
  tracks_protected "$dir" "$track" "$start" \
    && block "$new would track a protected branch: add --no-track (git worktree add --no-track -b $new <dir> <start>)"
}

# switch_to <top> <branch>: a switch to main (or to an unknown branch) counts at once; to another
# branch it stays pending until the next command is chained with &&.
PEND=0
PEND_TOP=
PEND_BRANCH=
switch_to() {
  if protected "$2"; then
    OV_TOP=$1
    OV_BRANCH=$2
    PEND=0
  else
    PEND=1
    PEND_TOP=$1
    PEND_BRANCH=$2
  fi
}

# check_subtree <dir> <words...>: `subtree push` never targets a protected branch; `subtree add`,
# `merge`, `pull` commit on the checked-out branch, like a commit.
check_subtree() {
  local dir=$1 w op= last= br
  shift
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    case "$w" in
      -P|--prefix|-m|--message|-b|--branch|--onto|--annotate) shift ;;
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') shift ;;
      -*|[0-9]'>'*|'>'*|'<'*) ;;
      *) if [ -z "$op" ]; then op=$w; else last=$w; fi ;;
    esac
  done
  case "$op" in
    push)
      [ "$ALLOW_PUSH" = 1 ] || block "a human pushes in this project (ALLOW_PUSH=0): commit on the branch and stop"
      last=${last##*:}
      last=${last#refs/heads/}
      case "$last" in ''|*'$'*) block "subtree push: name the remote and a branch that is not protected" ;; esac
      [[ "$last" =~ $PROTECTED ]] && block "never push $last: it only moves through a merged PR"
      ;;
    add|merge|pull)
      br=$(branch_of "$dir")
      protected "$br" && block "never subtree $op on $(describe "$br"): work on a branch, main only moves through a merged PR"
      ;;
  esac
}

# check_reset <dir> <words...>: `reset <commit>` (other than HEAD) moves the branch back.
check_reset() {
  local dir=$1 w pos=0 rev= top
  shift
  for w in "$@"; do
    w=$(unquote "$w")
    case "$w" in
      --) return ;;
      -*|[0-9]'>'*|'>'*|'<'*) ;;
      *) pos=$((pos + 1)); [ "$pos" = 1 ] && rev=$w ;;
    esac
  done
  [ "$pos" = 1 ] || return
  case "$rev" in HEAD|@) return ;; esac
  top=$(top_of "$dir")
  [ "$top" = "?" ] && return
  git -C "$top" rev-parse --verify --quiet "$rev^{commit}" >/dev/null 2>&1 \
    && block "never move a branch back: add a new commit (git revert)"
}

# check_pull <dir> <words...>: --ff-only only, no rebase; on main, only main itself.
check_pull() {
  local dir=$1 w pos=0 second= br ref
  shift
  case " $* " in *" --ff-only "*) ;; *) block "pull only with --ff-only" ;; esac
  case " $* " in *" --rebase"*|*" -r "*) block "never pull with rebase" ;; esac
  for w in "$@"; do
    w=$(unquote "$w")
    case "$w" in
      -*|[0-9]'>'*|'>'*|'<'*) ;;
      *) pos=$((pos + 1)); [ "$pos" = 2 ] && second=$w ;;
    esac
  done
  [ -z "$second" ] && return
  br=$(branch_of "$dir")
  if protected "$br"; then
    ref=${second%%:*}
    ref=${ref#+}
    ref=${ref#refs/heads/}
    [[ "$ref" =~ $PROTECTED ]] || block "on $(describe "$br"), pull only main itself: git pull --ff-only [origin main]"
  fi
}

# check_push <dir> <words...>: explicit remote and branch, never main, never forced.
# abbrev <word> <--option> <shortest>: the word is the option or one of its abbreviations (with or
# without `=value`), as git's option parser accepts them.
abbrev() {
  local w=${1%%=*}
  [ "${#w}" -ge "$3" ] && [[ "$2" == "$w"* ]]
}

check_push() {
  local dir=$1 w ref positional=0 skip=0 br= br_read=0 lease=0 includes=0 deleting=0
  shift
  for w in "$@"; do
    if [ "$skip" = 1 ]; then
      skip=0
      continue
    fi
    w=$(unquote "$w")
    if abbrev "$w" --force-with-lease 9; then
      [ "$ALLOW_FORCE_WITH_LEASE" = 1 ] || block "never force-push (--force-with-lease is off in this project: ALLOW_FORCE_WITH_LEASE=0)"
      lease=1
      continue
    fi
    if abbrev "$w" --force-if-includes 9; then includes=1; continue; fi
    if abbrev "$w" --force 3 || abbrev "$w" --force- 8 || abbrev "$w" --mirror 4 || abbrev "$w" --all 4 \
      || abbrev "$w" --prune 5; then
      block "never force-push nor push every ref"
    fi
    case "$w" in
      '') ;;
      -d|--delete) deleting=1 ;;
      -o|--push-option|--receive-pack|--exec) skip=1 ;;
      --repo) skip=1; positional=$((positional + 1)) ;;
      --repo=*) positional=$((positional + 1)) ;;
      --*) ;;
      -*f*) block "never force-push" ;;
      -*) ;;
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') skip=1 ;;
      [0-9]'>'*|'>'*|'<'*) ;;
      *)
        positional=$((positional + 1))
        [ "${w#+}" != "$w" ] && block "never force-push (+refspec)"
        [ "$positional" -lt 2 ] && continue
        case "$w" in
          *'*'*) block "never push a wildcard refspec: name the branch" ;;
          :) block "never push every matching branch (:): name the branch" ;;
          *:*'$'*) block "the destination of $w cannot be resolved, so it counts as a protected branch: name it" ;;
        esac
        ref=${w##*:}
        ref=${ref#refs/heads/}
        [ "$deleting" = 1 ] && case "$ref" in *'$'*) block "the branch to delete cannot be resolved, so it counts as a protected branch: name it" ;; esac
        case "$ref" in
          HEAD|@|*'$'*)
            if [ "$br_read" = 0 ]; then br=$(branch_of "$dir"); br_read=1; fi
            protected "$br" && block "never push $(describe "$br"): it only moves through a merged PR"
            ;;
        esac
        [[ "$ref" =~ $PROTECTED ]] && block "never push $ref: it only moves through a merged PR"
        ;;
    esac
  done
  [ "$includes" = 1 ] && [ "$lease" = 0 ] && block "never force-push (--force-if-includes)"
  [ "$positional" -lt 2 ] && block "name the remote and the branch explicitly: git push -u origin <branch>"
}

# gh_parse <segment>: GH_SUB = "<first word> <second word>" after `gh` and its flags (`gh -R o/r pr
# merge` and `gh pr --repo o/r merge` give "pr merge"), GH_ARGS = every other word after `gh`,
# flags placed before the subcommand included (`gh pr --admin merge`), GH_REPO_FLAG = 1 when
# -R/--repo appears anywhere.
gh_parse() {
  local w found=0 first= second=
  GH_SUB= GH_ARGS= GH_REPO_FLAG=0
  set -- $1
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    if [ "$found" = 0 ]; then
      case "$w" in gh|*/gh) found=1 ;; esac
      continue
    fi
    case "$w" in
      -R|--repo) GH_REPO_FLAG=1; shift; continue ;;
      -R?*|--repo=*) GH_REPO_FLAG=1; continue ;;
    esac
    if [ -z "$second" ]; then
      case "$w" in -*) GH_ARGS="$GH_ARGS $w"; continue ;; esac
      if [ -z "$first" ]; then first=$w; else second=$w; fi
    else
      GH_ARGS="$GH_ARGS $w"
    fi
  done
  GH_SUB="$first $second"
}

# gh_api_spans: each simple command of the raw command (quotes kept, split at unquoted ; & | ( )
# and newlines) that runs `gh api`, NUL-separated. API paths ("repos/{owner}/{repo}/…") and GraphQL
# queries are usually quoted with braces, which the reader blanks: they are read on the raw text,
# but only within the gh api command itself.
gh_api_spans() {
  printf '%s' "$COMMAND" | perl -e '
    local $/; my $s = <STDIN>; my ($q, $cur, @spans) = ("", "");
    for (my $i = 0; $i < length $s; $i++) {
      my $c = substr($s, $i, 1);
      if ($q) { $cur .= $c; if ($c eq "\\" && $q eq "\"") { $cur .= substr($s, ++$i, 1); next } $q = "" if $c eq $q; next }
      if ($c eq "\\") { $cur .= $c . substr($s, ++$i, 1); next }
      if ($c eq "\x27" || $c eq "\"") { $q = $c; $cur .= $c; next }
      if ($c =~ /[;&|()\n]/) { push @spans, $cur; $cur = ""; next }
      $cur .= $c;
    }
    push @spans, $cur;
    for (@spans) {
      print "$_\0" if /^\s*(?:(?:env|command|exec|nohup|time|sudo|xargs|rtk|if|then|do|else|while|until|!)\s+|timeout\s+\d+[smhd]?\s+|[A-Za-z_]\w*=\S*\s+)*(?:\S*\/)?gh\s+api(?:\s|$)/;
    }'
}

# check_gh_api: `gh api` never merges, auto-merges, writes a branch or writes the merge-conditions
# status. Sets GH_API_WRITE=1 when a gh api call of the command is not a read (method other than
# GET/HEAD: -X/--method, or fields/--input without a method).
GH_API_WRITE=0
check_gh_api() {
  local span method
  while IFS= read -r -d '' span; do
    span_has() { printf '%s' "$span" | grep -qE -- "$1"; }
    method=$(printf '%s' "$span" | grep -oE '(^|[[:space:]])(-X|--method)([[:space:]]+|=)?["'"'"']?[A-Za-z]+' | head -n 1 \
      | sed -E 's/^[[:space:]]*(-X|--method)([[:space:]]+|=)?["'"'"']?//' | tr 'a-z' 'A-Z')
    if [ -z "$method" ]; then
      method=GET
      span_has '(^|[[:space:]])(-f|-F|--field|--raw-field|--input)([[:space:]]|=|$)|(^|[[:space:]])-[fF][^[:space:]]' && method=POST
    fi
    case "$method" in GET|HEAD) ;; *) GH_API_WRITE=1 ;; esac
    span_has 'pulls/[^/[:space:]]+/merge([^[:alnum:]_-]|$)' \
      && block "never merge through the REST API: the only merge route is gh pr merge <n> --$MERGE_METHOD --match-head-commit <sha>"
    span_has 'repos/[^[:space:]]+/merges([^[:alnum:]_/-]|$)' && block "never merge branches through the API"
    span_has '(enablePullRequestAutoMerge|mergePullRequest|enqueuePullRequest|mergeBranch|createCommitOnBranch|updateRefs?)([^[:alnum:]]|$)' \
      && block "never merge, auto-merge or write a branch through the GraphQL API"
    if span_has '(^|[[:space:]])["'"'"']?graphql["'"'"']?([[:space:]]|$)' \
      && span_has '(^|[[:space:]])--input([[:space:]]|=|$)|query=@'; then
      block "a GraphQL query read from a file or stdin cannot be checked: pass it with -f query='...'"
    fi
    if span_has '/statuses/'; then
      span_has "context=[\"']?${STATUS_CONTEXT}([^[:alnum:]_-]|\$)" \
        && block "never post the $STATUS_CONTEXT status: only its workflow does"
      span_has '(^|[[:space:]])--input([[:space:]]|=|$)' \
        && block "post commit statuses with -f fields, never --input (the guardrail must see the context)"
    fi
    case "$method" in GET|HEAD) continue ;; esac
    span_has "git/refs/heads/(${PROTECTED_BRANCHES})([^[:alnum:]_./-]|\$)" && block "never write a protected branch through the API"
    span_has 'repos/[^[:space:]]+/contents/' && block "never commit through the contents API: commit on the change branch"
  done < <(gh_api_spans)
  return 0
}

# check_gh_merge <dir> <words after `gh pr merge`...>: the single merge route,
# `gh pr merge <n> --<MERGE_METHOD> --match-head-commit <sha>`, then verified on GitHub
# (verify_merge). `--disable-auto` alone only cancels an automatic merge.
MERGE_NUMBER=
check_gh_merge() {
  local dir=$1 w number= method= methods=0 disable=0 match=
  shift
  [ "$GH_REPO_FLAG" = 0 ] || block "run gh pr merge in the repository's checkout, without --repo: the merge conditions are checked for that repository"
  while [ $# -gt 0 ]; do
    w=$(unquote "$1")
    shift
    case "$w" in
      --merge|-m) method=merge; methods=$((methods + 1)) ;;
      --squash|-s) method=squash; methods=$((methods + 1)) ;;
      --rebase|-r) method=rebase; methods=$((methods + 1)) ;;
      --admin|--auto) block "never bypass or defer the merge conditions (--admin, --auto)" ;;
      --disable-auto) disable=1 ;;
      --delete-branch|-d) ;;
      --subject|-t|--body|-b|--body-file|-F|--author-email|-A) shift ;;
      --subject=*|--body=*|--body-file=*|--author-email=*) ;;
      --match-head-commit) match=$(unquote "$1"); shift ;;
      --match-head-commit=*) match=${w#*=} ;;
      '>'|'>>'|[0-9]'>'|[0-9]'>>'|'<') shift ;;
      [0-9]'>'*|'>'*|'<'*) ;;
      -*) block "unknown gh pr merge option $w: the merge route is gh pr merge <n> --$MERGE_METHOD --match-head-commit <sha> [--delete-branch]" ;;
      *)
        [ -z "$number" ] || block "merge one pull request, named by its number: gh pr merge <n> --$MERGE_METHOD --match-head-commit <sha>"
        number=$w
        ;;
    esac
  done
  if [ "$disable" = 1 ]; then
    [ "$methods" = 0 ] || block "--disable-auto only cancels an automatic merge: run it alone"
    return
  fi
  case "$MERGE_METHOD" in
    squash|merge) ;;
    *) block "MERGE_METHOD=$MERGE_METHOD in block-git-writes.conf is neither squash nor merge (rebase is refused: the deploy guard needs the default branch before the merge as one commit): no agent merge until it is fixed" ;;
  esac
  [ "$methods" = 1 ] && [ "$method" = "$MERGE_METHOD" ] || block "merge with the project's method only: gh pr merge <n> --$MERGE_METHOD --match-head-commit <sha>"
  [[ "$number" =~ ^[0-9]+$ ]] || block "name the pull request by its number: gh pr merge <n> --$MERGE_METHOD --match-head-commit <sha>"
  [[ "$match" =~ ^[0-9a-f]{40}$ ]] || block "name the head commit you verified, in full: gh pr merge $number --$MERGE_METHOD --match-head-commit <sha> (gh pr view $number --json headRefOid); GitHub then refuses the merge if the head moved"
  [ "$dir" = "?" ] && block "the directory the merge runs in cannot be resolved: run gh pr merge from the repository's checkout"
  MERGE_NUMBER=$number
  verify_merge "$dir" "$number" "$match"
}

# gh_query <dir> <gh arguments...>: gh's output, run in <dir> (gh resolves the repository there, as
# the merge itself will), non-interactive, killed when the merge route's deadline (GH_DEADLINE for
# all its queries together) is reached. Fails when gh fails or time is up.
gh_query() {
  local dir=$1 left=$((DEADLINE_AT - SECONDS))
  shift
  [ "$left" -gt 0 ] || return 1
  (
    cd "$dir" 2>/dev/null || exit 1
    export GH_PROMPT_DISABLED=1 GH_PAGER=cat NO_COLOR=1
    command -v perl >/dev/null 2>&1 || exec gh "$@"
    exec perl -e 'my $t = shift; my $pid = fork; exit 1 unless defined $pid;
      if ($pid == 0) { setpgrp(0, 0); exec @ARGV or exit 127 }
      $SIG{ALRM} = sub { kill "TERM", -$pid; kill "TERM", $pid; exit 124 };
      alarm $t; waitpid($pid, 0); exit(($? & 127) ? 1 : ($? >> 8));' "$left" gh "$@"
  ) 2>/dev/null
}

fail_closed() {
  block "could not obtain $1 from GitHub in time, so the merge is blocked (fail closed): retry, or hand the merge to the owner"
}

# verify_merge <dir> <number> <head the agent names>: asks GitHub, never the command line, whether
# the agent may merge the pull request now (see the header). Blocks with the reason otherwise.
verify_merge() {
  local dir=$1 n=$2 match=$3 out slug default state head base found st login url desc judged tip others
  local re='^gates: none; base ([0-9a-f]{7})$'
  command -v gh >/dev/null 2>&1 || block "gh not found: the merge route verifies $STATUS_CONTEXT on GitHub before merging (fail closed): install gh, or hand the merge to the owner"
  DEADLINE_AT=$((SECONDS + GH_DEADLINE))
  out=$(gh_query "$dir" repo view --json nameWithOwner,defaultBranchRef) || fail_closed "the repository (gh repo view)"
  slug=$(printf '%s' "$out" | jq -r '.nameWithOwner // "-"' 2>/dev/null)
  default=$(printf '%s' "$out" | jq -r '.defaultBranchRef.name // "-"' 2>/dev/null)
  [[ "$slug" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] && [[ "$default" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] \
    || fail_closed "the repository (gh repo view)"
  out=$(gh_query "$dir" api "repos/$slug/pulls/$n") || fail_closed "pull request #$n"
  state=$(printf '%s' "$out" | jq -r '.state // "-"' 2>/dev/null)
  head=$(printf '%s' "$out" | jq -r '.head.sha // "-"' 2>/dev/null)
  base=$(printf '%s' "$out" | jq -r '.base.ref // "-"' 2>/dev/null)
  [[ "$head" =~ ^[0-9a-f]{40}$ ]] && [ -n "$state" ] && [ "$base" != "-" ] || fail_closed "pull request #$n"
  [ "$state" = open ] || block "pull request #$n is not open (state: $state)"
  [ "$base" = "$default" ] || block "pull request #$n targets $base, not the default branch $default: the agent merges only into the default branch"
  [ "$match" = "$head" ] || block "--match-head-commit $match is not the head of #$n (${head:0:12}): check that head, then name it"
  # The newest merge-conditions status of the head commit, and who posted it: the workflow posts as
  # github-actions[bot]; a status posted with a person's token is not the check.
  out=$(gh_query "$dir" api "repos/$slug/commits/$head/statuses?per_page=100") || fail_closed "the $STATUS_CONTEXT status of #$n"
  found=$(printf '%s' "$out" | jq -r --arg c "$STATUS_CONTEXT" \
    'if type != "array" then error("not a list") else
       (map(select(.context == $c)) | first) as $s
       | if $s == null then "none" else [$s.state // "-", $s.creator.login // "-", $s.url // "-"] | join(" ") end
     end' 2>/dev/null) || fail_closed "the $STATUS_CONTEXT status of #$n"
  st=${found%% *}
  if [ "$st" != none ]; then
    login=${found#* }
    url=${login#* }
    login=${login%% *}
    case "$url" in */statuses/"$head") ;; *) fail_closed "the $STATUS_CONTEXT status of #$n's head commit" ;; esac
    [ "$login" = "github-actions[bot]" ] \
      || block "the latest $STATUS_CONTEXT status on #$n was posted by $login, not by its workflow (github-actions[bot]): hand the merge to the owner"
  fi
  desc=$(printf '%s' "$out" | jq -r --arg c "$STATUS_CONTEXT" 'map(select(.context == $c)) | first | .description // ""' 2>/dev/null)
  desc=${desc:0:140}
  case "$st" in
    none) block "no $STATUS_CONTEXT status on the head commit ${head:0:7} of #$n: wait for the check (a status on an older commit does not count)" ;;
    success) ;;
    pending) block "$STATUS_CONTEXT is pending on #$n ($desc): wait for it, then merge" ;;
    *) block "$STATUS_CONTEXT is $st on #$n ($desc): fix the pull request; the agent never merges it as it is" ;;
  esac
  case "$desc" in
    'gates: none' | 'gates: none;'*) ;;
    *) block "$STATUS_CONTEXT does not report 'gates: none' on #$n ($desc): hand the merge to the owner, whose merge stands for the go or the passed QA" ;;
  esac
  [[ "$desc" =~ $re ]] || block "$STATUS_CONTEXT on #$n does not name the $default commit it judged against, base <sha7> ($desc): wait for the re-judgement"
  judged=${BASH_REMATCH[1]}
  out=$(gh_query "$dir" api "repos/$slug/branches/$default") || fail_closed "the head of $default"
  tip=$(printf '%s' "$out" | jq -r '.commit.sha // "-"' 2>/dev/null)
  [[ "$tip" =~ ^[0-9a-f]{40}$ ]] || fail_closed "the head of $default"
  [ "${tip:0:7}" = "$judged" ] || block "$default moved since $STATUS_CONTEXT judged #$n (against $judged, $default is now ${tip:0:7}): wait for the re-judgement"
  # In flight = any other pull request carrying the label, whatever its state: the agent labels the
  # pull request it merged and removes the label once production is verified or rolled back. Read
  # through the issues endpoint (consistent at once, unlike search), every page.
  out=$(gh_query "$dir" api --paginate "repos/$slug/issues?labels=$IN_FLIGHT_LABEL&state=all&per_page=100") \
    || fail_closed "the pull requests in flight"
  others=$(printf '%s' "$out" | jq -rs --argjson n "$n" \
    'if all(.[]; type == "array") then add // [] | [.[] | select(.pull_request != null and .number != $n) | "#\(.number)"] | join(" ") else error("not a list") end' 2>/dev/null) \
    || fail_closed "the pull requests in flight"
  [ -z "$others" ] || block "another change is in flight ($others carries the $IN_FLIGHT_LABEL label): wait until it is verified in production or rolled back"
  # A refused deploy left on the default branch would ship with the next merge: no agent merge while
  # its issue is open (the owner resolves it and closes the issue).
  out=$(gh_query "$dir" api --paginate "repos/$slug/issues?labels=$DEPLOY_REFUSED_LABEL&state=open&per_page=100") \
    || fail_closed "the open deploy refusals"
  others=$(printf '%s' "$out" | jq -rs \
    'if all(.[]; type == "array") then add // [] | [.[] | "#\(.number)"] | join(" ") else error("not a list") end' 2>/dev/null) \
    || fail_closed "the open deploy refusals"
  [ -z "$others" ] || block "a refused deploy is not resolved ($others carries the $DEPLOY_REFUSED_LABEL label): revert it exactly through a pull request, or have the owner set the reset variable (OPENSPEC_GUIDE §8), then close the issue; no agent merge until then"
}

# A command that merges a pull request does nothing else that writes: the merge is verified against
# GitHub as it is before the command runs, so a push, a second merge or a status written in the same
# command would change what was verified. Around `gh pr merge`, only read-only git and gh commands,
# and after it `gh pr edit <n> --add-label in-flight`.
READONLY_GIT=' status log diff show rev-parse rev-list ls-remote ls-files fetch merge-base describe cat-file show-ref for-each-ref shortlog blame grep '
READONLY_GH=' pr_view pr_list pr_checks pr_status pr_diff run_list run_view run_watch repo_view auth_status '
alone() {
  block "gh pr merge runs alone: in the same command only read-only git and gh commands, and gh pr edit <n> --add-label $IN_FLIGHT_LABEL after the merge — run $1 in a separate call"
}

# --- Blocked wherever they run.
# History rewriting and raw commit creation.
check "${GIT}(rebase|am|commit-tree|filter-branch|filter-repo)${END}" "history rewriting is never delegated"
check "${GIT}update-ref${END}" "never move a ref by hand: add a new commit"
check "${GIT}commit[[:space:]][^;&|]*$(pfx --amend 4)${OEND}" "never amend a commit: add a new one"
check "${GIT}reset[[:space:]]([^;&|]*[[:space:]])?[\"']?($(pfx --soft 4)|$(pfx --mixed 4)|$(pfx --hard 4)|$(pfx --keep 4)|$(pfx --merge 4)|[^[:space:];&|]*[~^][^[:space:];&|]*|[^[:space:];&|]*@\{[^[:space:];&|]*)[\"']?${END}" "never move a branch back: add a new commit (git revert)"
# Sweeping stages: commit explicit paths only (parallel sessions share checkouts).
check "${GIT}commit[[:space:]]([^;&|]*[[:space:]])?(-[a-zA-Z]*a[a-zA-Z]*|--all)${END}" "commit -a sweeps every tracked change: stage explicit paths"
check "${GIT}add[[:space:]]([^;&|]*[[:space:]])?(-A|$(pfx --all 4)|-u|$(pfx --update 3)|\.|\./|\.\.|\.\./|\*|:/)${END}" "stage explicit paths, never the whole tree"
# Discarding work.
check "${GIT}clean[[:space:]]([^;&|]*[[:space:]])?(-[a-zA-Z]*f|$(pfx --force 3)${OEND})" "never discard work"
check "${GIT}checkout[[:space:]]([^;&|]*[[:space:]])?(\.|-f|$(pfx --force 3)|-B)${END}" "never discard work"
check "${GIT}switch[[:space:]]([^;&|]*[[:space:]])?(-f|$(pfx --force 3)|$(pfx --discard-changes 4)|-C|$(pfx --force-create 9))${END}" "never discard work"
check "${GIT}worktree[[:space:]]+remove[[:space:]]([^;&|]*[[:space:]])?(-f|$(pfx --force 3))${END}" "never discard work"
check "${GIT}restore[[:space:]]([^;&|]*[[:space:]])?\.${END}" "never discard work"
check "${GIT}stash[[:space:]]+(drop|clear)" "never discard work"
# Force-deleting, force-renaming or force-moving a branch: -D, -M, -f, combined -df/-fd.
check "${GIT}branch[[:space:]]([^;&|]*[[:space:]])?(-D|-M|-f|$(pfx --force 6)|-[a-zA-Z]*(df|fd)[a-zA-Z]*)${END}" "never force-delete, force-rename or force-move a branch"
# Skipping hooks. Only inside a git command: a bare match also blocked heredocs and greps
# that merely mention the flag.
check "${GIT}[^;&|]*$(pfx --no-verify 9)${OEND}" "never skip hooks"
check "(^|[^[:alnum:]_.\/-])git[[:space:]]([^;&|]*[[:space:]])?(-c[[:space:]]+|--config-env[[:space:]=]+)[\"']?[cC][oO][rR][eE]\.[hH][oO][oO][kK][sS][pP][aA][tT][hH]" "never skip hooks (core.hooksPath)"
if printf '%s' "$CHECKED" | grep -qE '(^|[^[:alnum:]_])HUSKY(_SKIP_HOOKS)?=' \
  && printf '%s' "$CHECKED" | grep -qE "${GIT}(commit|merge|push|revert|cherry-pick)${END}"; then
  block "never skip hooks (HUSKY=0)"
fi
check "${GIT}send-pack${END}" "push with git push, never send-pack"
check "${GIT}commit[[:space:]]([^;&|]*[[:space:]])?-[a-zA-Z]*n[a-zA-Z]*${END}" "never skip hooks (commit -n is --no-verify)"

# --- Checked per command segment, in order, following the directory and branch.
# `&&` and parentheses (subshells, command substitutions) become segments of their own: a pending
# switch needs the &&, a subshell restores the directory on exit. The `&` of a redirection
# (`2>&1`, `&>file`) is dropped first, so it neither splits a command nor breaks an && chain.
SEGMENTS=$(printf '%s' "$CHECKED" | sed -E -e 's/[0-9]*>&[0-9-]*/ /g' -e 's/&>(>?)/>\1/g' -e 's/&&/\
@AND@\
/g' -e 's/([()])/\
\1\
/g' | tr ';&|{}`' '\n\n\n\n\n\n')
# How many `gh pr merge` the command runs (at most one), before following it segment by segment.
MERGES=0
while IFS= read -r seg; do
  case "$seg" in *gh*) ;; *) continue ;; esac
  matches "$seg" "$GH" || continue
  gh_parse "$seg"
  [ "$GH_SUB" = "pr merge" ] && MERGES=$((MERGES + 1))
done <<< "$SEGMENTS"
if [ "$MERGES" -gt 0 ]; then
  [ "$MERGES" = 1 ] || block "one gh pr merge per command: each merge is verified against GitHub as it is before the command runs"
  printf '%s' "$CHECKED" | grep -qE '(^|[^[:alnum:]_])GH_(REPO|HOST)=' \
    && block "never set GH_REPO or GH_HOST in a command that merges: the merge conditions are checked for the checkout's repository"
fi
DIR=${CWD:-$PWD}
SUBSHELLS=()
PUSHED=()
while IFS= read -r seg; do
  trimmed=${seg#"${seg%%[![:space:]]*}"}
  trimmed=${trimmed%"${trimmed##*[![:space:]]}"}
  case "$trimmed" in
    '') continue ;;
    @AND@)
      if [ "$PEND" = 1 ]; then OV_TOP=$PEND_TOP; OV_BRANCH=$PEND_BRANCH; fi
      PEND=0
      continue
      ;;
  esac
  PEND=0
  case "$trimmed" in
    '(') SUBSHELLS[${#SUBSHELLS[@]}]=$DIR; continue ;;
    ')')
      k=${#SUBSHELLS[@]}
      if [ "$k" -gt 0 ]; then DIR=${SUBSHELLS[$((k - 1))]}; unset "SUBSHELLS[$((k - 1))]"; fi
      continue
      ;;
  esac
  # Cheap pre-filter: only segments that may move the directory or run git/gh are parsed.
  case "$seg" in *git*|*gh*|*cd*|*pushd*|*popd*) ;; *) continue ;; esac
  if [[ "$seg" =~ $POPD_RE ]]; then
    k=${#PUSHED[@]}
    if [ "$k" -gt 0 ]; then DIR=${PUSHED[$((k - 1))]}; unset "PUSHED[$((k - 1))]"; else DIR="?"; fi
    continue
  fi
  if [[ "$seg" =~ $CD_RE ]]; then
    verb=${BASH_REMATCH[3]}
    target=${BASH_REMATCH[7]}
    [ "$verb" = pushd ] && PUSHED[${#PUSHED[@]}]=$DIR
    if [ -n "$target" ]; then DIR=$(resolve_dir "$DIR" "$target"); else DIR=$HOME; fi
    continue
  fi
  if matches "$seg" "$GH"; then
    gh_parse "$seg"
    case "$GH_SUB" in
      'pr merge') check_gh_merge "$DIR" $GH_ARGS ;;
      api*)
        check_gh_api
        [ "$MERGES" = 0 ] || [ "$GH_API_WRITE" = 0 ] || alone "the gh api write"
        ;;
      'pr edit')
        if [ "$MERGES" -gt 0 ]; then
          # MERGE_NUMBER is set once the merge was checked: before it, no pr edit matches.
          [ "$(echo $GH_ARGS)" = "$MERGE_NUMBER --add-label $IN_FLIGHT_LABEL" ] || alone "gh pr edit"
        fi
        ;;
      *)
        if [ "$MERGES" -gt 0 ]; then
          case "$READONLY_GH" in *" ${GH_SUB// /_} "*) ;; *) alone "gh $GH_SUB" ;; esac
        fi
        ;;
    esac
    continue
  fi
  matches "$seg" "$GIT" || continue
  [[ "$seg" =~ $GITCMD_RE ]] || continue
  n=${#BASH_REMATCH[@]}
  opts=${BASH_REMATCH[2]}
  sub=${BASH_REMATCH[$((n - 2))]}
  rest=${BASH_REMATCH[$((n - 1))]}
  eff=$DIR
  while [[ "$opts" =~ $C_RE ]]; do
    eff=$(resolve_dir "$eff" "${BASH_REMATCH[1]}")
    opts=${BASH_REMATCH[$((${#BASH_REMATCH[@]} - 1))]}
  done
  if [ "$MERGES" -gt 0 ]; then
    case "$READONLY_GIT" in *" $sub "*) ;; *) alone "git $sub" ;; esac
  fi
  case "$sub" in
    switch|checkout) track_switch "$eff" $rest ;;
    branch) check_branch "$eff" $rest ;;
    worktree) check_worktree "$eff" $rest ;;
    commit|merge|revert|cherry-pick)
      br=$(branch_of "$eff")
      protected "$br" && block "never $sub on $(describe "$br"): work on a branch, main only moves through a merged PR"
      ;;
    reset) check_reset "$eff" $rest ;;
    subtree) check_subtree "$eff" $rest ;;
    pull) check_pull "$eff" $rest ;;
    push)
      [ "$ALLOW_PUSH" = 1 ] || block "a human pushes in this project (ALLOW_PUSH=0): commit on the branch and stop"
      check_push "$eff" $rest
      ;;
  esac
done <<< "$SEGMENTS"
exit 0
