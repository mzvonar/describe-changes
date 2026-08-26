# Code-change visualization — survey (2026-08-22)

Input to the views toolset (`skills/describe-changes/reference/visualizations.md`). Compiled by a research
agent; links at the bottom.

| Tool | Shows | Idiom | Value for a 100-file React PR | Steal | Embeddable |
|---|---|---|---|---|---|
| CodeRabbit Atlas / Change Stack | PR as change cohorts → ordered layers anchored to hunks; diagram only where useful | Outline + lanes | High — kills alphabetical order | cohort→layer→hunk outline; diagram-per-layer only when it helps | Mermaid v11 (~800 KB gz) |
| Devin Review | Grouped, ordered hunks with a 1-line caption each; moved code collapsed; 3-colour confidence | Ordered list + badges | High | per-hunk caption; "moved, not rewritten" | idiom only |
| GitHub Files Changed (2026) | Tree with comment/error markers | Tree + markers | Medium | reviewed/has-question markers | — |
| Graphite / ReviewStack | Stack nav, version dropdown | Stack + timeline | Medium | "what changed since last look" | — |
| SemanticDiff / difftastic | AST diff; renames/moves grouped | Token side-by-side | High noise cut | classify hunks rename/move/format/logic (we do) | CLI only |
| CodeSee Review Map (defunct) | Changed files as nodes; colours add/edit/delete/rename; **white = unchanged but depends on a changed file**; reviewed checkboxes | Nested-folder graph | High — blast radius | impacted-but-untouched nodes; per-node reviewed + progress | Cytoscape (112 KB gz) |
| Sourcegraph / code-review-graph | Callers + tests per changed symbol | Counts | Medium | "N callers, M tests" stat per symbol | D3 |
| codeflow (MIT 2025) | In-browser dep map: Folder / Layer / Churn / Blast views | Force graph | High, no build | Layer + Blast view toggle | fork; D3 ~90 KB gz |
| CodeScene | Hotspots + change coupling | Circle pack | Medium | "this file always changes with that one" | d3-hierarchy |
| ChangePrism (ICSME 2025) | Pre/post file mini-maps coloured by change kind | Spectrum bar | High per-file glance | **per-file spectrum strip** in the file list | hand-rolled SVG |
| ReviewVis (JSS 2023) | Symbol-level change graph | Graph | Medium | component/hook nodes, not files | dagre/elk |
| CHID (EMSE 2025) | PR risk score + impacted areas | Table | Medium | one score + why-list | — |
| File-ordering studies (2023, 2025) | Position bias: later files get less scrutiny | — | Foundational | risk first, order explicit (we do) | — |
| CoRA / untangling | Commit → feature/fix/refactor parts | Partitioned lists | High | intent label per cohort | — |
| React DevTools / react-sight / LocatorJS | Live component tree, click-to-source | Tree | Medium | static tree with changed nodes lit | markmap-view 72 KB |
| Storybook + Chromatic TurboSnap | Affected stories via import graph; before/after | Pairs | High for UI | "affected screens" from import graph; screenshots | precompute |
| dependency-cruiser / madge / skott / Nx | Import graph | Graph | Medium | changed ∪ 1-hop filter | JSON + Cytoscape |
| FigJam / Whimsical / Overflow | Screens as boxes, nav arrows, unreachable flagged | Screen map | High | **route map with nested components, changed lit** | hand-rolled boxes (+ dagre for arrows) |

## Ranked ideas

1. Cohort → layer → hunk outline with per-hunk captions (Atlas + Devin + CoRA). → our phases + findings; add captions per hunk in "Everything else".
2. Screen/route map with nested component boxes, changed nodes lit (FigJam + CodeSee + React tree). → **`screen` view** (done); add "unchanged-but-imports-a-changed-file" boxes later.
3. Blast-radius panel per changed export: direct importers, transitive count, tests covering (codeflow Blast + code-review-graph). → compute from import graph at collect time; show as counts on adoption roots.
4. ChangePrism spectrum bar per file in the file list. Pure SVG, ~50 lines. → lets a reviewer skip 60 trivial files in seconds.
5. Diagram only where it pays + "what changed since you last looked" (Atlas, Graphite). → mermaid optional (done); version delta between report snapshots via the fingerprint.

Sources: https://www.coderabbit.ai/atlas · https://cognition.com/blog/devin-review · https://github.blog/changelog/2026-01-22-improved-pull-request-files-changed-page-on-by-default/ · https://semanticdiff.com/blog/semanticdiff-vs-difftastic/ · https://docs.codesee.io/docs/review-map-guide · https://github.com/braedonsaunders/codeflow · https://github.com/tirth8205/code-review-graph · https://codescene.com/blog/change-coupling-visualize-the-cost-of-change · https://arxiv.org/abs/2508.12649 · https://www.sciencedirect.com/science/article/pii/S0164121222001820 · https://link.springer.com/article/10.1007/s10664-024-10600-2 · https://arxiv.org/pdf/2306.06956 · https://arxiv.org/pdf/2506.10654 · https://ieeexplore.ieee.org/document/8952413/ · https://qaskills.sh/blog/chromatic-turbosnap-storybook-guide · https://reactflow.dev/learn/layouting/layouting
