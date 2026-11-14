#!/bin/bash
# Regression tests for block-git-writes.sh. Run: bash .claude/hooks/block-git-writes.test.sh
# Each case: the cwd the agent runs in (a repo on main, or on a feature branch), the command string,
# and the expected hook exit code (2 = blocked, 0 = allowed).
# GitHub is never called: a stub `gh`, first in PATH, answers the merge route's queries from fixture
# files ($GH_FIXTURES), so the suite runs offline and in CI without a token.
SRC="${1:-$(dirname "$0")/block-git-writes.sh}"
case "$SRC" in /*) ;; *) SRC="$PWD/$SRC" ;; esac
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# The rules are tested on a copy without the project's block-git-writes.conf (defaults: main|master
# protected, push allowed, merge method `merge`, force-with-lease off); the .conf itself is tested
# further down (tc).
mkdir -p "$TMP/hook"
cp "$SRC" "$(dirname "$SRC")/block-git-writes.pl" "$TMP/hook/"
H="$TMP/hook/block-git-writes.sh"

# --- Stub gh. It accepts exactly the calls the merge route makes, and nothing else:
# `gh repo view --json nameWithOwner,defaultBranchRef` answers the file `repo-view`; `gh api <path>`
# and `gh api --paginate <path>` answer the file named after the path ('/', '?', '&', '=' turned
# into '_'); a list of issues is only answered paginated. `<file>.exit` makes that call fail with its code, `<file>.sleep` delays it (seconds); a
# missing file is a 404, any other argv an error. Every call is logged with its directory in calls.log.
mkdir -p "$TMP/gh-stub"
cat > "$TMP/gh-stub/gh" <<'STUB'
#!/bin/bash
d=${GH_FIXTURES:?}
printf '%s|%s\n' "$PWD" "$*" >> "$d/calls.log"
if [ "$#" = 4 ] && [ "$*" = "repo view --json nameWithOwner,defaultBranchRef" ]; then key=repo-view
elif [ "$#" = 2 ] && [ "$1" = api ] && [ "${2#*/issues?}" = "$2" ]; then key=$(printf '%s' "$2" | tr '/?&=' '____')
elif [ "$#" = 3 ] && [ "$1 $2" = "api --paginate" ]; then key=$(printf '%s' "$3" | tr '/?&=' '____')
else echo "stub gh: unexpected call: $*" >&2; exit 1; fi
[ -f "$d/$key.sleep" ] && sleep "$(cat "$d/$key.sleep")"
if [ -f "$d/$key.exit" ]; then echo "stub gh: simulated failure" >&2; exit "$(cat "$d/$key.exit")"; fi
[ -f "$d/$key" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
cat "$d/$key"
STUB
chmod +x "$TMP/gh-stub/gh"
export PATH="$TMP/gh-stub:$PATH"
key() { printf '%s' "$1" | tr '/?&=' '____'; }
HEAD_SHA=1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a
OLD_SHA=0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c
BASE_SHA=b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2
NEW_BASE_SHA=e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4e4
# The head the agent names, as the merge route requires.
MH="--match-head-commit $HEAD_SHA"
P_PR=repos/o/r/pulls/26
P_STATUS="repos/o/r/commits/$HEAD_SHA/statuses?per_page=100"
P_BRANCH=repos/o/r/branches/main
P_INFLIGHT='repos/o/r/issues?labels=in-flight&state=all&per_page=100'
P_REFUSED='repos/o/r/issues?labels=deploy-refused&state=open&per_page=100'
BOT='github-actions[bot]'
# fxset <fixture dir> <path> <answer>; fxfail <fixture dir> <path> [exit code]; fxsleep <dir> <path> <s>
fxset() { printf '%s' "$3" > "$1/$(key "$2")"; }
fxfail() { printf '%s' "${3:-1}" > "$1/$(key "$2").exit"; }
fxsleep() { printf '%s' "$3" > "$1/$(key "$2").sleep"; }
# status_json <state> <description> [sha] [creator]: the statuses of a commit, newest first: the
# merge-conditions one, then an older merge-conditions and a review-harness status.
status_json() {
  jq -cn --arg s "$1" --arg d "$2" --arg h "${3:-$HEAD_SHA}" --arg c "${4:-$BOT}" \
    '[{context:"merge-conditions",state:$s,description:$d,creator:{login:$c},url:("https://api.github.com/repos/o/r/statuses/"+$h)},
      {context:"review-harness",state:"success",description:"ok",creator:{login:"owner"},url:("https://api.github.com/repos/o/r/statuses/"+$h)},
      {context:"merge-conditions",state:"pending",description:"re-judging",creator:{login:"github-actions[bot]"},url:("https://api.github.com/repos/o/r/statuses/"+$h)}]'
}
# fx <name>: a fixture directory where pull request #26 of o/r is mergeable by the agent: open, into
# the default branch main, merge-conditions success with no gate on its head, posted by the
# workflow, judged against main's current head, no pull request in flight.
fx() {
  local d="$TMP/fx/$1"
  mkdir -p "$d"
  fxset "$d" repo-view '{"nameWithOwner":"o/r","defaultBranchRef":{"name":"main"}}'
  fxset "$d" "$P_PR" "{\"number\":26,\"state\":\"open\",\"head\":{\"sha\":\"$HEAD_SHA\"},\"base\":{\"ref\":\"main\"}}"
  fxset "$d" "$P_STATUS" "$(status_json success "gates: none; base ${BASE_SHA:0:7}")"
  fxset "$d" "$P_BRANCH" "{\"name\":\"main\",\"commit\":{\"sha\":\"$BASE_SHA\"}}"
  fxset "$d" "$P_INFLIGHT" '[]'
  fxset "$d" "$P_REFUSED" '[]'
  printf '%s' "$d"
}
GH_FIXTURES=$(fx default)
export GH_FIXTURES

MAIN="$TMP/on-main"
FEAT="$TMP/on-feat"
git init -q -b main "$MAIN"
git -C "$MAIN" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
git -C "$MAIN" branch feat/other
git -C "$MAIN" remote add origin https://example.invalid/o/r.git
git -C "$MAIN" update-ref refs/remotes/origin/feat/rem HEAD
git -C "$MAIN" update-ref refs/remotes/origin/main HEAD
git -C "$MAIN" config branch.main.remote origin
git -C "$MAIN" config branch.main.merge refs/heads/main
mkdir -p "$MAIN/sub" "$MAIN/sub dir"
git init -q -b feat/x "$FEAT"
git -C "$FEAT" remote add origin https://example.invalid/o/r.git
fail=0; n=0
t() {
  local expected="$1" dir="$2" cmd="$3" got
  n=$((n+1))
  printf '%s' "$(jq -n --arg c "$cmd" --arg d "$dir" '{cwd:$d, tool_input:{command:$c}}')" | "$H" 2>/dev/null
  got=$?
  if [ "$got" != "$expected" ]; then echo "FAIL (got $got, want $expected, cwd ${dir##*/}): $cmd"; fail=1; fi
}
NL=$'\n'
BT='`'

# --- must block on any branch (exit 2). Checked from a feature branch, where commits are allowed,
# so each case proves the rule itself.
for c in \
  'git rebase main' 'git rebase main --no-verify' 'git am p.patch' 'cd a && git am --no-verify p' \
  'git commit-tree HEAD^{tree}' 'git filter-branch --all' 'git rebase --abort && git push' \
  'git commit --amend' 'git commit --amend --no-edit' 'git commit --amend -m "two words"' \
  'git reset --soft HEAD~1' 'git reset HEAD~1' 'git reset --mixed HEAD^' 'git reset HEAD@{1}' \
  'git commit -a -m x' 'git commit -am x' 'git commit --all -m x' \
  'git add -A' 'git add .' 'git add --all' 'git add -u' 'git add -- .' 'git add src && git add .' \
  'git add ./' 'git add *' 'git add ..' 'cd sub && git add ../' \
  'git push' 'git push origin' 'git push -u origin' 'git push;' 'git push|tee log' 'git push&& echo ok' \
  '(cd x && git push)' 'echo $(git push)' 'git push; echo "exit=$?"' 'git push origin 2>&1' \
  'git push origin > out.log' 'git push -o ci.skip origin' 'git push --push-option ci.skip origin' \
  'git push origin main' 'git push -u origin main' 'git push origin master' 'git push origin HEAD:main' \
  'git push origin feat/x:main' 'git push origin :main' 'git push origin --delete main' 'git push origin -d main' \
  'git push origin refs/heads/main' 'git push origin "main"' \
  'git push --force origin feat/x' 'git push -f origin feat/x' 'git push -uf origin feat/x' \
  'git push --force-with-lease origin feat/x' 'git push --force-if-includes origin feat/x' \
  'git push origin +feat/x' 'git push --mirror origin' 'git push --all origin' \
  'git pull' 'git pull origin main' 'git pull --rebase' 'git pull --ff-only --rebase' 'git pull -r --ff-only' \
  'git reset --hard HEAD~1' 'git reset --keep HEAD~1' 'git clean -fd' 'git clean -d -f' 'git clean --force' 'git clean -xdf' \
  'git branch -D x' 'git branch -M x' 'git branch -f feat/x HEAD~2' 'git branch --force x' \
  'git branch --delete --force x' 'git branch -d -f x' 'git branch -f -d x' 'git branch -df x' \
  'git checkout .' 'git checkout -- .' 'git checkout .;echo' 'git checkout HEAD -- .' 'git checkout -f main' \
  'git checkout -B main origin/main' 'git restore .' 'git restore --staged .' 'git restore .;' \
  'git switch -C main origin/main' 'git switch --discard-changes main' 'git switch -f main' \
  'git worktree remove --force wt' 'git stash drop' 'git stash clear' \
  'git merge --no-verify feature' 'git commit --no-verify -m x' 'git commit -m "x y" --no-verify' \
  'rtk git push' 'env git push' 'command git push' 'exec git push' 'nohup git push' 'timeout 60 git push' \
  '/usr/bin/git push' 'if git push; then echo ok; fi' '! git push' 'GIT_SSH_COMMAND="ssh -i k" git push origin main' \
  "cd $MAIN && git commit -m x" "cd $MAIN; git add a.ts; git commit -F msg" "cd $MAIN && git push -u origin HEAD" \
  "git -C $MAIN commit -m x" "git -C $MAIN push origin HEAD" "git -C $MAIN merge feat/x" \
  "cd $MAIN/sub && git commit -m x" "cd \"$MAIN/sub dir\" && git commit -m x" \
  'git switch main && git merge --no-ff feat/x' 'git checkout main && git commit -m x' \
  'git switch main; git push origin HEAD' 'cd "$REPO" && git commit -m x' 'git -C "$REPO" commit -m x' \
  'cd - && git commit -m x' 'git switch "$B" && git commit -m x' \
  "cd $TMP/nowhere && git commit -m x" "git -C $TMP/nowhere commit -m x" \
  "if cd $MAIN; then git commit -m x; fi" "cd -P $MAIN && git commit -m x" "cd $MAIN/sub\\ dir && git commit -m x" \
  "pushd $MAIN && git commit -m x" "pushd $MAIN >/dev/null; git push origin HEAD" \
  'git push "--force" origin feat/x' "git push '-f' origin feat/x" 'git reset "--hard" HEAD' \
  'git clean "-fd"' "git branch '-D' x" 'git checkout "-f" main' 'git commit "--amend"' 'git add "-A"' \
  'cat <<EOF'"${NL}"'$(git push origin main)'"${NL}EOF" 'echo "$(git push origin main)"' \
  "echo ${BT}git push origin main${BT}" \
  'git -C "$(git rev-parse --show-toplevel)" push origin main' 'git -C $(pwd) push origin main' \
  'git push origin "$(git branch --show-current):main"' 'X="$(date)" git push origin main' \
  "printf \$'it\\'s ok\\n' && git push origin main && echo 'done'" \
  "git status # check \\${NL}git push origin main" "cat > m <<'EOF'${NL}x \\${NL}EOF${NL}git push origin main" \
  'echo $((x<<y))'"${NL}git push origin main" "(( m = 1 << bit ))${NL}git push origin main" \
  "cat <<E\"OF\"${NL}b${NL}EOF${NL}git push origin main" "echo \"\$(echo '\"')\" && git push origin main && echo 'z'" \
  "git commit -m \"\$(cat <<'EOF'${NL}fix: msg${NL}EOF)\"${NL}git push origin main" \
  "git commit -m \"\$(cat <<'EOF'${NL}fix: msg${NL}EOF)\" && git push origin main" \
  "git status \"\$(cat <<'EOF'${NL}x)\"" '((git push origin main) && echo pushed)' \
  "echo \"\$(case \$b in main) echo '\"';; esac)\" && git push origin main" \
  "(cd $MAIN && case \$x in a) :;; esac && git commit -m x)" \
  'gh pr merge 26' 'gh pr merge 26 --squash' 'gh pr merge 26 --rebase' 'gh pr merge 26 -s' \
  'gh pr merge 26 --merge --admin' 'gh pr merge 26 --auto --merge'; do
  t 2 "$FEAT" "$c"
done

# --- must block on main only: commits and merges land on a branch, never on main.
for c in 'git commit -m x' 'git commit -F msg.txt' 'git commit;' 'x && git commit -m z' 'git merge feature' \
         'git revert HEAD' 'git cherry-pick abc123' 'git -C sub commit -m y' 'git -C "sub dir" commit -m y' \
         'git --no-pager commit -m x' 'git --git-dir=.git commit -m x' "git -c 'user.name=x y' commit" \
         "git \\${NL}commit -m x" "GIT_AUTHOR_NAME='A B' git commit -m x" 'HUSKY=0 git commit -m x' \
         'env git commit -m x' 'for r in a; do git commit -m x; done' '{ git commit -m x; }' \
         'git merge --abort; git commit -m x' 'git switch feat/other && git switch main && git commit -m x' \
         'git push origin HEAD' 'git push -u origin HEAD' 'git push origin @' \
         'git push -u origin "$(git branch --show-current)"' 'git push -u origin $(git branch --show-current)' \
         'git push origin "$BRANCH"' 'git pull --ff-only origin feat/x' 'git pull --ff-only origin feat/x:main' \
         "echo 'it'\\''s' && git commit -m 'x'" \
         "cat > m <<'EOF'${NL}fix: don't drop alerts${NL}EOF${NL}git commit -F m && git push origin main && echo 'ok'" \
         "git status # it's fine${NL}git commit -m 'x'" \
         'git switch feat/other; git switch -; git commit -m x' 'git checkout feat/other a.txt; git commit -m x' \
         "(cd $FEAT && git status); git commit -m x" "pushd $FEAT; popd; git commit -m x" \
         "git push origin ${BT}git branch --show-current${BT}" \
         'git reset feat/other' 'git reset --soft feat/other' \
         'git -C "$(git rev-parse --show-toplevel)" commit -m x' \
         "git switch feat/other${NL}git commit -m x" 'git switch feat/other || true; git push origin HEAD' \
         'git switch feat/other; git commit -m x' 'git checkout -b feat/y; git commit -m x' \
         'case $b in main) git push origin HEAD;; esac'; do
  t 2 "$MAIN" "$c"
done

# --- must pass on a feature branch (exit 0)
for c in 'git commit -m x' 'git commit -F msg.txt' 'git commit;' 'x && git commit -m z' 'git -C . commit -m y' \
         "cat > m <<'EOF'${NL}gh pr merge 1${NL}git push origin main${NL}don't${NL}EOF${NL}git commit -F m" \
         "cat > m <<-EOF${NL}	git push origin main${NL}	EOF${NL}git commit -F m && git push -u origin feat/x" \
         "git commit -m 'x' # then never git push origin main" "echo 'it'\\''s' && git commit -m 'x'" \
         "git push origin ${BT}git branch --show-current${BT}" "pushd $MAIN; popd; git commit -m x" \
         "git commit -m \"\$(cat <<'EOF'${NL}fix: never ${BT}git push origin main${BT}, no (git rebase), no ${BT}git add -A${BT}${NL}EOF${NL})\"" \
         "gh pr create --title t --body \"\$(cat <<'EOF'${NL}Blocks (git rebase) and ${BT}gh pr merge 1 --squash${BT}.${NL}EOF${NL})\"" \
         'git -C "$(git rev-parse --show-toplevel)" status' \
         "git commit -m \"\$(cat <<'EOF'${NL}fix: msg${NL}EOF)\" && git push -u origin feat/x" \
         'echo $((1 + 2)) && git commit -m x' '((n = 1 << 2)) && git commit -m x' \
         'git --no-pager commit -m x' "GIT_AUTHOR_NAME='A B' git commit -m x" "git \\${NL}commit -m x" \
         'git commit -m "docs: never use --no-verify"' 'git commit -m "fix: handle -patch suffix"' \
         'git commit -m "explain --amend and -a; then git push origin main"' \
         "git commit -m \"Never run \\${BT}git pull\\${BT} alone.\"" "git commit -m 'reset --hard is gone'" \
         'gh pr create --title "x" --body "Blocks (git rebase) forms."' 'git -C x rebase --abort' \
         'git add src/a.ts docs/b.md' 'git add ./src/a.ts' 'git add -- src/a.ts' 'git add ./src' \
         'git add src/a.ts && git commit -F msg.txt && git push -u origin feat/x' \
         'git push -u origin feat/x' 'git push origin feat/x' 'git push origin HEAD' 'git push origin @' \
         'git push -u origin "$(git branch --show-current)"' 'git push origin feat/x 2>&1' \
         'git push origin --delete feat/old' 'git push origin feat/main-fix' 'git push --follow-tags origin feat/x' \
         'git push -o ci.skip origin feat/x' 'git push origin feat/x > out.log' \
         'GIT_SSH_COMMAND="ssh -i k" git push origin feat/x' 'timeout 60 git push origin feat/x' \
         'git merge origin/main' 'git merge main' 'git revert HEAD' 'git cherry-pick abc123' \
         'git pull --ff-only' 'git pull --ff-only origin feat/x' 'git branch -m chore/new-name' \
         'git branch -d x; ls -f' 'git reset HEAD file' 'git reset' 'git reset HEAD -- src/a.ts' \
         "gh pr merge 26 --merge $MH" "gh pr merge 26 --merge --delete-branch $MH" 'gh pr view 26' \
         "cd $FEAT && git commit -m x" 'cd sub && git status' \
         'git status' 'git log --oneline' 'git diff' 'grep "git commit" f' 'git checkout -b feat' \
         'git checkout main' 'git restore src/a.ts' 'git stash list' 'git branch -d merged' \
         'echo committed' 'git commit-graph verify' 'grep -- "--no-verify" f' \
         'echo "--no-verify"' 'git log; echo --no-verify' "$(printf 'cat <<EOF\nbloque --no-verify\nEOF')" \
         'git merge-base main HEAD' 'git status; echo done' 'cd a && git status' 'timeout 5 git status' \
         'HUSKY=0 git status' 'git switch main' 'git switch -c new' 'git checkout ./src/a.ts' 'git clean -n' \
         'git branch --delete merged' 'git rev-parse HEAD' 'git show HEAD --stat' \
         'printf "%s\n" "- run git commit/push yourself"' "echo \"use \\${BT}git commit\\${BT} manually\"" \
         'grep -E "(git commit|git push)" CLAUDE.md' 'rg -n "(git push)" docs' \
         'git fetch origin' 'git worktree list' 'git log --merges' \
         'git config --get user.name' 'git diff --cached' \
         'git rebase --abort' 'git merge --abort' 'git cherry-pick --abort' 'git am --quit' 'git revert --quit' \
         'git worktree remove wt' 'grep -E "git (commit|push)" f' 'xargs git log' 'do_it git status' \
         'GIT_PAGER="less -R" git log'; do
  t 0 "$FEAT" "$c"
done

# --- must pass on main: refresh it after a merged PR, start a branch, clean up merged branches,
# work in another checkout that is on a branch.
for c in 'git pull --ff-only' 'git pull --ff-only origin main' 'git switch -c feat/new' 'git checkout -b fix/y' \
         'git switch -c feat/new && git add a.ts && git commit -m x && git push -u origin HEAD' \
         'git switch feat/other && git commit -m x' "git -C $FEAT commit -m x" "cd $FEAT && git commit -m x" \
         "git -C $FEAT push -u origin HEAD" \
         'git status' 'git fetch origin' 'git branch -d feat/merged' 'git push origin --delete feat/merged' \
         'git merge --abort' 'git merge-base main HEAD' 'git log --merges' "gh pr merge 26 --merge --delete-branch $MH" \
         "gh pr merge 26 --merge --subject \"feat(x): y -s --squash (#26)\" $MH" 'git switch feat/rem && git commit -m x' \
         "(cd $FEAT && git commit -m x)" 'git reset' 'git reset HEAD' 'git reset HEAD a.txt' 'git reset feat/other -- a.txt' \
         'git switch -c feat/new 2>&1 && git add a.ts && git commit -m x' \
         'git switch -c feat/new &>/dev/null && git commit -m x' 'git switch -c feat/new >/dev/null 2>&1 && git commit -m x'; do
  t 0 "$MAIN" "$c"
done

# --- Ported from geomni's guardrail (dev-factory 7.1): merging outside the route, automatic merge,
# writing a branch through the API, tracking a protected branch, hooks skipped by `commit -n`,
# moving a ref by hand.
for c in \
  'gh api -X PUT repos/o/r/pulls/12/merge' 'gh api --method PUT repos/o/r/pulls/12/merge' \
  'gh api --method=PUT repos/o/r/pulls/12/merge' 'gh api repos/o/r/pulls/12/merge -X PUT' \
  'gh api /repos/o/r/pulls/12/merge -f merge_method=squash' 'gh api "repos/{owner}/{repo}/pulls/12/merge" -X PUT' \
  'gh api repos/o/r/pulls/12/merge' 'gh api -XPUT repos/o/r/pulls/12/merge' \
  'gh api repos/o/r/merges -f base=main -f head=feat/x' \
  'gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc' 'gh api -X DELETE repos/o/r/git/refs/heads/main' \
  'gh api -X PUT repos/o/r/contents/README.md -f message=x -f content=eA==' \
  "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"P\"}) { clientMutationId } }'" \
  "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"P\"}) { clientMutationId } }'" \
  "gh api graphql -F query='mutation{enqueuePullRequest(input:{pullRequestId:\"P\"}){clientMutationId}}'" \
  'gh pr merge 12 --squash' 'gh pr merge --auto 12' 'gh pr merge 12 --auto --merge' 'gh pr merge 12 --merge --admin' \
  'git branch -u origin/main' 'git branch --set-upstream-to=origin/main' 'git branch --set-upstream-to origin/main' \
  'git branch -u origin/main feat/x' 'git branch -u main' 'git branch -u origin/master' \
  'git branch --set-upstream-to=refs/remotes/origin/main' \
  'git branch --track feat/y origin/main' 'git branch -t feat/y main' 'git branch feat/y origin/main' \
  'git switch -c feat/y origin/main' 'git checkout -b feat/y origin/main' 'git switch -c feat/y --track origin/main' \
  'git switch --track=direct -c feat/y main' 'git checkout -t -b feat/y origin/main' \
  'git worktree add -b feat/y ../wt origin/main' 'git worktree add --track -b feat/y ../wt main' \
  'git push -u origin main' 'git push --set-upstream origin feat/x:main' \
  'git commit -n -m x' 'git commit -nm x' 'git commit -m x -n' \
  'git update-ref refs/heads/main HEAD' 'git update-ref refs/heads/feat/x HEAD~3' 'git update-ref -d refs/heads/feat/old'; do
  t 2 "$FEAT" "$c"
done
for c in \
  'gh api repos/o/r/pulls/12' 'gh api repos/o/r/pulls/12/files' 'gh api repos/o/r/commits/abc/status' \
  'gh api -X POST repos/o/r/statuses/abc -f state=success -f context=review-harness' \
  'gh api -X POST repos/o/r/issues/12/labels -f "labels[]=in-flight"' 'gh api -X DELETE repos/o/r/issues/12/labels/in-flight' \
  'gh api repos/o/r/git/refs/heads/main' 'gh api repos/o/r/contents/README.md' \
  "gh api graphql -f query='query { viewer { login } }'" 'gh pr checks 12 --watch' \
  'gh pr create --base main --title t --body b' \
  'git branch -u origin/feat/x' 'git branch --set-upstream-to=origin/feat/rem' 'git branch --unset-upstream' \
  'git branch --no-track feat/y origin/main' 'git branch feat/y main' 'git branch feat/y' \
  'git switch -c feat/y --no-track origin/main' 'git checkout --no-track -b feat/y origin/main' \
  'git switch -c feat/y main' 'git switch -c feat/y origin/feat/rem' 'git switch --track origin/main' \
  'git worktree add --no-track -b feat/y ../wt origin/main' 'git worktree add -b feat/y ../wt main' \
  'git worktree add ../wt feat/other' 'git branch -m feat/z' 'git commit -m "no -n here"'; do
  t 0 "$FEAT" "$c"
done
# --- Review of lot 3b: the merge-conditions status is never written by the agent; gh api read on its
# own span (a GET with fields is a read); refspecs that write main without naming it; hooks skipped
# through config, HUSKY or an abbreviated option; quoted subcommands; subtree and send-pack.
for c in \
  "gh api -X POST repos/o/r/statuses/$HEAD_SHA -f state=success -f context=merge-conditions -f description=\"gates: none; base b2b2b2b\"" \
  "gh api repos/o/r/statuses/$HEAD_SHA -F context=merge-conditions -f state=success" \
  "gh api repos/o/r/statuses/$HEAD_SHA --raw-field context=merge-conditions -f state=success" \
  "gh api \"repos/{owner}/{repo}/statuses/$HEAD_SHA\" --field 'context=merge-conditions' -f state=success" \
  "gh api repos/o/r/statuses/$HEAD_SHA -f context=\"merge-conditions\" -f state=success" \
  "gh api -X POST repos/o/r/statuses/$HEAD_SHA --input status.json" \
  'gh api --method put repos/o/r/git/refs/heads/main' 'gh api -X patch repos/o/r/contents/README.md' \
  "gh api graphql -f query='mutation { mergeBranch(input: {}) { clientMutationId } }'" \
  "gh api graphql -f query='mutation { createCommitOnBranch(input: {}) { clientMutationId } }'" \
  "gh api graphql -f query='mutation { updateRef(input: {}) { clientMutationId } }'" \
  "gh api graphql -f query='mutation { updateRefs(input: {}) { clientMutationId } }'" \
  'gh api graphql --input q.json' 'gh api graphql -F query=@q.graphql' \
  'git push origin "refs/heads/*:refs/heads/*"' "git push origin 'refs/heads/*'" 'git push origin :' \
  'git push origin feat/x:"$B"' 'git push origin --delete "$B"' 'git push origin "feat/*"' \
  'git push --forc origin feat/x' 'git push --for origin feat/x' 'git push --f origin feat/x' 'git push --force- origin feat/x' \
  'git push --force-w origin feat/x' 'git push --mi origin feat/x' 'git push --al origin feat/x' 'git push --pru origin feat/x' \
  'git -c core.hooksPath=/dev/null commit -m x' 'git -c core.hookspath=x push origin feat/x' \
  'git --config-env=core.hooksPath=X commit -m x' 'HUSKY=0 git commit -m x' 'export HUSKY=0; git push origin feat/x' \
  'HUSKY_SKIP_HOOKS=1 git commit -m x' \
  'git commit --no-verif -m x' 'git commit --no-veri -m x' 'git push --no-verif origin feat/x' \
  'git commit --amen' 'git commit --am -m x' 'git reset --har HEAD' 'git reset --so HEAD' 'git reset --mixe HEAD' \
  'git clean --forc' 'git clean --f -d' 'git checkout --forc feat/other' 'git switch --disc feat/other' \
  'git switch --force-c feat/other' 'git add --al' 'git add --upd' 'git branch --forc x HEAD' \
  'git "push" origin main' "git 'push' origin main" 'gh pr "merge" 26 --merge' \
  'git subtree push --prefix=dist origin main' 'git subtree push -P dist origin main' \
  'git subtree push --prefix dist origin refs/heads/main' 'git subtree push --prefix=dist origin "$B"' \
  'git send-pack origin HEAD:refs/heads/main' 'git send-pack origin feat/x' \
  'git switch --track origin/main && git commit -m x' 'git worktree add -B feat/y ../wt origin/main' \
  'git branch -uorigin/main'; do
  t 2 "$FEAT" "$c"
done
for c in \
  'gh api repos/o/r/contents/README.md --method GET -f ref=feat/x' 'gh api -X GET repos/o/r/git/refs/heads/main -f x=1' \
  'gh api --method get repos/o/r/contents/README.md -f ref=feat/x' \
  'gh api repos/o/r/pulls/12 --jq .title && git commit -m "explain pulls/12/merge"' \
  "gh api -X POST repos/o/r/statuses/$HEAD_SHA -f state=success -f context=opsx-verify -f description=\"ok\"" \
  "gh api repos/o/r/commits/$HEAD_SHA/statuses --jq '.[] | select(.context == \"merge-conditions\")'" \
  'HUSKY=0 git status' 'HUSKY=0 npm test' 'git push --follow-tags origin feat/x' 'git push --fol origin feat/x' \
  'git push --progress origin feat/x' 'git push --atomic origin feat/x' 'git push origin feat/x:feat/y' \
  'git -c core.editor=vim commit -m x' 'git -c user.name=x commit -m x' 'git commit -m "--no-verif is gone"' \
  'git subtree push --prefix=dist origin feat/dist' 'git subtree split --prefix=dist -b feat/dist' \
  'git subtree add --prefix=vendor origin feat/x' 'git "status"' "git 'log' --oneline" \
  'GH_REPO=o/r gh pr view 26' 'gh pr checks 26' 'gh pr edit 26 --add-label in-flight'; do
  t 0 "$FEAT" "$c"
done
# Copying a branch copies its upstream: main tracks origin/main here.
t 2 "$MAIN" 'git branch -c main feat/y'
t 2 "$MAIN" 'git branch -c feat/y'
t 2 "$MAIN" 'git branch --copy main feat/y'
t 0 "$MAIN" 'git branch -c feat/other feat/z'
t 0 "$MAIN" 'git branch -m feat/other feat/z'
t 2 "$MAIN" 'git branch --track=inherit feat/y main'
t 2 "$MAIN" 'git switch -c feat/y --track=inherit main'
t 0 "$MAIN" 'git branch --track=inherit feat/y feat/other'
git -C "$MAIN" branch feat/tracks-main
git -C "$MAIN" config branch.feat/tracks-main.remote origin
git -C "$MAIN" config branch.feat/tracks-main.merge refs/heads/main
t 2 "$MAIN" 'git branch --track=inherit feat/y feat/tracks-main'
t 2 "$MAIN" 'git branch -c feat/tracks-main feat/y'
t 2 "$MAIN" 'git subtree add --prefix=vendor origin feat/x'
t 2 "$MAIN" "git 'commit' -m x"
git init -q -b main "$TMP/simple-autosetup"
git -C "$TMP/simple-autosetup" remote add origin https://example.invalid/o/r.git
git -C "$TMP/simple-autosetup" config branch.autoSetupMerge simple
t 0 "$TMP/simple-autosetup" 'git switch -c feat/y origin/main'
t 2 "$TMP/simple-autosetup" 'git switch -c feat/y --track origin/main'
git init -q -b main "$TMP/inherit-autosetup"
git -C "$TMP/inherit-autosetup" config branch.autoSetupMerge inherit
git -C "$TMP/inherit-autosetup" config branch.main.remote origin
git -C "$TMP/inherit-autosetup" config branch.main.merge refs/heads/main
t 2 "$TMP/inherit-autosetup" 'git switch -c feat/y'
t 0 "$TMP/inherit-autosetup" 'git switch --orphan feat/y'
t 0 "$TMP/inherit-autosetup" 'git switch -c feat/y --no-track'

# On main, restoring main's own upstream is not tracking a protected branch from a change branch.
t 0 "$MAIN" 'git branch -u origin/main'
t 0 "$MAIN" 'git branch --set-upstream-to=origin/main main'
t 2 "$MAIN" 'git branch -u origin/main feat/other'
# The repository's branch.autoSetupMerge decides whether a branch created from main tracks it.
git init -q -b main "$TMP/no-autosetup"
git -C "$TMP/no-autosetup" remote add origin https://example.invalid/o/r.git
git -C "$TMP/no-autosetup" config branch.autoSetupMerge false
t 0 "$TMP/no-autosetup" 'git switch -c feat/y origin/main'
t 2 "$TMP/no-autosetup" 'git switch -c feat/y --track origin/main'
git init -q -b main "$TMP/always-autosetup"
git -C "$TMP/always-autosetup" config branch.autoSetupMerge always
t 2 "$TMP/always-autosetup" 'git switch -c feat/y main'
t 0 "$TMP/always-autosetup" 'git switch -c feat/y feat/other'

# --- The merge route (dev-factory 7.3): `gh pr merge <n> --<MERGE_METHOD> --match-head-commit <sha>`,
# allowed only when GitHub itself reports merge-conditions success with no gate on that head commit,
# posted by its workflow, judged against the default branch's current head, with no other pull
# request in flight, and the command does nothing else that writes. Default method: merge.
# tg <expected> <fixture dir> <command> [text the block message must contain] [cwd] [hook]
tg() {
  local expected="$1" fixtures="$2" cmd="$3" text="${4:-}" dir="${5:-$FEAT}" hook="${6:-$H}" got
  n=$((n+1))
  printf '%s' "$(jq -n --arg c "$cmd" --arg d "$dir" '{cwd:$d, tool_input:{command:$c}}')" \
    | GH_FIXTURES="$fixtures" "$hook" 2>"$TMP/stderr"
  got=$?
  if [ "$got" != "$expected" ]; then
    echo "FAIL merge route [${fixtures##*/}] (got $got, want $expected): $cmd — $(head -c 300 "$TMP/stderr")"; fail=1
  elif [ -n "$text" ] && ! grep -qF -- "$text" "$TMP/stderr"; then
    echo "FAIL merge route [${fixtures##*/}] (message lacks '$text'): $cmd — $(cat "$TMP/stderr")"; fail=1
  fi
}
d=$(fx green)
tg 0 "$d" "gh pr merge 26 --merge $MH"
tg 0 "$d" "gh pr merge 26 --merge --delete-branch $MH"
tg 0 "$d" "gh pr merge 26 -m -d $MH"
tg 0 "$d" "gh pr merge 26 --merge --subject \"feat(x): y (#26)\" --body \"z\" $MH"
tg 0 "$d" "gh pr merge 26 --merge --match-head-commit=$HEAD_SHA"
tg 0 "$d" "gh pr 'merge' 26 \"--merge\" $MH"
tg 0 "$d" "gh pr view 26 --json headRefOid && gh pr merge 26 --merge $MH && gh pr edit 26 --add-label in-flight && git status"
tg 2 "$d" 'gh pr merge 26 --merge' 'match-head-commit <sha>'
tg 2 "$d" "gh pr merge 26 --merge --match-head-commit ${HEAD_SHA:0:12}" 'in full'
tg 2 "$d" 'gh pr merge 26 --merge --match-head-commit "$SHA"' 'match-head-commit <sha>'
tg 2 "$d" "gh pr merge 26 --merge --match-head-commit $OLD_SHA" 'is not the head'
tg 2 "$d" "gh pr merge 26 --merge --match-head-commit=$OLD_SHA" 'is not the head'
tg 2 "$d" "gh pr merge 26 --squash $MH" 'gh pr merge <n> --merge'
tg 2 "$d" "gh pr merge 26 -s $MH" 'gh pr merge <n> --merge'
tg 2 "$d" "gh pr merge 26 --rebase $MH" 'gh pr merge <n> --merge'
tg 2 "$d" "gh pr merge 26 $MH" 'gh pr merge <n> --merge'
tg 2 "$d" "gh pr merge 26 --merge --squash $MH" 'gh pr merge <n> --merge'
tg 2 "$d" "gh pr merge 26 --merge --admin $MH" 'never bypass'
tg 2 "$d" "gh pr merge 26 --merge --auto $MH" 'never bypass'
tg 2 "$d" "gh pr merge --merge $MH" 'number'
tg 2 "$d" "gh pr merge https://github.com/o/r/pull/26 --merge $MH" 'number'
tg 2 "$d" "gh pr merge 26 27 --merge $MH" 'number'
# The repository flag anywhere, the repository or host from the environment.
for c in "gh pr merge 26 --merge --repo o/r $MH" "gh pr merge 26 --merge -R o/r $MH" "gh pr merge 26 --merge -Ro/r $MH" \
         "gh pr merge 26 --merge --repo=o/r $MH" "gh -R o/r pr merge 26 --merge $MH" "gh pr --repo=o/r merge 26 --merge $MH" \
         "gh pr -R o/r merge 26 --merge $MH"; do
  tg 2 "$d" "$c" 'without --repo'
done
for c in "GH_REPO=o/x gh pr merge 26 --merge $MH" "GH_HOST=x.example gh pr merge 26 --merge $MH" \
         "export GH_REPO=o/other && gh pr merge 26 --merge $MH" "env GH_HOST=x gh pr merge 26 --merge $MH"; do
  tg 2 "$d" "$c" 'GH_REPO or GH_HOST'
done
tg 2 "$d" "gh -R o/r pr merge 26 --admin --merge $MH"
tg 2 "$d" "gh pr --admin merge 26 --merge $MH" 'never bypass'
tg 2 "$d" "gh pr --auto merge 26 --merge $MH" 'never bypass'
tg 2 "$d" "gh pr --repo=o/r merge 26 --squash --auto $MH"
tg 2 "$d" "gh pr merge 26 --merge --body-file=b.md --unknown $MH" 'unknown'
tg 0 "$d" 'gh pr merge 26 --disable-auto'
tg 2 "$d" "gh pr merge 26 --disable-auto --merge $MH" 'disable-auto'
tg 2 "$d" "cd $TMP/nowhere && gh pr merge 26 --merge $MH" 'directory'
# The merge runs alone: nothing else in the command writes (verified against GitHub before it runs).
for c in "git add a.ts && git commit -m fix && git push origin feat/x && gh pr merge 26 --merge $MH" \
         "git push origin feat/x; gh pr merge 26 --merge $MH" "gh pr merge 26 --merge $MH && git push origin feat/x" \
         "gh pr merge 26 --merge $MH && git switch main && git pull --ff-only" \
         "gh api -X POST repos/o/r/statuses/$HEAD_SHA -f state=success -f context=opsx-verify && gh pr merge 26 --merge $MH" \
         "gh pr edit 26 --add-label in-flight && gh pr merge 26 --merge $MH" \
         "gh pr merge 26 --merge $MH && gh pr edit 25 --add-label in-flight" \
         "gh pr merge 26 --merge $MH && gh pr edit 26 --remove-label in-flight" \
         "gh pr merge 26 --merge $MH && gh pr close 25"; do
  tg 2 "$d" "$c" 'runs alone'
done
tg 2 "$d" "gh pr merge 25 --merge $MH && gh pr merge 26 --merge $MH" 'one gh pr merge per command'
tg 0 "$d" "gh pr merge 26 --merge $MH && gh api repos/o/r/pulls/26 --jq .merged && git log --oneline -1"
# The queries run in the directory where the command really runs.
d=$(fx where)
tg 0 "$d" "cd $MAIN && gh pr merge 26 --merge $MH"
n=$((n+1))
if ! grep -qF "$MAIN|repo view" "$d/calls.log"; then echo "FAIL merge route: gh repo view did not run in $MAIN"; fail=1; fi
# Gates: the owner merges.
for g in 'gates: intent' 'gates: irreversible' 'gates: intent+irreversible' 'gates: framing' 'gates: unclassified' \
         'gates: invalid'; do
  d=$(fx "gate-${g#gates: }")
  fxset "$d" "$P_STATUS" "$(status_json success "$g; base ${BASE_SHA:0:7}")"
  tg 2 "$d" "gh pr merge 26 --merge $MH" 'hand the merge to the owner'
done
d=$(fx gate-none-reasons)
fxset "$d" "$P_STATUS" "$(status_json success "gates: none - x; base ${BASE_SHA:0:7}")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'hand the merge to the owner'
# The status must come from the workflow: one posted with a person's token is not the check.
d=$(fx forged)
fxset "$d" "$P_STATUS" "$(status_json success "gates: none; base ${BASE_SHA:0:7}" "$HEAD_SHA" agent-owner)"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'not by its workflow'
d=$(fx no-creator)
fxset "$d" "$P_STATUS" "$(status_json success "gates: none; base ${BASE_SHA:0:7}" | jq -c '.[0] |= del(.creator)')"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'not by its workflow'
# The newest merge-conditions status counts, not an older green one.
d=$(fx newest-pending)
fxset "$d" "$P_STATUS" "$(status_json success "gates: none; base ${BASE_SHA:0:7}" | jq -c '[.[0] | .state = "pending" | .description = "re-judging"] + .')"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'pending'
# Stale verdict: the default branch moved since the check judged.
d=$(fx stale)
fxset "$d" "$P_BRANCH" "{\"name\":\"main\",\"commit\":{\"sha\":\"$NEW_BASE_SHA\"}}"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'wait for the re-judgement'
d=$(fx no-base)
fxset "$d" "$P_STATUS" "$(status_json success 'gates: none')"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'base'
# A status on an older commit than the head does not count.
d=$(fx older)
fxset "$d" "$P_STATUS" '[]'
fxset "$d" "repos/o/r/commits/$OLD_SHA/statuses?per_page=100" "$(status_json success "gates: none; base ${BASE_SHA:0:7}" "$OLD_SHA")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'no merge-conditions status'
d=$(fx no-status)
fxset "$d" "$P_STATUS" "$(status_json success x | jq -c 'map(select(.context != "merge-conditions"))')"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'no merge-conditions status'
d=$(fx status-other-sha)
fxset "$d" "$P_STATUS" "$(status_json success "gates: none; base ${BASE_SHA:0:7}" "$OLD_SHA")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
# Not green.
d=$(fx pending); fxset "$d" "$P_STATUS" "$(status_json pending "gates: none - ci.yml running; base ${BASE_SHA:0:7}")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'wait'
d=$(fx failure); fxset "$d" "$P_STATUS" "$(status_json failure "gates: none - ci.yml failure; base ${BASE_SHA:0:7}")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'failure'
d=$(fx error); fxset "$d" "$P_STATUS" "$(status_json error 'merge-conditions could not judge: x')"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'error'
# The pull request itself.
d=$(fx other-base)
fxset "$d" "$P_PR" "{\"number\":26,\"state\":\"open\",\"head\":{\"sha\":\"$HEAD_SHA\"},\"base\":{\"ref\":\"develop\"}}"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'default branch'
d=$(fx closed)
fxset "$d" "$P_PR" "{\"number\":26,\"state\":\"closed\",\"head\":{\"sha\":\"$HEAD_SHA\"},\"base\":{\"ref\":\"main\"}}"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'not open'
# In flight: another pull request carries the label, whatever its state; issues that are not pull
# requests do not count; every page is read.
d=$(fx in-flight)
fxset "$d" "$P_INFLIGHT" '[{"number":12,"state":"closed","pull_request":{"merged_at":"2026-11-13T10:00:00Z"}}]'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'another change is in flight'
d=$(fx in-flight-open)
fxset "$d" "$P_INFLIGHT" '[{"number":30,"state":"open","pull_request":{}},{"number":26,"state":"open","pull_request":{}}]'
tg 2 "$d" "gh pr merge 26 --merge $MH" '#30'
d=$(fx in-flight-page-2)
fxset "$d" "$P_INFLIGHT" '[{"number":5,"state":"open"}]
[{"number":31,"state":"closed","pull_request":{}}]'
tg 2 "$d" "gh pr merge 26 --merge $MH" '#31'
d=$(fx in-flight-self)
fxset "$d" "$P_INFLIGHT" '[{"number":26,"state":"open","pull_request":{}}]'
tg 0 "$d" "gh pr merge 26 --merge $MH"
d=$(fx in-flight-issue)
fxset "$d" "$P_INFLIGHT" '[{"number":5,"state":"open"}]'
tg 0 "$d" "gh pr merge 26 --merge $MH"
# A refused deploy not resolved: an open issue labelled deploy-refused, on any page; closed ones are
# not asked for (the query names state=open, and the stub answers that exact query only).
d=$(fx deploy-refused)
fxset "$d" "$P_REFUSED" '[{"number":40,"state":"open","title":"Deploy refused: abc1234 on main"}]'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'refused deploy is not resolved (#40'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'revert it exactly through a pull request, or have the owner set the reset variable (OPENSPEC_GUIDE §8)'
d=$(fx deploy-refused-page-2)
fxset "$d" "$P_REFUSED" '[]
[{"number":41,"state":"open"}]'
tg 2 "$d" "gh pr merge 26 --merge $MH" '#41'
d=$(fx deploy-refused-not-a-list)
fxset "$d" "$P_REFUSED" '{"message":"Resource not accessible by integration"}'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
d=$(fx deploy-refused-other-query)
fxset "$d" 'repos/o/r/issues?labels=deploy-refused&state=all&per_page=100' '[]'
rm "$d/$(key "$P_REFUSED")"
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
# GitHub unreachable or answering garbage: fail closed.
for p in repo-view "$P_PR" "$P_STATUS" "$P_BRANCH" "$P_INFLIGHT" "$P_REFUSED"; do
  d=$(fx "fails-$(key "$p")"); fxfail "$d" "$p"
  tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
  d=$(fx "garbage-$(key "$p")"); fxset "$d" "$p" 'not json {'
  tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
done
d=$(fx empty-pr); fxset "$d" "$P_PR" '{"number":26,"state":"open"}'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
d=$(fx bad-repo); fxset "$d" repo-view '{"nameWithOwner":"o/r; x","defaultBranchRef":{"name":"main"}}'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
d=$(fx bad-default); fxset "$d" repo-view '{"nameWithOwner":"o/r","defaultBranchRef":{"name":"main; x"}}'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
d=$(fx no-default); fxset "$d" repo-view '{"nameWithOwner":"o/r"}'
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
d=$(fx exit-4); fxfail "$d" "$P_STATUS" 4
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed'
# One deadline for all the queries together, tried on copies of the hook with a short one: a slow
# answer is killed and the merge blocked; two answers that each fit but not together are blocked too.
mkdir -p "$TMP/deadline-2" "$TMP/deadline-3"
for k in 2 3; do
  sed -E "s/^GH_DEADLINE=[0-9]+\$/GH_DEADLINE=$k/" "$SRC" > "$TMP/deadline-$k/block-git-writes.sh"
  chmod +x "$TMP/deadline-$k/block-git-writes.sh"
  cp "$(dirname "$SRC")/block-git-writes.pl" "$TMP/deadline-$k/"
done
d=$(fx slow); fxsleep "$d" "$P_PR" 6
start=$SECONDS
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed' "$FEAT" "$TMP/deadline-2/block-git-writes.sh"
n=$((n+1))
[ $((SECONDS - start)) -le 4 ] || { echo "FAIL merge route: a slow GitHub answer was not cut at the deadline ($((SECONDS - start)) s)"; fail=1; }
d=$(fx slow-sum); fxsleep "$d" "$P_PR" 2; fxsleep "$d" "$P_STATUS" 2
tg 2 "$d" "gh pr merge 26 --merge $MH" 'fail closed' "$FEAT" "$TMP/deadline-3/block-git-writes.sh"
d=$(fx slow-one); fxsleep "$d" "$P_PR" 1
tg 0 "$d" "gh pr merge 26 --merge $MH" '' "$FEAT" "$TMP/deadline-3/block-git-writes.sh"
# The deadline stays well under the hook's timeout in settings.json: a hook that times out does not
# block the call.
n=$((n+1))
deadline=$(sed -nE 's/^GH_DEADLINE=([0-9]+)$/\1/p' "$SRC")
settings="$(dirname "$SRC")/../settings.json"
if [ -f "$settings" ]; then
  timeout=$(jq -r '[.hooks.PreToolUse[]?.hooks[]? | select(.command | test("block-git-writes")) | .timeout] | first // 60' "$settings")
  if [ -z "$deadline" ] || [ $((deadline * 2)) -gt "$timeout" ]; then
    echo "FAIL merge route: GH_DEADLINE ($deadline s) is not well under the hook timeout ($timeout s) in settings.json"; fail=1
  fi
elif [ -z "$deadline" ] || [ "$deadline" -gt 40 ]; then
  echo "FAIL merge route: GH_DEADLINE ($deadline s) above 40 s"; fail=1
fi
# gh missing: only the tools the hook needs are on PATH.
mkdir -p "$TMP/no-gh"
for b in jq perl git grep sed tr cat dirname cut tail head env; do
  p=$(command -v "$b") && ln -s "$p" "$TMP/no-gh/$b"
done
n=$((n+1))
printf '%s' "$(jq -n --arg c "gh pr merge 26 --merge $MH" --arg d "$FEAT" '{cwd:$d, tool_input:{command:$c}}')" \
  | PATH="$TMP/no-gh" "$H" 2>"$TMP/stderr"
got=$?
if [ "$got" != 2 ] || ! grep -qF 'gh not found' "$TMP/stderr"; then echo "FAIL merge route without gh (got $got): $(cat "$TMP/stderr")"; fail=1; fi

# --- block-git-writes.conf: protected branches, push, merge method, force-with-lease (a copy of the
# hook per config).
tc() {
  local expected="$1" conf="$2" dir="$3" cmd="$4" got d
  n=$((n+1))
  d=$(mktemp -d "$TMP/conf.XXXX")
  cp "$SRC" "$(dirname "$SRC")/block-git-writes.pl" "$d/"
  printf '%s\n' "$conf" > "$d/block-git-writes.conf"
  printf '%s' "$(jq -n --arg c "$cmd" --arg e "$dir" '{cwd:$e, tool_input:{command:$c}}')" | "$d/block-git-writes.sh" 2>/dev/null
  got=$?
  if [ "$got" != "$expected" ]; then echo "FAIL with conf [$conf] (got $got, want $expected): $cmd"; fail=1; fi
}
git init -q -b develop "$TMP/on-develop"
tc 2 'PROTECTED_BRANCHES=main|develop' "$TMP/on-develop" 'git commit -m x'
tc 2 'PROTECTED_BRANCHES="main|develop"  # trunk + integration' "$FEAT" 'git push origin develop'
tc 0 'PROTECTED_BRANCHES=main' "$TMP/on-develop" 'git commit -m x'
tc 2 'PROTECTED_BRANCHES=$(rm -rf x)' "$MAIN" 'git commit -m x'
tc 2 'PROTECTED_BRANCHES=main|develop' "$FEAT" 'git switch -c feat/y origin/develop'
tc 2 'ALLOW_PUSH=0' "$FEAT" 'git push -u origin feat/x'
tc 0 'ALLOW_PUSH=0' "$FEAT" 'git commit -m x'
tc 0 'ALLOW_PUSH=1' "$FEAT" 'git push -u origin feat/x'
tc 0 'MERGE_METHOD=squash' "$FEAT" "gh pr merge 26 --squash $MH"
tc 0 'MERGE_METHOD=squash' "$FEAT" "gh pr merge 26 -s --delete-branch $MH"
tc 2 'MERGE_METHOD=squash' "$FEAT" "gh pr merge 26 --merge $MH"
tc 2 'MERGE_METHOD=squash' "$FEAT" "gh pr merge 26 --rebase $MH"
tc 0 'MERGE_METHOD=merge' "$FEAT" "gh pr merge 26 --merge $MH"
tc 2 'MERGE_METHOD=merge' "$FEAT" "gh pr merge 26 --squash $MH"
tc 0 'MERGE_METHOD="squash"  # one commit per change' "$FEAT" "gh pr merge 26 --squash $MH"
tc 2 'MERGE_METHOD=rebase' "$FEAT" "gh pr merge 26 --rebase $MH"
tc 2 'MERGE_METHOD=rebase' "$FEAT" "gh pr merge 26 --merge $MH"
tc 2 'MERGE_METHOD=fast' "$FEAT" "gh pr merge 26 --merge $MH"
d=$(fx gate-squash)
fxset "$d" "$P_STATUS" "$(status_json success "gates: intent; base ${BASE_SHA:0:7}")"
GH_FIXTURES=$d tc 2 'MERGE_METHOD=squash' "$FEAT" "gh pr merge 26 --squash $MH"
# A former setting no longer changes anything: the route decides, per pull request.
tc 0 'ALLOW_PR_MERGE=0' "$FEAT" "gh pr merge 26 --merge $MH"
GH_FIXTURES=$d tc 2 'ALLOW_PR_MERGE=1' "$FEAT" "gh pr merge 26 --merge $MH"
for lease in 0 1; do
  tc "$((2 - 2 * lease))" "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease origin feat/x'
  tc "$((2 - 2 * lease))" "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease=feat/x:abc123 origin feat/x'
  tc "$((2 - 2 * lease))" "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease --force-if-includes origin HEAD'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease origin main'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease origin feat/x:main'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$MAIN" 'git push --force-with-lease origin HEAD'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease -f origin feat/x'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease origin +feat/x'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force origin feat/x'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-if-includes origin feat/x'
  tc 2 "ALLOW_FORCE_WITH_LEASE=$lease" "$FEAT" 'git push --force-with-lease origin'
done

# --- without jq: git and gh commands are blocked, anything else passes.
mkdir -p "$TMP/bin"
for b in cat grep; do ln -s "$(command -v "$b")" "$TMP/bin/$b"; done
tj() {
  local expected="$1" cmd="$2" got
  n=$((n+1))
  printf '{"cwd":"%s","tool_input":{"command":"%s"}}' "$FEAT" "$cmd" | PATH="$TMP/bin" /bin/bash "$H" 2>/dev/null
  got=$?
  if [ "$got" != "$expected" ]; then echo "FAIL without jq (got $got, want $expected): $cmd"; fail=1; fi
}
tj 2 'git commit -m x'
tj 2 'gh pr merge 26 --merge'
tj 2 'ls\ngit push origin main'
tj 0 'ls -la'

[ "$fail" = 0 ] && echo "ALL $n CASES OK"
exit "$fail"
