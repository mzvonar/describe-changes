#!/usr/bin/env bash
# sync-skill.sh — keep the describe-changes skill in sync between this repo and the repos that use it.
#
# Forward (this repo → consumer), the normal flow. A COMMITTED copy lands in
# <consumer>/.claude/skills/describe-changes plus <consumer>/.claude/skills/.describe-changes-version:
#   ./sync-skill.sh <consumer-repo>                 # pinned to --ref main (git archive; needs a commit)
#   ./sync-skill.sh <consumer-repo> --ref <ref>     # any branch/tag/sha
#   ./sync-skill.sh <consumer-repo> --worktree      # copy the CURRENT working tree (uncommitted edits ok);
#                                                   # version file records sha=<head>-dirty
#
# Backward (consumer → this repo), when you edited the vendored copy in place while using it:
#   ./sync-skill.sh --from <consumer-repo>          # copies consumer's .claude/skills/describe-changes
#                                                   # over skills/describe-changes here; review + commit here,
#                                                   # then forward-sync every consumer again.
#
# Both directions are all-or-nothing (staged in a temp dir first). Requires git, tar, rsync.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL=describe-changes
die() { echo "ERROR: $*" >&2; exit 1; }

CONSUMER=""; REF="main"; MODE="archive"; FROM=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)      REF="${2:?--ref needs a value}"; shift 2 ;;
    --worktree) MODE="worktree"; shift ;;
    --from)     FROM="${2:?--from needs a path}"; shift 2 ;;
    -h|--help)  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         die "unknown flag '$1'" ;;
    *)          [ -z "$CONSUMER" ] || die "unexpected extra arg '$1'"; CONSUMER="$1"; shift ;;
  esac
done

# ---------------------------------------------------------------- backward
if [ -n "$FROM" ]; then
  [ -d "$FROM/.claude/skills/$SKILL" ] || die "no vendored copy at $FROM/.claude/skills/$SKILL"
  SRC="$(cd "$FROM/.claude/skills/$SKILL" && pwd)"
  [ -f "$SRC/SKILL.md" ] || die "$SRC has no SKILL.md — refusing"
  rsync -a --delete --exclude '__pycache__' "$SRC/" "$REPO/skills/$SKILL/"
  echo "Pulled $SRC → $REPO/skills/$SKILL"
  git -C "$REPO" status --short -- "skills/$SKILL" || true
  echo "Review the diff above, commit here, then run ./sync-skill.sh <consumer> for every consumer."
  exit 0
fi

# ---------------------------------------------------------------- forward
[ -n "$CONSUMER" ] || die "usage: sync-skill.sh <consumer-repo> [--ref <ref> | --worktree]   |   sync-skill.sh --from <consumer-repo>"
[ -d "$CONSUMER" ] || die "consumer path not found: $CONSUMER"
CONSUMER="$(cd "$CONSUMER" && pwd)"
[ "$CONSUMER" != "$REPO" ] || die "consumer is this repo"
ORIGIN="$(git -C "$REPO" remote get-url origin 2>/dev/null || echo unknown)"
DEST="$CONSUMER/.claude/skills"; mkdir -p "$DEST"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT

if [ "$MODE" = "worktree" ]; then
  SHA="$(git -C "$REPO" rev-parse -q --verify "HEAD^{commit}" 2>/dev/null || true)"; [ -n "$SHA" ] || SHA="uncommitted"
  DIRTY=""; git -C "$REPO" diff --quiet HEAD -- "skills/$SKILL" 2>/dev/null || DIRTY="-dirty"
  [ -n "$(git -C "$REPO" ls-files --others --exclude-standard "skills/$SKILL")" ] && DIRTY="-dirty"
  mkdir -p "$STAGE/skills"; rsync -a --exclude '__pycache__' "$REPO/skills/$SKILL/" "$STAGE/skills/$SKILL/"
  REF="worktree"; SHA="${SHA}${DIRTY}"
else
  SHA="$(git -C "$REPO" rev-parse --verify "${REF}^{commit}" 2>/dev/null)" || die "ref '$REF' not found in $REPO (commit first, or use --worktree)"
  git -C "$REPO" archive "$SHA" "skills/$SKILL" | tar -x -C "$STAGE"
fi
[ -f "$STAGE/skills/$SKILL/SKILL.md" ] || die "staged copy has no SKILL.md — aborting, no changes made"

rm -rf "$DEST/$SKILL"; mv "$STAGE/skills/$SKILL" "$DEST/$SKILL"
cat > "$DEST/.describe-changes-version" <<V
# describe-changes vendored copy — managed by sync-skill.sh. DO NOT edit by hand.
# Re-sync:  <describe-changes>/sync-skill.sh <this-repo> [--ref <ref> | --worktree]
# Pull edits made here back upstream:  <describe-changes>/sync-skill.sh --from <this-repo>
sha=$SHA
ref=$REF
origin=$ORIGIN
skills=$SKILL
V
SHORT="${SHA:0:7}"
echo "Vendored $SKILL @ $SHORT ($REF) into $DEST/$SKILL"
echo "Wrote $DEST/.describe-changes-version"
grep -q '^\.describe-changes/$' "$CONSUMER/.gitignore" 2>/dev/null || echo "Tip: add '.describe-changes/' to $CONSUMER/.gitignore (report + feedback output dir)."
echo "Next in $CONSUMER: review the diff, then commit .claude/skills/$SKILL + .claude/skills/.describe-changes-version."
