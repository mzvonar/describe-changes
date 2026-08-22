# report.json — the contract between the analysis (LLM) and the renderer (script)

Write this file to `$OUT/report.json`. `check-report.py` validates it; `render-report.py` renders it.
Keys marked ● are required.

```jsonc
{
  "title": "Per-step execution config for type:claude steps",          // ● short, the change's name
  "intent": "Story 3.2: let workflow.yml set model/effort per step…",   // what was asked (source: task/story/PR/commits)
  "summary": "Adds an `execution` block to claude steps… 2–4 sentences: what was done and how it meets the intent.", // ●
  "confession": "I could not run the e2e that covers the retry path; `resolveModel` fallback is a guess.", // optional, author doubt
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
