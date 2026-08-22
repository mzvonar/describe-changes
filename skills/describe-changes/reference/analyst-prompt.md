# Analyst prompt (fan-out for big changes)

Use when `substantive.diff` exceeds ~2500 lines. Slice by phase with `scripts/slice-diff.py`, spawn one
analyst per slice **in parallel** (Agent tool, general-purpose), then synthesize their JSON under the
credibility budget yourself. Analysts may read the repo for context; they must cite hunk ids.

```
You are one analyst in a code-change description pipeline (skill "describe-changes"). Your job is NOT
to review code quality; it is to tell a human reviewer what changed and the FEW spots only a human
can judge.

Read the rules first: <skill>/reference/analysis-guide.md (§2, §3, §5) and the report shape in
<skill>/reference/report-schema.md.

Your slice: <path to slice-<name>.diff> — the "<phase title>" part of <branch> in the repo at <root>
(read-only; you may Read/Grep source and tests there for context: callers, deleted files, tests,
e2e specs). Hunks are tagged like `[F13H1]` — cite those ids.

Intent: <task / story / commit subjects>.
Known + deferred already (do not re-flag, but DO flag if the code contradicts the note): <bullets
from the repo's deferred-work / review notes, if any>.

Return ONLY a JSON object:
{
 "phase": {"title", "narrative" (1–3 sentences a stranger can follow), "files": [paths]},
 "graph": {"nodes":[{"id","label","kind","change","file"}], "edges":[{"from","to","kind","label"}]}  // ≤ 12 nodes
 "candidates": [{"severity","title" (falsifiable, ≤80 chars),"verify" (one question answerable by
   looking),"why_human","what","file","lines" (new-side),"hunks":[ids],"tags":[...],
   "evidence" (what you actually checked)}],   // ≤ 6, most important first
 "unreviewed_notes": {"path": "one clause why it needs no flag"},
 "confession": "spots with no test coverage or that look guessed — or empty string"
}
Be ruthless: a false flag costs more than a miss. Prefer divergence (code does ≠ what it claims),
blast radius, behaviour present in deleted code and absent in the new, and anything the tests assert
less than before. Verify against the source before listing.
```

Synthesis rules: merge graphs (dedupe node ids), keep ≤ 25 nodes total; rank all candidates together;
apply the caps (≤ 3 critical); drop anything an analyst could not evidence; keep each phase's
narrative; union `unreviewed_notes`; join confessions.
