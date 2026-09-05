# report.json — the contract between the analysis (LLM) and the renderer (script)

Write this file to `$OUT/report.json`. `check-report.py` validates it; `render-report.py` renders it.
Keys marked ● are required.

```jsonc
{
  "title": "Per-step execution config for type:claude steps",          // ● short, the change's name
  // The ASK, ONE line, ≤ 260 chars. Rendered as a small lede above the summary.
  "intent": "Story 3.2: let workflow.yml set model/effort per step.",
  // ● What CHANGED, plus the one thing that is not obvious from it. ≤ 3 sentences / 420 chars
  // (hard cap 700). It must NOT restate the intent — the validator warns when they overlap > 55%.
  // Test: "what does the reviewer still not know after reading the intent line?" Answer only that.
  "summary": "Steps carry an `execution` block that `runStep` resolves per step, falling back to the workflow default. The non-obvious part: an unset `mode` no longer inherits the daemon's — it resolves to `default`.",
  // Author doubt, as a LIST — one scannable line each, the longer explanation folded behind it.
  // 2–4 items is the useful range; > 6 warns (if everything is doubtful, nothing is).
  "confession": [
    { "point": "The retry-path e2e never ran — I could not reproduce the fixture locally.",
      "detail": "Optional; shown only when the reader expands the point. Mechanism, what you tried, what would settle it." },
    { "point": "`resolveModel`'s fallback is a guess; no test pins it." }
  ],
  "range": "main..feat/3.2 (+ working tree)",                          // optional; meta.json has it

  "phases": [                                                         // ● dependency order, 2–6
    { "id": "p1", "title": "Schema + types", "narrative": "…1–3 sentences…", "files": ["src/shared/workflow.ts"] }
  ],

  "graph": {                                                          // ●
    "narrative": "optional one-liner about what the map shows / omits",
    "nodes": [                                                        // ≤ ~25
      { "id": "runStep", "label": "runStep()", "kind": "function", "change": "modified", "file": "src/daemon/executor.ts" },
      { "id": "ExecCfg", "label": "ExecutionConfig", "kind": "type", "change": "added", "file": "src/shared/workflow.ts" },
      { "id": "oldHelper", "label": "buildArgs()", "kind": "function", "change": "moved", "file": "src/daemon/args.ts" }
    ],
    "edges": [
      { "from": "runStep", "to": "ExecCfg", "kind": "reads", "label": "model, effort" },
      { "from": "runStep", "to": "oldHelper", "kind": "calls" }
    ]
  },
  // node.kind: function | method | component | hook | type | interface | schema | module | file | store | db | table | endpoint | job | config
  // node.change: added | modified | removed | moved | renamed | split | unchanged
  // edge.kind: calls | dataflow | imports | renders | extends | moved_to | split_into | reads | writes | emits

  "views": [ /* optional, 0–3 — see visualizations.md: screen | flow | adoption */ ],

  "findings": [                                                       // ● important first; ids C1.. M1.. L1..
    {
      "id": "C1", "severity": "critical",
      "title": "`spawnClaude` passes `--dangerously-skip-permissions` whenever `execution.mode` is unset",
      "verify": "Is bypass the intended default for steps that do not declare a mode?",
      "why_human": "Default policy for unattended sessions is a judgement call with security consequences; no test encodes the intent.",
      "what": "The fallback branch in `resolveMode()` returns 'bypass' instead of the previous 'default'.",
      "file": "src/daemon/executor.ts", "lines": "118-131", "hunks": ["F4H2"],
      "tags": ["divergence", "auth", "blast-radius"]
      // optional instead of hunks: "before": "…code…", "after": "…code…"
    }
  ],

  "folded": [ /* copy diff-model.json → folds verbatim */ ],          // ●
  "unreviewed_notes": {                                              // substantive files with no finding: why
    "src/pwa/components/StepCard.tsx": "prop pass-through only; typed end to end"
  }
}
```

Rules the validator enforces: ≤ 3 critical (error), ≤ 7 medium (warn); each finding has `title`,
`verify`, `why_human`, `file`; finding ids are unique and match severity (`C`/`M`/`L`); every file path
exists in the diff; every edge references a node; graph ≤ 40 nodes (warn).

On the header specifically: `summary` > 700 chars is an **error**, > 420 a warning, > 4 sentences a
warning; `intent` > 260 chars warns; `intent`/`summary` vocabulary overlap > 55% warns; a `confession`
item needs a `point` (its `detail` is optional), a `point` > 180 chars warns, and > 6 items warns.
These are caps on the reviewer's attention, not on your prose — an over-long header is the cheapest
way to produce the rubber-stamped signature this tool exists to prevent.

`confession` also accepts a plain string (the pre-1.1 form) and still renders, but the list is what
gets read: a reviewer skims four one-liners and opens the one that worries them, where the same
content as a paragraph is skipped whole and the doubt may as well not have been declared.
