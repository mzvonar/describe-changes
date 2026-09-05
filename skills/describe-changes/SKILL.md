---
name: describe-changes
version: "1.0.0"
description: >
  Present an implemented change to a human reviewer the way a human needs it: what was done and why,
  a visual map of the high-level change (who calls whom, where data flows, what moved/split/renamed),
  and a ranked, tiny list of the spots that genuinely need human eyes (critical / medium / low) — with
  renames, moves, formatting, lockfiles and import rewrites folded away. Renders in chat AND as a
  mobile-first interactive HTML report, then answers follow-up questions and collects feedback so the
  skill sharpens over time. Use proactively right after implementing a story/task/feature, before
  opening a PR, and whenever the user says "describe the changes", "walk me through what you changed",
  "what should I review", "explain this diff/PR/branch", "show me the implementation", or "/describe-changes".
argument-hint: "[git range | --staged | <base>] [--task \"...\"] [--story <file>] [--chat-only] [--port N]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# describe-changes

**Goal:** make the human's signature on this change honest, at the lowest possible attention cost.
The human is the bottleneck, not the code. You allocate their attention; you do not dump a diff.

**Division of labour (hard rule):** scripts do everything mechanical — range resolution, rename/move/
split/whitespace/format/import-rewrite folding, code snippets, HTML, feedback capture. You do only what
scripts cannot: say what the change *means*, draw the map, and decide the ~3 things a human must check.
Never re-derive the noise pass by hand, never write HTML, never paste the raw diff into chat.

## 0. Resolve paths and inputs

```bash
SKILL_DIR=<dir containing this SKILL.md>        # ${CLAUDE_PLUGIN_ROOT}/skills/describe-changes, or .claude/skills/describe-changes, or ~/.claude/skills/describe-changes
S="$SKILL_DIR/scripts"
DEV_CHECKOUT=$(git -C "$(readlink -f "$SKILL_DIR")" rev-parse --show-toplevel 2>/dev/null)
```

Arguments (all optional): a git range / ref / `--staged` / `-- path` (passed through to `git diff`);
`--task "…"` or `--story <file>` = the intent source; `--chat-only` = skip HTML (phone-only sessions);
`--port N` for the server. Staleness: in dev mode `$SKILL_DIR` is a symlink into the checkout you edit,
so **resolve it — never assume a path**. If `$DEV_CHECKOUT` is non-empty and is not the repo being
described, and this repo has `.claude/skills/.describe-changes-version`, compare that file's `sha=`
with `git -C "$DEV_CHECKOUT" rev-parse HEAD`: if they differ, the vendored copy is behind your
checkout — mention it once, never block.

**Intent source, in priority order:** explicit `--task`/`--story` → the story/task file you implemented
this session → PR/MR description → `commits.txt` from step 1 → the branch name. Read it; the report is
judged against *what was asked*, not just what was done.

## 1. Collect + fold (script)

```bash
OUT=$(bash "$S/collect-diff.sh" [git diff args…] | tail -1 | sed 's/^OUT=//')
```

**Scope = everything the human would sign for:** on a feature branch that is every commit since
`merge-base(<base>)` **plus** staged, unstaged and untracked changes (the working tree is the truth,
not HEAD); `--committed-only` limits it to HEAD; on the default branch it is the working tree vs
HEAD. `meta.json` records `commits`, `uncommitted_files` and a tree `fingerprint`. Say in chat how
much of the change is uncommitted — the reviewer must know a signature on HEAD would not cover it.

Produces `$OUT/{raw.diff,numstat.txt,commits.txt,meta.json,diff-model.json,substantive.diff}`.
Exit 2 = nothing to describe; stop and say so. Add `.describe-changes/` to the repo's `.gitignore`
if it is not there (it holds reports + feedback, never source).

## 2. Read the model, not the diff

Read **`diff-model.json`** first (`stats`, `folds`, `symbol_moves`, per-file `status`/`moved_from`/
`symbols_added|removed`, hunk `category` + `symbol` + `id`). Then read **`substantive.diff`** — only the
hunks that survived folding; each hunk is tagged `[F3H2]` so you can cite it. Open full source files
only when a hunk's meaning depends on context you cannot see (a caller, a type, a config key) — and
prefer `Grep` for the one symbol over reading the file.

**Big change (substantive.diff > ~2500 lines)? Fan out, don't skim.** Slice by phase —
`python3 "$S/slice-diff.py" "$OUT/substantive.diff" "$OUT/slices" header='page-header|layout' picker='pairing/' --rest misc`
— spawn one analyst per slice in parallel with the template in `reference/analyst-prompt.md`, read
the small slices (docs, config) yourself, then synthesize. Never read 9k lines serially and call it
analysis.

**Mine the repo's own review trail first.** `deferred-work.md`, `lessons-inbox.md`, review-findings
sections, PR comments: deferred items are the author's *known* doubts — list them under
`confession`/findings as "known, deferred", and flag any place the code contradicts the note.

If you implemented the change yourself in this session you hold privileged knowledge: **confess** the
spots you were unsure about, guessed at, or could not test. That goes into `confession` and usually
into a finding. Self-reported doubt is the cheapest, highest-precision signal this tool has.

Write it as a **list of one-line points**, each with an optional `detail` the reader can expand —
not a paragraph. Two to four items. A confession only works if it is read, and a wall of prose at the
top of the report is skipped wholesale, which leaves the doubt declared but not delivered.

## 3. Analyse → write `$OUT/report.json`

Follow `reference/analysis-guide.md` (severity rules, credibility budget, tags, divergence lens) and
the exact shape in `reference/report-schema.md`. The non-negotiables:

- **Credibility budget:** ≤ 3 critical (hard cap), ≤ 7 medium, the rest low or unflagged. If everything
  is critical, nothing is. A false flag costs more than a miss — the reviewer tunes out forever.
- **Attention budget on the header.** `intent` = the ask, ONE line. `summary` = what CHANGED plus the
  one thing not obvious from it, ≤ 3 sentences. They answer different questions, so **never restate
  the intent in the summary** — the test is "what does the reviewer still not know after reading the
  intent line?", and the validator warns when their vocabulary overlaps > 55%. Length here is not a
  style question: the reviewer who gives up at the top signs without reading anything below it.
- **The summary is FUNCTIONAL, not mechanical.** Say what a person can now do, what they can no
  longer do, and the rules that decide which — in the product's own words, the ones on the buttons.
  Mechanism (locks, transactions, capabilities, cache tags, file moves) belongs in the summary *only*
  where it **is** a decision or a risk the reviewer must weigh; otherwise it lives in the phases, the
  findings, or nowhere. Test each clause: *would this sentence change what a non-author asks about?*
  "Guarded by an invariant re-asserted inside the write transaction over a row lock" fails it —
  "**the last admin can't remove or demote themselves; the controls disappear rather than fail**"
  passes, and is the same fact stated where the reviewer lives. A summary that reads like a commit
  message is the second-commonest way this report gets rubber-stamped, after being too long.
- **Every finding = a question the human can answer** (`verify`), plus `why_human` — why a machine/the
  author can't settle it (judgement, intent, blast radius, irreversibility, security, data, money).
- **Divergence lens:** flag where what the code *does* ≠ what it *claims* (name vs body, "just a
  refactor" that changes behaviour, scope creep beyond the task, PII/secrets wrapped or renamed,
  hidden global state, error paths swallowed). That is the part no linter does.
- **Phases** = dependency order (foundations → domain → wiring → tests), not file or commit order.
  2–6 phases; each narrative is 1–3 sentences a stranger can follow. They render *after* the map and
  views: the reader wants the shape of the change before the walkthrough of it, and a phase list read
  cold is a sequence of unfamiliar names. Write them expecting the reader has already seen the map.
- **Views** (`reference/visualizations.md`): pick 0–3 from the toolset — `screen` (nested boxes:
  screen → slots → what fills them) for UI chrome, `flow` (created → deleted → re-pointed → restyled)
  when the commits tell a story, `adoption` (root → used in → replaces) for every extracted shared
  thing. Every block with a `file` is clickable to the changed code. Prefer these over the graph for
  React/UI work; leave `graph.nodes` empty to hide the map.
- **Graph** = only change-relevant symbols (functions, components, types, modules, stores), ≤ ~25
  nodes, edges of kind `calls | dataflow | imports | renders | moved_to | split_into | extends | reads | writes`.
  Use `diff-model.json`'s `symbol_moves` and `moved_from` for `moved`/`split`/`renamed` nodes.
- **`how_to_check`:** one entry per capability this change actually SHIPPED, with the steps to drive
  it — the reviewer's way to stop trusting the report. Write steps someone who has never seen the
  feature can follow: where to start, what to click, what they should see (`expect`). Name real
  buttons and routes, not component names. Cover what the change *added or altered*, not the whole
  product; omit the section entirely for a change nobody can drive (pure refactor, infra, docs).
  Set `surface: "api"` plus a `request` for anything HTTP-callable and the page gives the reader
  copy-as-curl, a Postman collection and an inline send against a base URL they choose. Skip
  `request` for a server action or RPC that has no addressable endpoint — a card that cannot be run
  is still a good card, and a fake endpoint is worse than none.
- **`folded`:** copy `diff-model.json` → `folds` verbatim (you may add a one-line `title` tweak; never
  invent folds). **`unreviewed_notes`:** one clause per substantive-but-unflagged file saying why it
  didn't make the cut (the honest "I looked, nothing to ask" list).
- Be concrete: `file`, `lines` (new-side), `hunks: ["F3H2"]` so the renderer pulls the code for free.

## 4. Validate (must pass)

```bash
python3 "$S/check-report.py" "$OUT/report.json"
```

Fix every `ERROR` (budget overflow → demote, unknown file → fix path, bad edge → fix node id).
Treat `WARN` as advice.

## 5. Render + serve

```bash
python3 "$S/render-report.py" --dir "$OUT"
nohup python3 "$S/serve.py" "$OUT" --port ${PORT:-8790} > "$OUT/serve.log" 2>&1 &
sleep 0.5; cat "$OUT/serve.log"
```

Give the user the **LAN and Tailscale URLs** (phone-friendly) and the local path. The page is
self-contained except the mermaid renderer (CDN); the map's text fallback shows if offline.
If the `Artifact` tool is available and the user is remote, you may also publish `$OUT/index.html`
(keep the same file path on re-publish). Skip all of this with `--chat-only`.

## 6. Present in chat (altitude 0 — short)

Exactly this shape, nothing more:

1. **The summary, once** — 2–3 sentences, the same content as `report.summary`. Do NOT also state the
   intent: in chat the reader already knows what they asked for, so repeating it back is the purest
   form of the padding that gets reports skimmed. Then `files that matter / total`, `lines that
   matter / total`, `N% folded`.
2. **Phases** as a numbered list, one line each.
3. **Critical + medium findings** as `C1 · title — file:lines → verify question`. Low findings as a
   count only ("+4 low in the report").
4. **Confession** as one line per point — the same list as the report, no `detail` text.
5. **Folded noise** as one line: "Folded: 3 renames (+11 import rewrites), 6 formatting hunks, 2 lockfiles".
6. The URLs. For `--chat-only` there is no page to link, so inline the rest: the map as a
   ```mermaid``` block **between the summary and the phases** — same order as the report, and for the
   same reason — then the full low list and the folded groups at the end.

Do not paste code. Do not repeat the report's prose. The chat view is the map's top label, the HTML
is the zoom.

## 7. Answer questions, dig deeper, keep the report true

Stay in this mode until the user moves on. **Before every answer, check the tree has not moved:**
`bash "$S/collect-diff.sh" --check "$OUT"` — exit 3 lists what changed since the snapshot; re-run
step 1 (same `--out`), re-check which findings/hunks still hold, re-render, and say so. Answering
from a stale snapshot while someone edits the worktree is how a report lies.

For each follow-up:

- Answer from the code (read the relevant file/symbol; `Grep` callers; run a test if it settles it).
  Prefer showing the one decisive snippet over narrating.
- **Log it** so the skill learns what the report failed to answer up front:
  `python3 "$S/feedback.py" question "<the question>" --dir "$OUT" [--finding C1] [--answered-by-reading src/x.ts:40-80]`
- **Fetch page comments.** The report lets the reader select any text (a symbol in the summary, a
  sentence in a phase, a line in a card) and ask about it. When the user says "check the comments",
  "I asked something in the report", or at every natural pause:
  `python3 "$S/feedback.py" comments --dir "$OUT" --open`
  Each thread carries the selection, its surrounding context, section and finding. Answer from the
  code (read the symbol, `Grep` its callers/tests; show the one decisive snippet), then store it:
  `python3 "$S/feedback.py" answer --dir "$OUT" --id <id> --improvement "<what the report should have said up front>" --text "<answer; paragraphs + \`code\`>"`
  and re-render (`render-report.py --dir "$OUT"`) so the answer appears in the page's **Conversation**
  section (the URL stays the same; the user reloads). Also echo the answer in chat. Every answered
  comment is logged as an improvement candidate — the report failed to pre-answer it.
- A **gut-flag** (⚑ in the UI, or "something feels off in X" in chat) is a targeting order: investigate
  that spot adversarially (how can it break / be abused / lie about itself), scoped to that spot only.
- If the Q&A reveals a **missed finding, a false positive, or a wrong severity**: update `report.json`,
  re-run steps 4–5 (the URL stays the same), and log it:
  `python3 "$S/feedback.py" outcome --dir "$OUT" --kind missed|false_positive|severity_changed --finding C2|new --text "…"`

## 8. Close the learning loop

When the user is done (or says "done", "looks good", "ship it", or you end the session):

```bash
[ -f "$OUT/feedback.jsonl" ] && python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT"
python3 "$S/feedback.py" push      # no-op unless a shared backend is configured
```

If the user pasted feedback JSON copied from the page (file:// mode), save it to `$OUT/feedback.json`
and ingest that. Mention in one line how many lessons were recorded. Maintainers improve the skill with
`python3 "$S/feedback.py" digest` — see `reference/learning-loop.md`.

## Style rules for everything you write

- Plain English, stranger-readable. Name functions/files in backticks. No "I have successfully…".
- Prefer *claims the human can falsify* over adjectives: "`retry()` now swallows `AbortError` — was
  that intended?" beats "error handling was improved".
- Important first, always. Short first, always. The human may stop reading at any line.
