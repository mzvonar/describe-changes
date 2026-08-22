#!/usr/bin/env bash
# collect-diff.sh — deterministic step 1 of describe-changes.
# Resolves WHAT to describe (a git range or the working tree), dumps the raw diff with
# rename/copy detection, and runs classify-diff.py to produce the noise-stripped model.
#
# Usage:
#   collect-diff.sh [--out <dir>] [--base <ref>] [--committed-only] [<git diff args...>]
#   collect-diff.sh --check <out-dir>        # exit 3 (+ list) if the tree moved since that snapshot
#
# Range resolution (when no git diff args are given):
#   - on a non-default branch:  merge-base(<base>, HEAD) → WORKING TREE, i.e. every commit on the
#                               branch PLUS staged, unstaged and untracked changes (--committed-only
#                               stops at HEAD)
#   - on the default branch:    working tree vs HEAD (staged + unstaged + untracked)
#   <base> defaults to the repo's default branch (origin/HEAD → main → master).
#   meta.json records commits, uncommitted files and a fingerprint of the tree so a later --check
#   can tell whether the report still describes what is on disk.
#
# Writes into <out> (default: <repo>/.describe-changes/<slug>/):
#   raw.diff          full unified diff (-M -C, 3 lines of context, function headers)
#   numstat.txt       git --numstat
#   commits.txt       commit subjects in range (empty for working-tree mode)
#   meta.json         repo, branch, range label, base sha, head sha, timestamp
#   diff-model.json   output of classify-diff.py (files, hunks, folds, stats)
#   substantive.diff  only the hunks a human may need to read
# Prints the out dir on the last line: OUT=<dir>

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
die() { echo "ERROR: $*" >&2; exit 1; }

OUT=""; BASE=""; ARGS=(); COMMITTED_ONLY=0; CHECK=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --out)  OUT="${2:?--out needs a value}"; shift 2 ;;
    --base) BASE="${2:?--base needs a value}"; shift 2 ;;
    --committed-only) COMMITTED_ONLY=1; shift ;;
    --check) CHECK="${2:?--check needs the report dir}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
cd "$ROOT"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached)"
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || echo none)"

# Fingerprint of "what is on disk": HEAD + porcelain status + per-file hashes of dirty/untracked files.
fingerprint() {
  # NB: every grep here may match nothing (clean tree) — never let that exit status reach set -e/pipefail.
  { echo "$HEAD_SHA"; { git status --porcelain=v1 --untracked-files=all 2>/dev/null | grep -v ' \.describe-changes/' || true; } \
      | while IFS= read -r l; do f="${l:3}"; f="${f#* -> }"; printf '%s ' "$l"; { [ -f "$f" ] && git hash-object "$f"; } || echo dir; done; } | shasum | cut -c1-16
}

if [ -n "$CHECK" ]; then
  [ -f "$CHECK/meta.json" ] || die "no meta.json in $CHECK"
  OLD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("fingerprint",""))' "$CHECK/meta.json")"
  NEW="$(fingerprint)"
  if [ "$OLD" = "$NEW" ]; then echo "tree unchanged since snapshot ($NEW)"; exit 0; fi
  echo "TREE MOVED since the snapshot was taken (was $OLD, now $NEW). Changed vs snapshot HEAD $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("head_sha","")[:7])' "$CHECK/meta.json"):"
  OLD_HEAD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("head_sha",""))' "$CHECK/meta.json")"
  git diff --name-status "$OLD_HEAD" 2>/dev/null | sed 's/^/  /' | head -40
  { git ls-files --others --exclude-standard | grep -v '^\.describe-changes/' || true; } | sed 's/^/  ?? /' | head -20
  echo "Re-run collect-diff.sh and refresh the report before answering."
  exit 3
fi

default_branch() {
  local ref
  ref="$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$ref" ]; then echo "${ref#origin/}"; return; fi
  for c in main master develop; do
    git show-ref -q --verify "refs/heads/$c" && { echo "$c"; return; }
  done
  echo main
}
[ -n "$BASE" ] || BASE="$(default_branch)"

MODE=""; LABEL=""; BASE_SHA=""
COMMON_FLAGS=(-M50% -C50% --no-color --no-ext-diff --unified=3)

if [ "${#ARGS[@]}" -gt 0 ]; then
  MODE="explicit"; LABEL="git diff ${ARGS[*]}"
  RAW="$(git diff "${COMMON_FLAGS[@]}" "${ARGS[@]}")"
  NUMSTAT="$(git diff --numstat -M50% "${ARGS[@]}")"
  COMMITS=""
elif [ "$BRANCH" != "$BASE" ] && [ "$BRANCH" != "detached" ] && git rev-parse -q --verify "$BASE" >/dev/null; then
  MODE="branch"
  BASE_SHA="$(git merge-base "$BASE" HEAD)"
  if [ "$COMMITTED_ONLY" = 1 ]; then
    LABEL="$BASE..$BRANCH (committed only)"
    RAW="$(git diff "${COMMON_FLAGS[@]}" "$BASE_SHA" HEAD)"
    NUMSTAT="$(git diff --numstat -M50% "$BASE_SHA" HEAD)"
  else
    LABEL="$BASE..$BRANCH + working tree"
    RAW="$(git diff "${COMMON_FLAGS[@]}" "$BASE_SHA")"
    NUMSTAT="$(git diff --numstat -M50% "$BASE_SHA")"
  fi
  COMMITS="$(git log --reverse --format='%h %s' "$BASE_SHA..HEAD")"
else
  MODE="worktree"; LABEL="working tree vs HEAD"
  RAW="$(git diff "${COMMON_FLAGS[@]}" HEAD 2>/dev/null || git diff "${COMMON_FLAGS[@]}")"
  NUMSTAT="$(git diff --numstat -M50% HEAD 2>/dev/null || true)"
  COMMITS=""
fi

# Untracked files count as additions in branch/worktree modes.
if [ "$MODE" != "explicit" ] && [ "$COMMITTED_ONLY" != 1 ]; then
  while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$f" ] || continue
    RAW="${RAW}"$'\n'"$(git diff --no-color --no-index /dev/null "$f" 2>/dev/null || true)"
    NUMSTAT="${NUMSTAT}"$'\n'"$(wc -l < "$f" | tr -d ' ')	0	$f"
  done < <(git ls-files --others --exclude-standard | grep -v '^\.describe-changes/' || true)
fi

if [[ "$RAW" != *"diff --git "* ]]; then   # no pipe: grep -q + pipefail = SIGPIPE on big diffs
  echo "Nothing to describe: no changes for '$LABEL'." >&2
  exit 2
fi

if [ -z "$OUT" ]; then
  SLUG="$(printf '%s' "$BRANCH" | tr -c 'A-Za-z0-9._-' '-' | sed 's/^-*//;s/-*$//')"
  [ -n "$SLUG" ] || SLUG="changes"
  OUT="$ROOT/.describe-changes/$SLUG"
fi
mkdir -p "$OUT"
printf '%s\n' "$RAW" > "$OUT/raw.diff"
printf '%s\n' "$NUMSTAT" | sed '/^$/d' > "$OUT/numstat.txt"
printf '%s\n' "$COMMITS" | sed '/^$/d' > "$OUT/commits.txt"

UNCOMMITTED="$( { git status --porcelain=v1 --untracked-files=all 2>/dev/null || true; } | grep -v ' \.describe-changes/' || true)"
[ "$COMMITTED_ONLY" = 1 ] && UNCOMMITTED=""
FP="$(fingerprint)"
UNCOMMITTED="$UNCOMMITTED" python3 - "$OUT/meta.json" "$ROOT" "$BRANCH" "$BASE" "$BASE_SHA" "$HEAD_SHA" "$MODE" "$LABEL" "$FP" "$COMMITTED_ONLY" <<'PY'
import json, sys, datetime, os
p, root, branch, base, base_sha, head, mode, label, fp, committed_only = sys.argv[1:]
unc = [l for l in os.environ.get("UNCOMMITTED", "").splitlines() if l.strip()]
commits = [l for l in open(os.path.join(os.path.dirname(p), "commits.txt")).read().splitlines() if l.strip()]
json.dump({
  "repo": root.rstrip("/").split("/")[-1], "root": root, "branch": branch, "base": base,
  "base_sha": base_sha, "head_sha": head, "mode": mode, "range_label": label,
  "commits": len(commits), "committed_only": committed_only == "1",
  "uncommitted_files": [{"status": l[:2].strip() or "??", "path": l[3:].split(" -> ")[-1]} for l in unc],
  "fingerprint": fp,
  "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
}, open(p, "w"), indent=2)
PY

python3 "$HERE/classify-diff.py" --diff "$OUT/raw.diff" --numstat "$OUT/numstat.txt" --out "$OUT"

echo "OUT=$OUT"
