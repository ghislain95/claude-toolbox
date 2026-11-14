#!/usr/bin/env bash
# deploy-guard.sh — the deploy guard of the spec-driven workflow, the server-side barrier: a commit of
# the default branch deploys only when it, and every first-parent commit since the last deployed one,
# is the merge of a pull request that meets the merge conditions, recomputed here
# (`merge_conditions.py deploy-guard`), never read from the `merge-conditions` status. It does not
# enforce the owner's gates: an owner merge and an agent merge look the same to it.
#
# This script and the merge_conditions.py it runs are read from a TRUSTED commit — the target's last
# deployed commit, else the default branch before the push — never from the pushed one, so a merge
# cannot rewrite the guard that judges it. The entry point (the deploy workflow's step, Vercel's
# ignoreCommand) extracts this file from that commit and passes the commit on.
#
#   deploy-guard.sh <merged-sha> <before-sha> <trusted-sha>
#       A GitHub Actions deploy job and the deploy-alert workflow. Exit 0 = deploy; 1 = refused, 2 =
#       cannot judge, 4 = the adoption merge (refused, expected): the step fails, nothing after it
#       runs. <trusted-sha> is the last commit this workflow ran successfully on (judged since then).
#       A manual run (workflow_dispatch, GITHUB_EVENT_NAME) passes an empty <before-sha>: it must
#       run on the default branch (GITHUB_REF), and its commit's first parent stands for `before`.
#
#   deploy-guard.sh --vercel [<glob>...]
#       Vercel's `ignoreCommand`, whose convention is inverted: exit 1 = build, exit 0 = skip. The
#       trusted commit is VERCEL_GIT_PREVIOUS_SHA (the last production deployment). A build that is
#       not explicitly a preview (VERCEL_ENV=preview) is guarded: it exits 1 only when the guard
#       says deploy and a path matching one of the globs changed since that deployment (every path
#       when none is given), and 0 in every other case. The ignoreCommand turns any other exit code
#       (a missing file, a crash) into a skip too. Previews never reach production: they build.
#
# Repository: GITHUB_REPOSITORY, or VERCEL_GIT_REPO_OWNER/VERCEL_GIT_REPO_SLUG. Commit (Vercel):
# VERCEL_GIT_COMMIT_SHA. Token, read-only (Contents, Pull requests, Actions, Metadata):
# DEPLOY_GUARD_TOKEN, GH_TOKEN or GITHUB_TOKEN. Verdict as JSON in DEPLOY_GUARD_VERDICT when set.
# DEPLOY_GUARD_TARGET (a target of the trusted commit's .sdd/deployment.yaml): only the commits that
# change its trigger paths are judged, so a refused commit elsewhere does not block it.
# Needs git and python3; without PyYAML, a fresh virtual environment (mktemp -d) gets PyYAML 6.0.2,
# hash-pinned (CPython 3.9-3.13, Linux or macOS; anything else cannot judge). DEPLOY_GUARD_PYTHON
# overrides the interpreter. Copied verbatim by sdd-init; tests: .sdd/bin/test_merge_conditions.py
# (DeployGuardScriptTest).
set -u

python=${DEPLOY_GUARD_PYTHON:-python3}
token=${DEPLOY_GUARD_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN:-}}}
api=${GITHUB_API_URL:-https://api.github.com}
repository=${GITHUB_REPOSITORY:-}
if [ -z "$repository" ] && [ -n "${VERCEL_GIT_REPO_OWNER:-}" ] && [ -n "${VERCEL_GIT_REPO_SLUG:-}" ]; then
  repository="$VERCEL_GIT_REPO_OWNER/$VERCEL_GIT_REPO_SLUG"
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/sdd-deploy-guard.XXXXXX") || { echo "deploy-guard: cannot judge: no temporary directory"; exit 2; }
trap 'rm -rf "$work"' EXIT

# trusted_guard <commit>: merge_conditions.py of <commit> into $work, from git, else from GitHub's
# contents API (a shallow clone may not hold the commit). Returns 4 when the commit has no guard.
trusted_guard() {
  local commit=$1 file=.sdd/bin/merge_conditions.py
  if git -C "$top" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$top" cat-file -e "$commit:$file" 2>/dev/null || return 4
    git -C "$top" show "$commit:$file" > "$work/merge_conditions.py"
    return
  fi
  curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/vnd.github.raw" \
    -o "$work/merge_conditions.py" "$api/repos/$repository/contents/$file?ref=$commit"
}

# Runs `merge_conditions.py deploy-guard <arguments>` from the trusted commit: prints its one line,
# returns its exit code (0 deploy, 1 refused, 2 cannot judge, 3 nothing under the globs, 4 adoption).
guard() {
  local trusted=$1 code
  shift
  if [ -z "$repository" ]; then
    echo "deploy-guard: cannot judge: repository unknown (GITHUB_REPOSITORY or VERCEL_GIT_REPO_OWNER/SLUG)"
    return 2
  fi
  if ! top=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "deploy-guard: cannot judge: $PWD is not inside a git repository"
    return 2
  fi
  trusted_guard "$trusted"
  code=$?
  if [ "$code" = 4 ]; then
    echo "deploy-guard: adoption: the trusted commit ${trusted:0:7} has no deploy guard yet, so nothing is deployed until one is in place"
    return 4
  elif [ "$code" != 0 ]; then
    echo "deploy-guard: cannot judge: merge_conditions.py of the trusted commit ${trusted:0:7} is unavailable"
    return 2
  fi
  if ! "$python" -c 'import yaml' >/dev/null 2>&1; then
    cat > "$work/requirements.txt" <<'REQUIREMENTS'
pyyaml==6.0.2 \
--hash=sha256:0a9a2848a5b7feac301353437eb7d5957887edbf81d56e903999a75a3d743086 \
    --hash=sha256:29717114e51c84ddfba879543fb232a6ed60086602313ca38cce623c1d62cfbf \
    --hash=sha256:8824b5a04a04a047e72eea5cec3bc266db09e35de6bdfe34c9436ac5ee27d237 \
    --hash=sha256:ec031d5d2feb36d1d1a24380e4db6d43695f3748343d99434e6f5f9156aaa2ed \
    --hash=sha256:936d68689298c36b53b29f23c6dbb74de12b4ac12ca6cfe0e047bedceea56180 \
    --hash=sha256:23502f431948090f597378482b4812b0caae32c22213aecf3b55325e049a6c68 \
    --hash=sha256:cc1c1159b3d456576af7a3e4d1ba7e6924cb39de8f67111c735f6fc832082774 \
    --hash=sha256:1e2120ef853f59c7419231f3bf4e7021f1b936f6ebd222406c3b60212205d2ee \
    --hash=sha256:5d225db5a45f21e78dd9358e58a98702a0302f2659a3c6cd320564b75b86f47c \
    --hash=sha256:3ad2a3decf9aaba3d29c8f537ac4b243e36bef957511b4766cb0057d32b0be85 \
    --hash=sha256:ff3824dc5261f50c9b0dfb3be22b4567a6f938ccce4587b38952d85fd9e9afe4 \
    --hash=sha256:797b4f722ffa07cc8d62053e4cff1486fa6dc094105d13fea7b1de7d8bf71c9e \
    --hash=sha256:c70c95198c015b85feafc136515252a261a84561b7b1d51e3384e0655ddf25ab \
    --hash=sha256:ce826d6ef20b1bc864f0a68340c8b3287705cae2f8b4b1d932177dcc76721725 \
    --hash=sha256:1f71ea527786de97d1a0cc0eacd1defc0985dcf6b3f17bb77dcfc8c34bec4dc5 \
    --hash=sha256:80bab7bfc629882493af4aa31a4cfa43a4c57c83813253626916b8c7ada83476 \
    --hash=sha256:0833f8694549e586547b576dcfaba4a6b55b9e96098b36cdc7ebefe667dfed48 \
    --hash=sha256:8b9c7197f7cb2738065c481a0461e50ad02f18c78cd75775628afb4d7137fb3b \
    --hash=sha256:efdca5630322a10774e8e98e1af481aad470dd62c3170801852d752aa7a783ba \
    --hash=sha256:50187695423ffe49e2deacb8cd10510bc361faac997de9efef88badc3bb9e2d1 \
    --hash=sha256:0ffe8360bab4910ef1b9e87fb812d8bc0a308b0d0eef8c8f44e0254ab3b07133 \
    --hash=sha256:70b189594dbe54f75ab3a1acec5f1e3faa7e8cf2f1e08d9b561cb41b845f69d5 \
    --hash=sha256:41e4e3953a79407c794916fa277a82531dd93aad34e29c2a514c2c0c5fe971cc \
    --hash=sha256:68ccc6023a3400877818152ad9a1033e3db8625d899c72eacb5a668902e4d652 \
    --hash=sha256:688ba32a1cffef67fd2e9398a2efebaea461578b0923624778664cc1c914db5d \
    --hash=sha256:a8786accb172bd8afb8be14490a16625cbc387036876ab6ba70912730faf8e1f \
    --hash=sha256:d8e03406cac8513435335dbab54c0d385e4a49e4945d2909a581c83647ca0290 \
    --hash=sha256:3b1fdb9dc17f5a7677423d508ab4f243a726dea51fa5e70992e59a7411c89d19 \
    --hash=sha256:0b69e4ce7a131fe56b7e4d770c67429700908fc0752af059838b1cfb41960e4e \
    --hash=sha256:a9f8c2e67970f13b16084e04f134610fd1d374bf477b17ec1599185cf611d725
REQUIREMENTS
    if ! { "$python" -m venv "$work/venv" >/dev/null 2>&1 \
           && "$work/venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-deps \
                --only-binary :all: --require-hashes -r "$work/requirements.txt" >/dev/null 2>&1; }; then
      echo "deploy-guard: cannot judge: PyYAML is missing and could not be installed (hash-pinned wheels)"
      return 2
    fi
    python="$work/venv/bin/python"
  fi
  set -- --repo "$repository" "$@"
  [ -n "${DEPLOY_GUARD_TARGET:-}" ] && set -- "$@" --target "$DEPLOY_GUARD_TARGET"
  [ -n "${DEPLOY_GUARD_VERDICT:-}" ] && set -- "$@" --verdict-file "$DEPLOY_GUARD_VERDICT"
  "$python" "$work/merge_conditions.py" -C "$top" deploy-guard "$@"
}

if [ "${1:-}" = "--vercel" ]; then
  shift
  if [ "${VERCEL_ENV:-}" = "preview" ]; then
    echo "deploy-guard: preview build, not guarded (it never reaches production): build"
    exit 1
  fi
  if [ -z "${VERCEL_GIT_COMMIT_SHA:-}" ] || [ -z "${VERCEL_GIT_PREVIOUS_SHA:-}" ]; then
    echo "deploy-guard: cannot judge: VERCEL_GIT_COMMIT_SHA or VERCEL_GIT_PREVIOUS_SHA is not set (first production deployment, or system environment variables not exposed): skip"
    exit 0
  fi
  arguments=(--sha "$VERCEL_GIT_COMMIT_SHA" --last-deployed "$VERCEL_GIT_PREVIOUS_SHA")
  [ $# -gt 0 ] && arguments+=(--paths "$@")
  guard "$VERCEL_GIT_PREVIOUS_SHA" "${arguments[@]}"
  code=$?
  if [ "$code" -eq 0 ]; then
    echo "deploy-guard: Vercel: build"
    exit 1
  fi
  echo "deploy-guard: Vercel: skip (guard exit $code)"
  exit 0
fi

if [ $# -ne 3 ] || [ -z "$1" ] || [ -z "$3" ]; then
  echo "usage: deploy-guard.sh <merged-sha> <before-sha> <trusted-sha> | deploy-guard.sh --vercel [<glob>...]" >&2
  exit 2
fi
merged=$1 before=$2 trusted=$3
arguments=(--sha "$merged" --last-deployed "$trusted")
if [ -z "$before" ]; then
  if [ "${GITHUB_EVENT_NAME:-}" != "workflow_dispatch" ]; then
    echo "usage: <before-sha> is empty only for a manual run (workflow_dispatch)" >&2
    exit 2
  fi
  if ! before=$(git rev-parse --verify --quiet "$merged^1"); then
    echo "deploy-guard: cannot judge: $merged has no parent here"
    exit 2
  fi
  arguments+=(--ref "${GITHUB_REF:-}")
fi
arguments+=(--before "$before")
guard "$trusted" "${arguments[@]}"
code=$?
[ "$code" -eq 0 ] && exit 0
[ "$code" -eq 3 ] && exit 1   # never "nothing to deploy" here: no globs are passed in this mode
exit "$code"
