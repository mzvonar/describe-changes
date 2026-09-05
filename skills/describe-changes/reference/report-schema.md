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
  //
  // FUNCTIONAL, not mechanical: what a person can now do, what they can no longer do, and the rule
  // that decides which — in the product's own words. Mechanism earns a place only when it IS a
  // decision or a risk. Compare:
  //   ✗ "Guarded by one invariant re-asserted inside the write transaction over a row lock."
  //   ✓ "The last admin can't remove or demote themselves — the controls disappear rather than fail."
  // Same fact; the second is the one a reviewer can act on. The validator warns when a summary
  // carries more than three `backticked` identifiers, which is the usual tell for the first shape.
  "summary": "A step can now pick its own model and effort instead of taking the workflow's. Steps that say nothing keep today's behaviour — except for permission mode, where an unset value now means `default` rather than inheriting the daemon's.",
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
    },
    {
      "id": "C2", "severity": "critical",
      "title": "`removeMemberAsUser` reads Prisma directly instead of going through the repository",
      "verify": "Is this deliberately outside the layer rule, or should it call `membershipRepository`?",
      "why_human": "The rule exists to keep tenant scoping in one place; whether this is a new direction is the author's call.",
      "file": "src/features/org/service/member-service.ts", "lines": "44-58", "hunks": ["F9H1"],
      "tags": ["convention", "blast-radius"],
      // REQUIRED on a `convention` finding: what it contradicts. A written rule, or ≥ 2 neighbours
      // that do it the other way. Uncited = taste, and check-report.py rejects it.
      "diverges_from": [
        { "ref": "CLAUDE.md:161", "why": "service layer never touches Prisma directly" },
        { "ref": "src/features/org/service/invitation-service.ts:22" }
      ]
    }
  ],

  // Optional. One entry per SHIPPED user-facing capability, so a reviewer can exercise it for real
  // instead of trusting the report. Omit for a change nobody can drive (pure refactor, infra, docs).
  "how_to_check": [
    {
      "id": "V1",                                   // V<n>, unique
      "feature": "Remove a member from an organization",
      "surface": "ui",                              // ui | api | cli   (default ui)
      "where": "/app/org/{slug}/settings/members",  // route, screen or command
      "setup": "Sign in as an owner of an org that has two owners.",   // optional preconditions
      "steps": ["Open Nastavenia → Členovia.", "Press Odstrániť on the other owner's row.", "Confirm."],
      "expect": "The row disappears without a page reload and a success toast shows.",
      "covered_by": "tests/e2e/specs/organization/member-removal.spec.ts"  // optional
    },
    {
      "id": "V2", "feature": "Bulk import endpoint", "surface": "api",
      "steps": ["Send the request below.", "Re-open the list — the rows are there."],
      "expect": "201 with {imported: 3}.",
      // `request` turns the card into a runnable one: copy-as-curl, a Postman collection for the
      // whole report, and an inline send. Only for surface:"api".
      "request": { "method": "POST", "path": "/api/v1/import",
                   "headers": {"content-type": "application/json"},
                   "body": {"rows": []},
                   "note": "Needs a signed-in session cookie." }
    }
  ],

  "folded": [ /* copy diff-model.json → folds verbatim; the HTML renders the MODEL's copy */ ],  // ●
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
