---
name: describe-changes
version: "1.16.3"
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

**Division of labour (hard rule):** scripts do everything mechanical — range resolution, folding
(rename/move/split, whitespace/format, imports, prop threading, index rows, working notes, vendored
subtrees proven identical to their pin), code
snippets, HTML, feedback capture. You do only what
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

Produces `$OUT/{raw.diff,numstat.txt,commits.txt,meta.json,diff-model.json,substantive.diff,conventions.txt}`.
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

**Judge the code against its neighbours, not against your taste.** `$OUT/conventions.txt` names the
rule documents that govern the changed paths (CLAUDE.md/AGENTS.md, skills, ADRs — ranked by whether
they actually talk about these files) and the untouched siblings in every changed directory. Read
the rules that cover what changed, and open one sibling per changed directory before you clear it.
New code that contradicts a written rule or the local precedent — a skipped layer, a second way to
do what the codebase already does one way, a library the project does not use — is a finding, and a
structural one is **critical**: it propagates, and only a human can call it direction or mistake.
Cite the rule or ≥ 2 siblings in `diverges_from`; uncited, it is taste and the validator rejects it.

**A vendored subtree folds only when its provenance survives two checks the diff cannot forge.**
A pin arriving with the change it authorises is the author's own word — hash and `origin` alike —
so the classifier requires BOTH: the `origin` and `upstream_path` must already be present, and
unchanged, in the pin at the **base ref** (an earlier review accepted that upstream), AND the bytes
must re-derive from it by shallow-fetching the pinned commit. Anything else is read in full, with
the reason in `notes`: a **first vendoring** (no accepted origin exists yet), a change that
**repoints `origin`** (adopting an upstream is a human decision), a report with **no base ref**, an
unreachable remote, or content that does not match. You do not need to re-check any of that — the
classifier already refused. What DOES deserve a line in the report is the fold that DID happen: say
which origin and commit it was verified against, so the reviewer knows what they are trusting.

**Mine the repo's own review trail first.** `deferred-work.md`, `lessons-inbox.md`, review-findings
sections, PR comments: deferred items are the author's *known* doubts — list them under
`confession`/findings as "known, deferred", and flag any place the code contradicts the note.

If you implemented the change yourself in this session you hold privileged knowledge: **confess** the
spots you were unsure about, guessed at, or could not test. That goes into `confession`. Self-reported
doubt is the cheapest, highest-precision signal this tool has.

Write it as a **list of one-line points**, each with an optional `detail` the reader can expand —
not a paragraph. Two to four items. A confession only works if it is read, and a wall of prose at the
top of the report is skipped wholesale, which leaves the doubt declared but not delivered.

## 2a. If you wrote the change, you are a WITNESS — not the analyst

**When you implemented the change in this session, and `substantive.diff` is > ~2500 lines, you do
not write the findings.** Produce `intent` and `confession` — the two things only you can know — then
hand the findings to a subagent with no memory of building it (§2b). Below that size, or when you are
already reading the change cold, do both yourself and skip §3b.

The reason is not workload, it is blindness. You cannot flag what you have already decided. The
failure this exists to catch, observed in a real run: the author left a comment in `duzp.ts` saying a
required field "collapses inference at every call site". True — but the experiment behind it varied
one of the two inputs it needed to. An author-written pass repeats the comment, because it *is* the
author's reasoning. A cold reader re-ran it, found the other half, and the finding became the change
that turned a shipped production bug into a compile error.

Note what is NOT split: `confession` stays yours and is never handed over or second-guessed. It is
testimony, not a claim to be verified — nobody else can say what you were unsure about.

## 2b. The cold pass — findings from an agent that did not build it

Spawn ONE subagent with the prompt in `reference/fresh-eyes-prompt.md`. Two rules make or break it:

- **It must not see your findings, your confession, or your reasoning** — only the diff, the model
  and `conventions.txt`. Show it your conclusions and it will agree with them, and a rubber stamp is
  indistinguishable from genuine agreement.
- **It is not there to raise MORE findings.** The credibility budget is unchanged (≤ 3 critical): the
  report optimises for precision, and a second pass bolted on for recall makes the cap arbitrate by
  truncation instead of anyone deciding. It replaces your findings, at the same budget.

Then reconcile — a linking job, not a judgement, which is why it is safe for you to do:

1. Tag every finding with `provenance`: `fresh` (the cold pass), `author` (you, from knowledge the
   diff does not carry — rare, keep it that way), or `both`. All-or-nothing; the validator rejects a
   partly-tagged report.
2. For each `confession` point, set `corroborated_by` to the finding ids the cold pass raised over
   the same code — **`[]` when it flagged nothing there**, which is information, not silence.
3. Do NOT delete a cold finding because you disagree with it. Answer it in the finding's `what`, or
   leave it and let the human arbitrate. Deleting your own critique is the bias this whole step
   exists to remove.

The renderer turns that into a **Two readings** section: what you did not flag, what you flagged that
nothing corroborated, and what you both landed on independently. That divergence is the product —
merging the two lists into one silently destroys it.

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
- **`folded`:** copy `diff-model.json` → `folds` verbatim; never invent folds, never re-word them.
  The HTML renders the model's folds, not this copy (a copy can only go stale), so it exists for the
  chat view and for exports that ship without a model. **`unreviewed_notes`:** one clause per substantive-but-unflagged file saying why it
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

Give the user the **LAN and Tailscale URLs** (phone-friendly) and the local path. **Pass the URLs
exactly as printed — each carries a `?k=…` token** minted for this run; the server binds 0.0.0.0 (a
phone cannot reach a loopback bind) and refuses any request that has neither the token nor the cookie
the first open sets. `--no-token` serves openly for a trusted setup, and says so in its banner. The
page is self-contained except the mermaid renderer (CDN); the map's text fallback shows if offline.
If the `Artifact` tool is available and the user is remote, you may also publish `$OUT/index.html`
(keep the same file path on re-publish). Skip all of this with `--chat-only`.

**Every render records a snapshot** (`$OUT/snapshots/<seq>-<head7>`), and the next render opens with
**"Since you last read this"** — findings resolved / added / changed, checks re-written (and so
un-ticked), the commits that landed in between, the scope delta. Identical states are not saved
twice, so re-rendering while you edit does not bury the version the reader actually read.

The same delta is also a **page of its own**: `delta-<seq>.html` per earlier snapshot (`delta.html`
is the newest), plus a picker across them and a link back to the whole report. Point a returning
reader at `/delta.html` and someone who has been away longer at the oldest one, which is the entire
arc since the first description. Ticks are shared — a check verified on a delta page is verified on
the report.

Each of those pages is a **real report over the code between that reading and now**: its own diff,
map, phases, folded noise and file store, built by running the ordinary pipeline against the tree
the snapshot froze (`refs/describe-changes/…`, written through a throwaway index — your index and
worktree are never touched). Findings and checks are the current report's, filtered to that range;
they keep `file`/`lines` but lose `hunks`, because a hunk id belongs to the model it was computed
in. When the range cannot be built — a snapshot older than tree refs, or no code moved — the page
falls back to the delta's cards alone, and still names what moved.

```bash
python3 "$S/snapshots.py" list --dir "$OUT"                      # what versions exist
python3 "$S/snapshots.py" diff --dir "$OUT" --from first         # the whole arc since the first read
python3 "$S/render-report.py" --dir "$OUT" --snapshot-label "after review fixes"
```

**Suggest a commit before re-describing.** When the user is about to act on the report — fixing a
finding, applying a review round — say once, before they start: *"commit what's here first and the
next report will be able to show you exactly what the fixes changed."* A snapshot taken against a
dirty tree can still be compared, but only a committed one gives the delta a real `A → B` range and
commit list. Never commit for them: suggest, then follow their instruction.

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
4b. **On a two-pass run only**, one line naming the divergence: how many findings the author did not
   flag, and how many declared doubts the cold pass could not corroborate ("3 of 5 findings were
   raised cold; 1 declared doubt was not corroborated"). It is the one thing the chat view cannot
   convey by listing findings, and it is what tells the reader how much of the report is a second
   opinion. Say nothing here on a single-pass run — silence means one reader, which is the default.
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
- **Fetch page comments.** The report takes reader input FIVE ways, and `comments` returns all of
  them: selecting any text (a symbol in the summary, a sentence in a phase, a line in a card) and
  asking about it; **tapping the line number beside any line of code** — every diff in the report
  carries a gutter, whether it sits in a finding card, a file sheet or a fold; a note typed into a
  **finding** card; a note typed into a **verification check** card; and a **reply typed into a
  thread in the Conversation section**. Never filter to one type by
  hand: each surface that was ever left out of this command has been silently lost at least once,
  the reader having been told "no open comments" while their words sat in `feedback.jsonl`.

  **A thread is a conversation, not a question with an answer.** Every thread carries a reply box,
  so the reader can push back on what you said without hunting for a sentence to select. `comments`
  prints the whole thread under the opening question — `Claude:` and `THEM:` turns, oldest first —
  and **a reply REOPENS the thread**: "answered" means the last word is yours, not that an answer
  exists somewhere. So `--open` surfaces a replied-to thread again, which is the only thing that
  stops a reply landing in a thread marked done and never being seen. Read the turns before
  answering: the reader is responding to something specific you said, and a reply read without it
  is a question with no subject. Answering again appends a new turn; answering with no reply in
  between CORRECTS your previous answer rather than adding a second one.
  When the user says "check the comments", "I asked something
  in the report", or at every natural pause:
  `python3 "$S/feedback.py" comments --dir "$OUT" --open`
  Each thread carries the selection, its surrounding context, section and finding; a comment left on
  code also carries an `at:` line — `path:line` (**new-side**, except on a deleted line, where it is
  old-side and says so) plus the hunk id. **Open that line before answering.** The reader is looking
  at it, and a reply reasoned from the ±2 quoted lines alone will miss the surrounding code they can
  see and you cannot. Then answer from the code (read the symbol, `Grep` its callers/tests; show the
  one decisive snippet) and store it:
  `python3 "$S/feedback.py" answer --dir "$OUT" --id <id> --improvement "<what the report should have said up front>" --text "<answer; paragraphs + \`code\`>"`
  and re-render (`render-report.py --dir "$OUT"`) so the answer appears in the page's **Conversation**
  section (the URL stays the same; the user reloads). Also echo the answer in chat. Every answered
  comment is logged as an improvement candidate — the report failed to pre-answer it.
- A **gut-flag** (⚑ in the UI, or "something feels off in X" in chat) is a targeting order: investigate
  that spot adversarially (how can it break / be abused / lie about itself), scoped to that spot only.
- If the Q&A reveals a **missed finding, a false positive, or a wrong severity**: update `report.json`,
  re-run steps 4–5 (the URL stays the same), and log it:
  `python3 "$S/feedback.py" outcome --dir "$OUT" --kind missed|false_positive|severity_changed --finding C2|new --text "…"`
- **When fixes land, re-describe rather than patch the prose.** Re-run step 1 (same `--out`), update
  the findings the fix resolved, re-render — the reader opens the same URL and the delta section
  tells them what moved. Suggest committing the fixes first (§5): the delta then names the commits,
  and the report the user read stays pinned as its own snapshot instead of being overwritten by a
  moving worktree.

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
