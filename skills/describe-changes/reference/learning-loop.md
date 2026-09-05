# Learning loop — how the skill gets sharper

The skill learns from three channels, all normalised into one append-only event log by
`scripts/feedback.py`:

| Channel | Event types | Captured by |
|---|---|---|
| HTML report UI (phone/desktop) | `more`, `less`, `noise`, `checked`, `note`, `gut_flag`, `undo`, `comment` (select text → Ask; carries selection + context + section/finding) | `serve.py` (`POST /feedback` → `feedback.jsonl`), or Copy JSON → paste into chat when opened as a file |
| "How to check" cards | `check_verified` / `undo`, `check_note` ("didn't work" text), `check_run` (inline API send + HTTP `status`) — each carrying the check's `id`, `feature` and `surface` | same as above; read per-report with `feedback.py notes`, across reports with `digest` |
| Chat follow-ups | `question` (+ which finding, + what code answered it) | the skill, step 7 |
| Page comments answered | `question` with `source=comment`, `selection`, `section`, `improvement` — what the report should have said up front | `feedback.py answer` (answers live in `answers.jsonl`, rendered into the page's Conversation section) |
| Q&A outcomes | `outcome` with `kind = missed / false_positive / confirmed / severity_changed` | the skill, step 7 |

Every event carries `repo`, `range`, the finding's `severity` + `tags` + `title`, the `skill_version`
(the vendored `sha=` or `VERSION`) and the `user`. That is enough to answer the maintainer's questions:
*which tags get over-flagged, which file types collect gut-flags, what do people keep asking that the
report should have said.*

## Local store (default)

`~/.describe-changes/lessons.jsonl` (override with `DESCRIBE_CHANGES_HOME`). Nothing leaves the
machine unless a backend is configured.

## Shared store (team-wide)

Put a `~/.describe-changes/config.json` in place:

```json
{ "user": "mato", "team": "platform",
  "backend": { "type": "http", "url": "https://memory.example.com/v1/events", "token_env": "DC_MEMORY_TOKEN" } }
```

`feedback.py push` POSTs `{source:"describe-changes", team, events:[…]}` with a bearer token from the
named env var and marks events `pushed`. The payload is deliberately generic JSON so it can land in
any shared agent-memory service (an MCP memory server's HTTP ingress, a Supabase/PocketBase table, a
Slack/Notion relay, a git repo of JSONL behind a tiny endpoint). When a team-wide agent memory tool
becomes the standard, add a second backend `type` in `cmd_push` — the event shape does not change.

## Maintainer workflow (sharpening the skill)

1. Collect: `python3 scripts/feedback.py digest [--since 2026-08-01] [--repo run-story]` (or export the
   shared store to a local `lessons.jsonl` first).
2. Read the digest's sections in order: **severity calibration** (which `severity/tags` combos humans
   demote or call noise → tighten rules in `analysis-guide.md` §2), **gut-flags** (file types the
   analysis is blind to → add a signal), **how-to-check results** (a check the reader marked as not
   working is a defect in the *report* — wrong route, missing precondition, an expectation the code
   does not meet → tighten the `how_to_check` rules), **questions** (what the report should have
   answered up front → add to the finding shape, phases, or map rules), **outcomes** (missed
   findings → new signal; false positives → budget discipline).
3. Edit `reference/analysis-guide.md` / `SKILL.md`, bump `VERSION`, commit in the describe-changes repo,
   re-sync consumers with `sync-skill.sh`. Lessons from the next runs will carry the new version, so
   you can see whether the calibration moved.

Keep the loop honest: a lesson that says "flag more" must be weighed against the credibility budget.
The goal is not more findings; it is findings the reviewer believes.
