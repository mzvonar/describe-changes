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

**Vendored copy in a consumer repo (recommended — same model as `run-story-skill`):**

```bash
cd ~/Development/describe-changes
./sync-skill.sh /path/to/consumer            # pinned to main (needs a commit here)
./sync-skill.sh /path/to/consumer --worktree # copy the current working tree, uncommitted edits included
```

Writes `<consumer>/.claude/skills/describe-changes/` + `<consumer>/.claude/skills/.describe-changes-version`
(`sha=…`). Commit both in the consumer. Add `.describe-changes/` to the consumer's `.gitignore`
(reports + feedback output).

**Edit-while-using loop:** if you fixed the vendored copy inside a consumer while using it,
`./sync-skill.sh --from /path/to/consumer` copies it back here; review, commit, then forward-sync
every consumer again.

**Plugin:** `claude --plugin-dir ~/Development/describe-changes`, or
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

→ edit `reference/analysis-guide.md` → bump `VERSION` → commit → re-sync consumers. Configure
`~/.describe-changes/config.json` with an HTTP backend to pool lessons across a team.

## Tests

```bash
bash tests/run.sh
```
