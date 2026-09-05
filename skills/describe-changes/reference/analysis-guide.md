# Analysis guide — how to decide what a human must check

The report's only job: make the reviewer's signature honest at the lowest attention cost. Every rule
below descends from four principles: **the human is the bottleneck**, **credibility is the only
currency** (a false flag costs more than a miss), **fresh ignorance is a feature** (lead with questions,
not explanations), and **human points, AI investigates** (a gut-flag is an order to dig, not a verdict).

## 1. Budget first

| Bucket | Hard cap | Meaning | Test |
|---|---|---|---|
| **critical** | 3 | If this is wrong the change must not ship, and only a human can tell. | "Would I page someone if this were wrong in prod?" *and* "Can a test/linter/the author settle it?" → no |
| **medium** | 7 (soft) | Worth 60 seconds of a human's attention; wrong would cost a fix-forward, not an incident. | "Would a careful senior ask about this in review?" |
| **low** | — | Nice to know; collapsed by default. | Everything else you'd still mention. |

When you exceed a cap, **demote the least irreversible item** — not the least interesting.
Rather than 5 criticals, produce 3 criticals and put the other two first in medium.
Zero findings is a valid report. Say so plainly; the "Everything else" list carries the honesty.

## 2. What earns a flag (signals, strongest first)

1. **Divergence** — what the code does ≠ what it claims. Misleading names (`hint` holding a secret,
   `isValid` that also mutates), a "refactor" that changes behaviour, a helper doing more than its
   caller expects, scope beyond the task. Tag `divergence`.
2. **Blast radius × reversibility** — migrations, data deletion, auth/permission checks, money,
   public API shapes, persisted formats, background jobs, retries. Tag `blast-radius`, `data`,
   `auth`, `api`, `money`.
3. **PII / secrets flow** — a field renamed, wrapped, logged, serialised, sent, stored. Follow the
   value, not the keyword. Tag `pii`, `secret`.
4. **Confidence × blast-radius mismatch** — a big-impact change the author was *very* confident
   about, or justified at length, deserves a second look precisely because of that. Tag `confidence`.
5. **Author confession** — spots the implementer (you, in this session) was unsure of, guessed, or
   could not exercise. Always at least medium. Tag `confession`.
6. **Error paths and edges** — swallowed exceptions, new `catch {}`, defaults that hide failure,
   off-by-one at boundaries, time zones, concurrency, ordering. Tag `errors`, `concurrency`, `edge`.
7. **Tests that prove less than they look** — tests asserting the mock, deleted/skipped tests,
   snapshot churn. Tag `tests`.
8. **Intent gap** — an acceptance criterion with no visible implementation, or an implementation
   with no criterion. Tag `intent`.

Not a flag: style, naming taste, "could be simpler", anything a formatter/linter/type-checker already
enforces, anything already in the folded noise. Put those in `low` only if they'd mislead a future reader.

## 3. Shape of a finding

- `title` — the claim, ≤ 80 chars, falsifiable: "`saveUser` now upserts instead of inserting".
- `verify` — one question the human can answer by looking: "Is silently overwriting an existing
  row the intended behaviour for duplicate emails?"
- `why_human` — why a machine can't settle it (intent, judgement, domain, irreversibility).
- `what` — 1–2 sentences of mechanism, optional. Lead with the question, not the lecture.
- `file`, `lines` (new-side line or range), `hunks` (`["F3H2"]`) — the renderer fetches the code.
- `tags` — from the list above; they become filter buttons and feed the learning loop.

## 4. Phases (altitude 1)

Group by **dependency**, not by file or commit: types/schema → core logic → integration/wiring →
UI → tests/docs. Each phase: a title a stranger understands, 1–3 sentences, the files. 2–6 phases;
a one-file change gets one phase.

## 5. The map (altitude 1, visual)

Nodes are *symbols the change touched that matter*: functions, components, types, modules, stores,
tables, endpoints. Mark each `added | modified | removed | moved | renamed | split | unchanged`
(`unchanged` only for an anchor the reader needs, e.g. the caller that was not touched). Edges:
`calls`, `dataflow` (a value travels), `imports`, `renders`, `extends`, `moved_to`, `split_into`,
`reads`, `writes`. Label edges with the *payload or purpose* when it isn't obvious (`user row`,
`JWT`, `POST /orders`). ≤ ~25 nodes — if the change is bigger, map the riskiest phase and say so in
`graph.narrative`. Use `symbol_moves` and `moved_from` from `diff-model.json` for moves/splits;
never guess a move the script didn't see.

## 6. Noise — trust the script, then be honest about its limits

`diff-model.json` already folded: pure renames (+ the import rewrites that follow them), moves,
splits, whitespace-only and format-only hunks (not in whitespace-sensitive languages), comment-only
hunks, lockfiles, generated/snapshot/binary files, **prop threading** (a prop declared once and
passed at N call sites — the declaration stays visible, the pass-sites fold under a flow of the
components it travels through), **index/registry rows** whose link target is a file this change
adds, and **working notes** (plans, handoffs, journals, a lessons inbox — never an ADR, a wiki page,
a README or a changelog, which are the "why" a reviewer needs most).
Copy its `folds` into `report.folded`. If you
notice a fold that hides a real change (a "rename" at 52% similarity that also changed logic, a
snapshot that changed because behaviour did), surface that as a finding — that is exactly the
"P0 buried in the noise" failure this tool exists to prevent.

## 7. Writing

Plain English for a stranger. Name code in backticks. Verbs over adjectives. No praise, no
"successfully". Every sentence either tells the reviewer what to look at or why — delete the rest.
