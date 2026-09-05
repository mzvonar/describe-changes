# describe-changes — present a change for honest human review

A Claude Code skill for the moment *after* an agent implemented a task and *before* a human signs it
off. It does not review code for you (CodeRabbit, `/code-review` and friends do that). It makes the
human's review fast, focused and honest:

```
diff in → fold the noise → phases + visual map → the ~3 things a human must verify → Q&A → feedback → sharper skill
```

- **What was done and why** — summary judged against the task's intent, plus the author's confession
  (the spots the agent was unsure about).
- **How it was built** — 2–6 phases in dependency order, not file order.
- **Map of the change** — mermaid graph: who calls whom, where data flows, what was moved / split /
  renamed (colour-coded by change kind).
- **What a human must check** — critical (≤ 3, hard cap) / medium / low cards, each a *question the
  reviewer can answer* with the code snippet one tap away. Over-flagging is treated as the cardinal
  sin: credibility is the only currency.
- **Folded as noise** — pure renames with their import rewrites nested under them, moves, splits,
  whitespace/format-only hunks, comment-only hunks, lockfiles, generated files, snapshots.
- **Everything else** — the honest list of substantive files that got no flag, each with a ⚑ gut-flag
  button ("something feels off here — dig in").

Rendered twice: a short chat view (the map's top label) and a **mobile-first HTML report** (cards,
collapsible, filterable by severity/tag, copyable `file:line`, feedback buttons). The skill then stays
in Q&A mode, and every question, ▲▼✕ vote, note and gut-flag is recorded so the skill can be
recalibrated — locally by default, team-wide via a pluggable backend.

Design source: `run-story/_bmad-output/brainstorming/brainstorming-session-2026-05-26-2117.md` and
`review-tool-elevator-pitch.md` (ownership-transfer north star, attention budget, credibility
constraint, human-points/AI-investigates, divergence scoring).

## Layout

```
skills/describe-changes/
  SKILL.md                  the procedure (what the model does, step by step)
  VERSION
  reference/analysis-guide.md   severity rules, credibility budget, tags, divergence lens
  reference/report-schema.md    report.json — the LLM ↔ renderer contract
  reference/learning-loop.md    feedback channels, local/shared store, maintainer workflow
  scripts/collect-diff.sh       range resolution → raw.diff, numstat, commits, meta.json, then ↓
  scripts/classify-diff.py      deterministic noise pass → diff-model.json + substantive.diff
  scripts/check-report.py       validates report.json (budget, ids, file refs, graph)
  scripts/render-report.py      report.json → index.html (mobile-first, mermaid map, snippets)
  scripts/serve.py              HTTP server (LAN + Tailscale URLs) + POST /feedback capture
  scripts/feedback.py           lessons store: ingest / question / outcome / push / digest / export
  assets/template.html          CSS + JS shell (collapse, filter, feedback, mermaid loader)
sync-skill.sh                   vendor into consumer repos (forward) / pull edits back (backward)
tests/run.sh                    smoke test of every script on a synthetic repo (no LLM)
```

Scripts are Python 3 stdlib + git only. The HTML needs internet for the mermaid CDN; the map falls
back to a text list without it.

## Install

Two modes. Pick by whether you are **improving** the skill or **consuming** it.

### Dev mode — one checkout, live in every repo

The setup for iterating on the skill while using it on real repos. The skill lives in exactly one
place, edits are live everywhere on the next invocation, and "merge upstream" is just a commit here.
Agent-runnable from scratch:

```bash
DC=<any path you like>                              # e.g. ~/Development/describe-changes, /srv/describe-changes
git clone git@github.com:mzvonar/describe-changes.git "$DC"
for P in ~/.claude ~/.claude-personal; do
  [ -d "$P/skills" ] && ln -sfn "$DC/skills/describe-changes" "$P/skills/describe-changes"
done
bash "$DC/tests/run.sh"                             # verify before trusting it on a real diff
```

`$DC` is yours to choose and is never hardcoded anywhere: the skill finds the checkout by resolving
its own symlink (`readlink -f "$SKILL_DIR"` → `git rev-parse --show-toplevel`), so the staleness check
in SKILL.md step 0 works regardless of where you cloned it. `$DC` below means that same checkout.

Then, once per consumer repo, add `.describe-changes/` to its `.gitignore` (report + feedback output
is written into every repo you run the skill on).

Rules that keep this working:

- **User level only.** In dev mode never symlink *or* vendor into a consumer's `.claude/skills/`.
  That path is where the committed vendored copy belongs, and project level wins over user level — a
  vendored copy silently shadows your checkout. (That shadowing is *correct* once a consumer pins a
  copy for its team; dev mode just steps aside.)
- **Nothing about the skill gets committed to the consumer.** No per-repo symlink to gitignore, no
  VM-only path in a shared repo.
- It works because `scripts/collect-diff.sh` resolves the target repo from the **cwd**
  (`git rev-parse --show-toplevel`), not from the script's own location — so the skill can live
  outside the repo it analyses. The lessons store is machine-global
  (`~/.describe-changes/lessons.jsonl`), with every event tagged `repo`, so several consumers feed
  one log and `feedback.py digest --repo <name>` still separates them.

Loop: edit `skills/describe-changes/…` → `bash tests/run.sh` → run `/describe-changes` in a consumer
repo → `feedback.py digest` → commit + push here. No sync step, no second copy to diverge.

Caveat: `VERSION` is a static string, so lessons collected across an iteration session all carry the
same `skill_version` and the digest cannot attribute one to a specific edit. Bump `VERSION` when a
change is worth telling apart.

### Consumer install — vendored, pinned, committed

For teammates, CI, and machines that are not iterating on the skill:

```bash
cd "$DC"                                     # your checkout (see dev mode above)
./sync-skill.sh /path/to/consumer            # pinned to main (needs a commit here)
./sync-skill.sh /path/to/consumer --ref <ref>
./sync-skill.sh /path/to/consumer --worktree # copy the current working tree, uncommitted edits included
```

Writes `<consumer>/.claude/skills/describe-changes/` + `<consumer>/.claude/skills/.describe-changes-version`
(`sha=…`). Commit both in the consumer. Add `.describe-changes/` to the consumer's `.gitignore`.

If you edited a vendored copy in place while using it, `./sync-skill.sh --from /path/to/consumer`
copies it back here; review, commit, then forward-sync every consumer again. Dev mode never needs
this — there is only one copy.

**Plugin:** `claude --plugin-dir "$DC"`, or
`/plugin marketplace add <path-or-repo>` → `/plugin install describe-changes@describe-changes`.

## Use

```
/describe-changes                      # branch vs default branch (+ working tree), or working tree on main
/describe-changes HEAD~3               # any git diff args
/describe-changes --staged --task "…"  # with explicit intent
/describe-changes main --story _bmad-output/implementation-artifacts/3-2-story.md
/describe-changes --chat-only          # no HTML (phone-only session)
```

It also triggers on its own after the agent implements a story/task ("walk me through what you
changed", "what should I review").

Output lands in `<repo>/.describe-changes/<branch>/` (`report.json`, `index.html`, `feedback.jsonl`,
`diff-model.json`, `substantive.diff`). The server prints LAN and Tailscale URLs for the phone.

## Learning loop

See `skills/describe-changes/reference/learning-loop.md`. Short version:

```bash
python3 skills/describe-changes/scripts/feedback.py digest     # what humans disagreed with, what they asked
```

→ edit `reference/analysis-guide.md` → bump `VERSION` → `bash tests/run.sh` → commit + push (dev mode
is live immediately; vendored consumers need a re-sync). Configure
`~/.describe-changes/config.json` with an HTTP backend to pool lessons across a team.

## Tests

```bash
bash tests/run.sh
```
