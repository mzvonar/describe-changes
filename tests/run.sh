#!/usr/bin/env bash
# tests/run.sh — smoke test for the deterministic scripts (no LLM involved).
# Builds a throwaway git repo exercising: pure rename + import rewrites, a file split into two,
# whitespace-only and formatting-only hunks, a comment-only hunk, a lockfile, a whitespace-sensitive
# python change, and one real behaviour change. Then checks classification, validates a sample
# report, renders HTML, and round-trips feedback.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; S="$HERE/../skills/describe-changes/scripts"
T="${KEEP_T:-$(mktemp -d)}"; [ -n "${KEEP_T:-}" ] || trap 'rm -rf "$T"' EXIT
export DESCRIBE_CHANGES_HOME="$T/home"
fail() { echo "FAIL: $*" >&2; exit 1; }
# Isolation guard, and it is not paranoia: this script `git init`s, rewrites .gitignore, writes
# fixture sources and commits. A KEEP_T that does not exist made `cd "$T"` a no-op once and the
# fixture landed in the caller's real repo. Never trust set -e to catch a bad cd — check here.
[ -n "$T" ] || { echo "FATAL: empty scratch dir" >&2; exit 1; }
mkdir -p "$T" || { echo "FATAL: cannot create scratch dir '$T'" >&2; exit 1; }
[ -z "$(ls -A "$T")" ] || { echo "FATAL: scratch dir '$T' is not empty — remove it or unset KEEP_T" >&2; exit 1; }
cd "$T" || { echo "FATAL: cannot enter scratch dir '$T'" >&2; exit 1; }
[ "$(pwd -P)" = "$(cd "$T" && pwd -P)" ] || { echo "FATAL: not in the scratch dir" >&2; exit 1; }
git rev-parse --show-toplevel >/dev/null 2>&1 && { echo "FATAL: '$T' is inside an existing git repo — refusing to write fixtures into it" >&2; exit 1; }
git init -q -b main . && git config user.email t@t && git config user.name t
printf 'home/\nget.html\nserve.log\nserve2.log\njar\nth/\n' > .gitignore

mkdir -p src/util src/api
cat > src/util/strings.ts <<'F'
export function slugify(input: string): string {
  return input.toLowerCase().replace(/\s+/g, '-');
}
F
cat > src/util/big.ts <<'F'
export function alpha(a: number) { const x = a * 2; const y = x + 1; return y * 3; }
export function beta(b: string) { const parts = b.split(','); const trimmed = parts.map(p => p.trim()); return trimmed.join('|'); }
export function gamma(c: boolean) { if (c) { return 'yes-it-is-true'; } return 'no-it-is-false'; }
export function delta(d: number[]) { return d.reduce((acc, n) => acc + n, 0) / Math.max(d.length, 1); }
export function epsilon(e: string) { return e.split('').reverse().join('') + '!'; }
export function zeta(z: number) { return Array.from({ length: z }, (_, i) => i * i); }
F
cat > src/api/users.ts <<'F'
import { slugify } from '../util/strings';
import { alpha } from '../util/big';
// users api
export function saveUser(name: string) {
  const id = slugify(name);
  return { id, value: alpha(1) };
}
export function format(x: { a: number, b: number }) {
    return [x.a,x.b];
}
F
# Two import-only files with OPPOSITE directions, so the fold has to tell them apart: one gains a
# bare specifier inside an existing block (no quoted module path on the changed line), one drops a
# whole import line.
cat > src/api/barrel.ts <<'F'
import {
  alpha,
  slugify,
} from '../util/barrel';
export function run(n: string) { return alpha(1) + slugify(n); }
F
cat > src/api/legacy.ts <<'F'
import { zeta } from '../util/big';
import { gamma } from '../util/flags';
export function legacy(c: boolean) { return gamma(c); }
F
# A prop threaded through three components, plus the two shapes that must NOT fold with it: a
# declaration (the contract) and a prop whose VALUE changed at a call site.
mkdir -p src/ui
cat > src/ui/page-shell.tsx <<'F'
export const PageShell = ({ title }: { title: string }) => (
  <div>
    <TopBar title={title} items={LEGACY_ITEMS} />
    <Divider />
    <SideNav title={title} />
  </div>
);
F
cat > src/ui/top-bar.tsx <<'F'
interface Props {
  title: string;
}
export const TopBar = ({ title }: Props) => (
  <header>
    <UserMenu title={title} />
  </header>
);
F
cat > src/ui/user-menu.tsx <<'F'
interface Props {
  title: string;
}
export const UserMenu = ({ title }: Props) => <span>{title}</span>;
F
mkdir -p docs/plans docs/adr
printf '# plan\n\nstep one\n' > docs/plans/old-plan.md
printf '# ADR index\n\n| id | title |\n| -- | ----- |\n' > docs/adr/README.md
# An import block long enough that the `} from "…"` falls outside the hunk's context: the module
# cannot be named, but the direction still can.
cat > src/api/wide.ts <<'F'
import {
  a1,
  a2,
  a3,
  a4,
  a5,
  a6,
  a7,
  a8,
} from '../util/wide';
export function wide() { return a1 + a8; }
F
printf 'def f(x):\n    if x:\n        return 1\n    return 2\n' > script.py
printf '{"lockfileVersion": 3}\n' > package-lock.json
# A file that will receive a COMMENT-ONLY change, so the run produces a comment-only fold whose
# hunks must still be viewable from the fold card.
printf '// old note about totals\nexport function total(n: number[]) {\n  return n.reduce((a, b) => a + b, 0);\n}\n' > src/util/notes.ts
git add -A && git commit -qm init

git mv src/util/strings.ts src/util/text.ts
cat > src/util/big-a.ts <<'F'
export function alpha(a: number) { const x = a * 2; const y = x + 1; return y * 3; }
export function beta(b: string) { const parts = b.split(','); const trimmed = parts.map(p => p.trim()); return trimmed.join('|'); }
export function gamma(c: boolean) { if (c) { return 'yes-it-is-true'; } return 'no-it-is-false'; }
F
cat > src/util/big-b.ts <<'F'
export function delta(d: number[]) { return d.reduce((acc, n) => acc + n, 0) / Math.max(d.length, 1); }
export function epsilon(e: string) { return e.split('').reverse().join('') + '!'; }
export function zeta(z: number) { return Array.from({ length: z }, (_, i) => i * i); }
F
git rm -q src/util/big.ts
cat > src/api/users.ts <<'F'
import { slugify } from '../util/text';
import { alpha } from '../util/big-a';
// users api (handles persistence)
export function saveUser(name: string) {
  const id = slugify(name);
  db.upsert(id, name);
  return { id, value: alpha(1) };
}
export function format(x: { a: number; b: number }) {
  return [x.a, x.b];
}
F
cat > src/api/barrel.ts <<'F'
import {
  alpha,
  beta,
  slugify,
} from '../util/barrel';
export function run(n: string) { return alpha(1) + slugify(n); }
F
cat > src/api/legacy.ts <<'F'
import { gamma } from '../util/flags';
export function legacy(c: boolean) { return gamma(c); }
F
# `canEdit` is declared once and threaded down two levels; `items=` changes VALUE at the same call
# site and must survive as substantive.
cat > src/ui/page-shell.tsx <<'F'
export const PageShell = ({ title, canEdit }: { title: string; canEdit: boolean }) => (
  <div>
    <TopBar title={title} items={NEXT_ITEMS} />
    <Divider />
    <SideNav
      title={title}
      canEdit={canEdit}
    />
  </div>
);
F
cat > src/ui/top-bar.tsx <<'F'
interface Props {
  title: string;
  canEdit: boolean;
}
export const TopBar = ({
  title,
  canEdit,
}: Props) => (
  <header>
    <UserMenu
      title={title}
      canEdit={canEdit}
    />
  </header>
);
F
cat > src/ui/user-menu.tsx <<'F'
interface Props {
  title: string;
  canEdit: boolean;
}
export const UserMenu = ({ title }: Props) => <span>{title}</span>;
F
printf '# plan\n\nstep one\n\nstep two, added while implementing\n' > docs/plans/old-plan.md
printf '# ADR index\n\n| id | title |\n| -- | ----- |\n| [0007](0007-new-decision.md) | A new decision |\n' > docs/adr/README.md
printf '# 0007 New decision\n\nWe chose A over B.\n' > docs/adr/0007-new-decision.md
cat > src/api/wide.ts <<'F'
import {
  a0,
  a1,
  a2,
  a3,
  a4,
  a5,
  a6,
  a7,
  a8,
} from '../util/wide';
export function wide() { return a1 + a8; }
F
printf 'def f(x):\n    if x:\n        return 1\n        return 3\n    return 2\n' > script.py
printf '{"lockfileVersion": 3, "x": 1}\n' > package-lock.json
printf '// new note: totals ignore NaN\nexport function total(n: number[]) {\n  return n.reduce((a, b) => a + b, 0);\n}\n' > src/util/notes.ts
git add -A

OUT="$(bash "$S/collect-diff.sh" --staged | tail -1 | sed 's/^OUT=//')"
[ -f "$OUT/diff-model.json" ] || fail "no diff-model.json"
python3 - "$OUT" <<'PY'
import json, sys, os
m = json.load(open(os.path.join(sys.argv[1], "diff-model.json")))
def fail(x): print("FAIL:", x); sys.exit(1)
files = {f["path"]: f for f in m["files"]}
assert files["src/util/text.ts"]["status"] == "rename", files["src/util/text.ts"]
folds = {f["kind"]: f for f in m["folds"]}
assert "rename" in folds, "rename fold missing"
followers = folds["rename"]["items"][0]["followers"]
assert any("text" in f["detail"] for f in followers), f"import rewrite not attached to rename: {followers}"
assert "split" in folds, f"split not detected: {list(folds)}"
assert {t["path"] for t in folds["split"]["items"][0]["targets"]} == {"src/util/big-a.ts", "src/util/big-b.ts"}
assert "lockfile" in folds
cats = {h["category"] for h in files["src/api/users.ts"]["hunks"]}
assert "substantive" in cats, cats
assert files["script.py"]["whitespace_sensitive"] and files["script.py"]["substantive_hunks"] == 1
assert m["stats"]["noise_pct"] > 30, m["stats"]
# Import folds must state the DIRECTION they actually observed. A bare specifier added inside an
# existing `import { … }` block names no module on the changed line; that used to bucket it as
# "unused imports dropped in N files" over a diff of pure additions.
imports = {it["module"]: it for it in folds["import-rewrite"]["items"]}
add = imports.get("../util/barrel") or fail(f"barrel import not grouped by its module: {list(imports)}")
assert "now imported in 1 file" == add["verb"], add
assert add["added_in"] == ["src/api/barrel.ts"] and add["removed_in"] == [], add
drop = imports.get("../util/big") or fail(f"dropped import not grouped by its module: {list(imports)}")
assert "no longer imported in 1 file" == drop["verb"], drop
assert drop["removed_in"] == ["src/api/legacy.ts"] and drop["added_in"] == [], drop
assert not any("dropped" in it["detail"] and "src/api/barrel.ts" in it["detail"] for it in folds["import-rewrite"]["items"]), folds["import-rewrite"]
# Prop threading: pass-sites fold, the DECLARATION does not, and a value change at the same call
# site survives. The fold carries the flow (which component hands the prop to which).
thread = {it["prop"]: it for it in folds["prop-thread"]["items"]}
t = thread.get("canEdit") or fail(f"canEdit thread not folded: {list(thread)}")
assert t["kind"] == "added" and t["files"] == ["src/ui/page-shell.tsx", "src/ui/top-bar.tsx"], t
assert set(t["declared_in"]) == {"src/ui/top-bar.tsx", "src/ui/user-menu.tsx"}, t
edges = {(e["from"].split("/")[-1], e["to"]) for e in t["flow"]}
assert ("page-shell.tsx", "SideNav") in edges and ("top-bar.tsx", "UserMenu") in edges, t["flow"]
assert {e["to_file"] for e in t["flow"]} == {None, "src/ui/user-menu.tsx"}, t["flow"]
decl = [h for h in files["src/ui/top-bar.tsx"]["hunks"] if h["category"] == "substantive"]
assert decl, "the prop DECLARATION must stay substantive — it is the contract"
assert any(h["category"] == "substantive" for h in files["src/ui/page-shell.tsx"]["hunks"]), \
    "items={LEGACY_ITEMS} → {NEXT_ITEMS} at the same call site must NOT fold with the prop"
# Working notes fold as a file; an ADR does not.
notes = {it["file"] for it in folds["notes"]["items"]}
assert notes == {"docs/plans/old-plan.md"}, notes
assert files["docs/adr/0007-new-decision.md"]["noise_kind"] is None, "an ADR is never working notes"
# The index row pointing at THAT new ADR is bookkeeping.
reg = folds["registry"]["items"]
assert [it["file"] for it in reg] == ["docs/adr/README.md"] and reg[0]["target"] == "docs/adr/0007-new-decision.md", reg
# Module outside the hunk: unnamed, but never mis-signed.
unnamed = [it for it in folds["import-rewrite"]["items"] if not it["module"]]
assert len(unnamed) == 1 and unnamed[0]["files"] == ["src/api/wide.ts"], unnamed
assert unnamed[0]["verb"].startswith("imports added in 1 file"), unnamed[0]
sub = open(os.path.join(sys.argv[1], "substantive.diff")).read()
assert "db.upsert" in sub and "big-a.ts" not in sub.split("diff --git")[0]
assert "package-lock" not in sub
print("classification OK:", m["stats"])
PY

cat > "$OUT/report.json" <<'J'
{ "title": "Split util + upsert users", "intent": "Split big util, rename strings→text, persist users",
  "summary": "Renames the string helpers module, splits the oversized util file in two, and makes saveUser persist via db.upsert — a behaviour change beyond the refactor.",
  "confession": [ {"point":"Never ran the persistence path against a real db.","detail":"The test fake accepts any shape, so upsert's overwrite semantics are unverified."},
                  {"point":"The split point between big-a and big-b was a guess."} ],
  "how_to_check": [ {"id":"V1","feature":"Saving a user persists it","surface":"ui","where":"/users",
                     "setup":"Sign in.","steps":["Open /users.","Save a user that already exists."],
                     "expect":"The existing row is overwritten, not duplicated.",
                     "covered_by":"src/api/users.ts"},
                    {"id":"V2","feature":"Save user endpoint","surface":"api",
                     "steps":["Send the request.","Re-read the row."],"expect":"200 and one row.",
                     "request":{"method":"POST","path":"/api/users","headers":{"x-demo":"1"},
                                "body":{"id":1,"name":"a"},"note":"Needs a session cookie."}} ],
  "phases": [ {"id":"p1","title":"Module reshuffle","narrative":"Rename + split, imports follow.","files":["src/util/text.ts","src/util/big-a.ts","src/util/big-b.ts"]},
              {"id":"p2","title":"Persistence","narrative":"saveUser now writes to db.","files":["src/api/users.ts"]} ],
  "graph": { "nodes": [ {"id":"saveUser","label":"saveUser()","kind":"function","change":"modified","file":"src/api/users.ts"},
                        {"id":"db","label":"db.upsert","kind":"store","change":"unchanged"},
                        {"id":"bigA","label":"big-a.ts","kind":"module","change":"split","file":"src/util/big-a.ts"} ],
             "edges": [ {"from":"saveUser","to":"db","kind":"writes","label":"id, name"}, {"from":"saveUser","to":"bigA","kind":"imports"} ] },
  "findings": [ {"id":"C1","severity":"critical","title":"`saveUser` now persists via `db.upsert` — not in the refactor's scope",
                 "verify":"Was persistence intended here, and is upsert (overwrite) the right semantics?",
                 "why_human":"Intent and overwrite semantics are judgement calls; no test covers it.",
                 "file":"src/api/users.ts","lines":"6","hunks":["F1H1"],"tags":["divergence","data"]} ],
  "views": [ {"kind":"adoption","title":"saveUser adoption","root":{"label":"saveUser()","file":"src/api/users.ts","change":"modified"},"uses":[{"label":"big-a","file":"src/util/big-a.ts","change":"added"}]},
             {"kind":"flow","title":"Reshuffle","steps":[{"label":"rename strings→text","change":"renamed","file":"src/util/text.ts"},{"label":"split big","change":"split","then":[{"label":"big-a","file":"src/util/big-a.ts","change":"added"}]}]},
             {"kind":"screen","title":"Mock","screen":{"label":"Page","change":"modified","children":[{"slot":"header","label":"Header","change":"added","file":"src/api/users.ts"}]}} ],
  "folded": [], "unreviewed_notes": {"script.py":"indentation-sensitive; one added early return"} }
J
python3 - "$OUT" <<'PY'
import json, sys, os
d = sys.argv[1]; r = json.load(open(os.path.join(d, "report.json"))); m = json.load(open(os.path.join(d, "diff-model.json")))
r["folded"] = m["folds"]
hid = next(h["id"] for f in m["files"] if f["path"] == "src/api/users.ts" for h in f["hunks"] if h["category"] == "substantive")
r["findings"][0]["hunks"] = [hid]
json.dump(r, open(os.path.join(d, "report.json"), "w"))
PY
python3 "$S/check-report.py" "$OUT/report.json" || fail "check-report rejected a valid report"
python3 "$S/render-report.py" --dir "$OUT"
grep -q 'data-id="C1"' "$OUT/index.html" || fail "finding card missing"
grep -q 'db.upsert' "$OUT/index.html" || fail "hunk snippet not embedded"
grep -q 'class="mermaid"' "$OUT/index.html" || fail "mermaid map missing"
# Pictures before prose: map + views precede the phase walkthrough, and the TOC agrees with the page.
python3 - "$OUT/index.html" <<'PY' || fail "section order regressed"
import re, sys
h = open(sys.argv[1]).read()
body = h.split('<div class="toc"', 1)[1]
SECTIONS = ('id="summary"', 'id="view-1"', 'id="map"', 'id="phases"', 'id="findings"',
            'id="conversation"', 'id="unreviewed"', 'id="folded"')   # noise LAST
order = [s for s in SECTIONS if s in body]
pos = [body.index(s) for s in order]
ok = pos == sorted(pos) and body.index('id="map"') < body.index('id="phases"')
toc = h.split('<div class="toc"', 1)[1].split("</div>", 1)[0]
anchors = [a for a in re.findall(r'href="#([^"]+)"', toc)]
in_page = [a for a in anchors if f'id="{a}"' in body]
ok = ok and in_page == sorted(in_page, key=lambda a: body.index(f'id="{a}"'))
print("section order OK" if ok else f"FAIL order={order}")
sys.exit(0 if ok else 1)
PY
# Header shape (1.1.0): the ask is a subordinate lede, and confession is a skimmable list whose
# detail hides behind the point. A regression to one prose blob is silent otherwise — it still
# renders, it just stops being read, which is the failure this tool exists to prevent.
grep -q 'class="lede"' "$OUT/index.html" || fail "intent lede missing"
grep -q 'class="conf"' "$OUT/index.html" || fail "confession list missing"
grep -q 'The split point between big-a and big-b was a guess' "$OUT/index.html" || fail "confession point without detail not rendered"
grep -q '<summary>Never ran the persistence path' "$OUT/index.html" || fail "confession point with detail is not expandable"
grep -q 'upsert&#x27;s overwrite semantics are unverified' "$OUT/index.html" || fail "confession detail not rendered"
grep -q 'class="adoption"' "$OUT/index.html" && grep -q 'class="flow"' "$OUT/index.html" && grep -q 'class="screen"' "$OUT/index.html" || fail "views missing"
grep -q 'id="file-store"' "$OUT/index.html" && grep -q 'data-open="src/api/users.ts"' "$OUT/index.html" || fail "file store / chips missing"
# Every listed file opens its own diff (1.1.0). Phase lists were plain text before, which is the
# one place a reader is handed filenames and then given no way to look at them.
grep -q 'class="fpath" data-open="src/util/text.ts"' "$OUT/index.html" || fail "phase file paths are not clickable"
# How to check: cards render, the API one is runnable, and the Postman collection is real JSON
# carrying a {{base}} variable rather than a host baked in at render time.
grep -q 'id="check"' "$OUT/index.html" || fail "how-to-check section missing"
grep -q 'Save a user that already exists' "$OUT/index.html" || fail "check steps missing"
grep -q 'data-act="curl"' "$OUT/index.html" && grep -q 'data-act="send"' "$OUT/index.html" || fail "api run controls missing"
grep -q 'id="dl-postman"' "$OUT/index.html" || fail "postman download missing"
grep -q 'class="ck-done"' "$OUT/index.html" || fail "verified checkbox missing"
grep -q 'class="ck-mark"><textarea placeholder=' "$OUT/index.html" || fail "check note box missing"
grep -q 'id="ck-count" data-total="2"' "$OUT/index.html" || fail "verified counter missing"
python3 - "$OUT/index.html" <<'PY' || fail "postman collection is not usable"
import json, re, sys
h = open(sys.argv[1]).read()
coll = json.loads(re.search(r'id="postman-store">(.*?)</script>', h, re.S).group(1).replace("<\\/", "</"))
items = coll["item"]
ok = (len(items) == 1 and items[0]["request"]["method"] == "POST"
      and items[0]["request"]["url"]["raw"] == "{{base}}/api/users"
      and json.loads(items[0]["request"]["body"]["raw"])["id"] == 1
      and any(v["key"] == "base" for v in coll["variable"]))
store = json.loads(re.search(r'id="check-store">(.*?)</script>', h, re.S).group(1).replace("<\\/", "</"))
ok = ok and set(store) == {"V2"}          # only the runnable card is in the run store
print("postman + check store OK" if ok else f"FAIL {json.dumps(coll)[:400]}")
sys.exit(0 if ok else 1)
PY
grep -q 'class="fpath" data-open="src/util/big-a.ts"' "$OUT/index.html" || fail "folded-noise file paths are not clickable"
# A fold entry opens ITS OWN hunk, not the file's substantive diff — and that hunk must exist in the
# store, since the file store carries substantive hunks only. Without both, the moved import or the
# reworded comment a fold card is about renders nowhere in the report.
python3 - "$OUT/index.html" <<'PY' || fail "folded hunks are not viewable"
import json, re, sys
h = open(sys.argv[1]).read()
store = json.loads(re.search(r'id="hunk-store">(.*?)</script>', h, re.S).group(1).replace("<\\/", "</"))
refs = re.findall(r'data-open-hunks="([^"]+)"', h)
ids = {i for r in refs for i in r.split(",")}
missing = sorted(ids - set(store))
ok = bool(refs) and not missing and all(store.values())
print("fold hunks viewable" if ok else f"FAIL refs={refs[:3]} missing={missing}")
sys.exit(0 if ok else 1)
PY
# …and the page must print the model's direction, not re-derive one (it had its own copy of the
# label logic, so a fold of pure additions read "unused imports dropped").
grep -q '← now imported in 1 file' "$OUT/index.html" || fail "import fold: added direction not rendered"
# …and it must come from the MODEL, not from report.json's copy of it — a stale copy is how the
# page kept rendering old fold labels after the classifier was fixed.
export S
python3 - "$OUT" <<'PY' || fail "stale report.folded won over the live model"
import json, os, subprocess, sys
d = sys.argv[1]; p = os.path.join(d, "report.json"); r = json.load(open(p))
orig = open(p).read()
r["folded"] = [{"kind": "import-rewrite", "title": "STALE COPY", "count": 1,
                "items": [{"file": "x", "module": "x", "files": ["x"], "hunk_ids": [], "verb": "STALE VERB", "detail": "x"}]}]
open(p, "w").write(json.dumps(r))
subprocess.run([sys.executable, os.environ["S"] + "/render-report.py", "--dir", d], check=True, capture_output=True)
html = open(os.path.join(d, "index.html")).read()
open(p, "w").write(orig)
sys.exit(0 if "STALE VERB" not in html and "now imported in 1 file" in html else 1)
PY
python3 "$S/render-report.py" --dir "$OUT" >/dev/null   # restore the real page for later assertions
grep -q '← no longer imported in 1 file' "$OUT/index.html" || fail "import fold: removed direction not rendered"
! grep -q 'unused imports dropped' "$OUT/index.html" || fail "import fold: stale removal label rendered"
# The prop fold draws the flow, and every node in it is a live control.
python3 - "$OUT/index.html" <<'PY' || fail "prop-thread flow tree not rendered as live nodes"
import re, sys
h = open(sys.argv[1]).read()
i = h.find("Props threaded through components")
seg = h[i:i + 4000] if i >= 0 else ""
ok = (i >= 0
      and "new prop threaded through 2 files" in seg
      and "&lt;UserMenu&gt;" in seg and "&lt;SideNav&gt;" in seg
      and "└─" in seg
      and 'data-open="src/ui/user-menu.tsx"' in seg              # a component in the diff opens its file
      and '<span class="dim">&lt;SideNav&gt;</span>' in seg      # one that is not stays inert, never a dead control
      and re.search(r'data-open-hunks="[^"]+" data-open-label="src/ui/page-shell\.tsx"', seg))  # pass-site opens its hunk
print("prop flow OK" if ok else f"FAIL: {seg[:400]!r}")
sys.exit(0 if ok else 1)
PY
# The gut-flag wiring must not swallow the row's Collapse button (it did: `.unrev button` matched
# both, and the later assignment replaced the collapse handler outright).
grep -q "\$\$('.unrev button\[data-file\]')" "$OUT/index.html" || fail "gut-flag selector is not scoped to the flag buttons"
python3 - "$OUT/index.html" <<'PY' || fail "clickable paths are not all backed by the file store"
import json, re, sys
html = open(sys.argv[1]).read()
store = json.loads(re.search(r'<script type="application/json" id="file-store">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
missing = sorted({p for p in re.findall(r'data-open="([^"]+)"', html)} - set(store))
print("FAIL, dead controls:", missing) if missing else print("all data-open paths resolve")
sys.exit(1 if missing else 0)
PY
grep -q 'Renamed files' "$OUT/index.html" || fail "fold card missing"
grep -q 'row fold-row' "$OUT/index.html" && grep -A3 'row fold-row' "$OUT/index.html" | grep -q 'row-body' || fail "everything-else rows not expandable"

# Snapshots: a report read twice must be able to say what moved between the readings.
python3 "$S/snapshots.py" list --dir "$OUT" | grep -q "001-" || fail "the render did not record a snapshot"
python3 "$S/snapshots.py" diff --dir "$OUT" | grep -q "Nothing changed" || fail "an unchanged report must report no delta"
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
python3 "$S/snapshots.py" list --dir "$OUT" | grep -cq "^" && [ "$(python3 "$S/snapshots.py" list --dir "$OUT" | wc -l)" = "1" ] \
  || fail "an unchanged re-render must not pile up snapshots"
python3 - "$OUT" <<'PY' || fail "could not stage the second snapshot"
import json, os, sys
d = sys.argv[1]; p = os.path.join(d, "report.json"); r = json.load(open(p))
r["findings"] = [dict(r["findings"][0], id="M1", severity="medium",
                      title="A different claim entirely about the same file")]
r["how_to_check"][0]["steps"] = ["Open /users.", "Save a user that already exists.", "Reload."]
json.dump(r, open(p, "w"))
PY
# …and REAL code moves between the two readings, which is what the delta page is for.
printf 'export function afterTheFirstRead(x: number) {\n  return x * 2;\n}\n' >> src/api/users.ts
git add -A
bash "$S/collect-diff.sh" --staged --out "$OUT" >/dev/null
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
DELTA="$(python3 "$S/snapshots.py" diff --dir "$OUT" --from first --to last)"
case "$DELTA" in *"Findings changed"*) ;; *) fail "a re-worded finding must read as changed, not as one gone + one new: $DELTA" ;; esac
case "$DELTA" in *"Checks re-written"*) ;; *) fail "an edited check must be called out (its tick was dropped): $DELTA" ;; esac
grep -q "Since you last read this" "$OUT/index.html" || fail "the delta is not rendered on the page"
grep -q "a tick on these was dropped" "$OUT/index.html" || fail "the page must say why a tick vanished"
python3 "$S/snapshots.py" list --dir "$OUT" | grep -q "002-" || fail "the changed render did not snapshot"
# The delta is also a page of its own — one per earlier snapshot, with a picker across them.
[ -f "$OUT/delta.html" ] && [ -f "$OUT/delta-001.html" ] || fail "no delta page was written"
grep -q "what moved since" "$OUT/delta-001.html" || fail "the delta page has no header"
grep -q 'href="index.html"' "$OUT/delta-001.html" || fail "the delta page must link back to the full report"
# It is a REAL report over the range between the two readings — its own diff, folds and map — not a
# list of what moved. Built by running the ordinary pipeline against the snapshot's frozen tree.
[ -f "$OUT/deltas/001/diff-model.json" ] || fail "no code delta was collected between the snapshots"
python3 - "$OUT/delta-001.html" "$OUT" <<'PY' || fail "the delta page is not a scoped, live report"
import json, os, re, sys
h, d = open(sys.argv[1]).read(), sys.argv[2]
store = json.loads(re.search(r'id="file-store">(.*?)</script>', h, re.S).group(1).replace("<\\/", "</"))
dead = sorted(set(re.findall(r'data-open="([^"]+)"', h)) - set(store))
model = json.load(open(os.path.join(d, "deltas/001/diff-model.json")))
full = json.load(open(os.path.join(d, "diff-model.json")))
narrower = {f["path"] for f in model["files"]} < {f["path"] for f in full["files"]}
# The full-report sections only a real render emits, and code for the files in THIS range:
# a `.diff` block lives inside the file-store JSON, so look for it there, not in the markup.
# Matched on the opening tag only — the element carries attributes (`data-file`, for the line
# gutter), and pinning the whole tag made this fail on a change that added one.
has_code = ('id="folded"' in h and 'id="unreviewed"' in h
            and any('<div class="diff"' in v.get("html", "") for v in store.values()))
scoped = set(store) == {f["path"] for f in model["files"]}
ok = not dead and narrower and has_code and scoped
print("delta page OK" if ok else f"FAIL dead={dead} narrower={narrower} code={has_code} scoped={scoped}")
sys.exit(0 if ok else 1)
PY
# A third state: now TWO earlier snapshots exist, so the reader can pick which reading to diff from.
python3 - "$OUT" <<'PY'
import json, os, sys
d = sys.argv[1]; p = os.path.join(d, "report.json"); r = json.load(open(p))
r["findings"].append(dict(r["findings"][0], id="L1", severity="low", title="A third-pass note"))
json.dump(r, open(p, "w"))
PY
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
[ -f "$OUT/delta-002.html" ] || fail "a second earlier snapshot produced no page"
for f in delta-001 delta-002; do   # -o, not -c: the picker is one line, and `grep -c` counts LINES
  [ "$(grep -o 'class="pick' "$OUT/$f.html" | wc -l)" -ge 3 ] || fail "$f has no picker across both snapshots"
done
grep -q "since 002" "$OUT/delta-001.html" || fail "the picker must offer the other snapshot"
echo "snapshots OK"
git checkout -q "$OUT/report.json" 2>/dev/null || true

# budget violation must fail
python3 - "$OUT" <<'PY'
import json, sys, os, copy
d = sys.argv[1]; r = json.load(open(os.path.join(d, "report.json")))
for i in range(2, 6): r["findings"].append(dict(r["findings"][0], id=f"C{i}"))
json.dump(r, open(os.path.join(d, "bad.json"), "w"))
PY
if python3 "$S/check-report.py" "$OUT/bad.json" >/dev/null 2>&1; then fail "check-report accepted 5 criticals"; fi

# A `convention` finding lives or dies on its citation: it is the only thing separating "the rule
# says X and two siblings do X" from "I'd have written it differently", and the second one costs
# the report its credibility.
python3 - "$OUT" <<'PY'
import json, os, sys
d = sys.argv[1]; r = json.load(open(os.path.join(d, "report.json")))
base = dict(r["findings"][0], id="M1", severity="medium", tags=["convention"])
def w(name, **kw): json.dump(dict(r, findings=[dict(base, **kw)]), open(os.path.join(d, name), "w"))
w("conv-none.json")                                                     # no citation at all
w("conv-ghost.json", diverges_from=["docs/nope-does-not-exist.md:3"])   # cites a file that is not there
w("conv-one.json", diverges_from=["src/util/notes.ts:2"])               # one neighbour, no rule
w("conv-rule.json", diverges_from=[{"ref": "docs/adr/0007-new-decision.md", "why": "we chose A"}])
w("conv-two.json", diverges_from=["src/util/notes.ts:2", "src/util/text.ts:1"])
PY
for bad in conv-none conv-ghost conv-one; do
  if python3 "$S/check-report.py" "$OUT/$bad.json" >/dev/null 2>&1; then fail "check-report accepted $bad"; fi
done
# NB `cmd | grep` under pipefail reports the FAILING cmd, not grep — capture, then match.
CONV_MSG="$(python3 "$S/check-report.py" "$OUT/conv-none.json" 2>&1 || true)"
case "$CONV_MSG" in *diverges_from*) ;; *) fail "the rejection must name the missing field: $CONV_MSG" ;; esac
python3 "$S/check-report.py" "$OUT/conv-rule.json" >/dev/null || fail "a cited written rule must pass"
python3 "$S/check-report.py" "$OUT/conv-two.json" >/dev/null || fail "two neighbours must pass"
# …and the citation reaches the page, next to the claim.
cp "$OUT/report.json" "$OUT/report-real.json"; cp "$OUT/conv-rule.json" "$OUT/report.json"
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q "Diverges from" "$OUT/index.html" && grep -q 'data-loc="docs/adr/0007-new-decision.md"' "$OUT/index.html" \
  && grep -q "we chose A" "$OUT/index.html" || fail "diverges_from not rendered on the finding"
mv "$OUT/report-real.json" "$OUT/report.json"; python3 "$S/render-report.py" --dir "$OUT" >/dev/null
echo "convention citations OK"

# --- Two readings: provenance + the divergence between the passes (1.8.0) --------------------
# The value of a second, independent pass is knowing which findings the author did NOT see coming.
# A merged list destroys that, so the split has to survive validation AND reach the page.
cp "$OUT/report.json" "$OUT/report-single.json"
python3 - "$OUT" <<'PY'
import json, os, sys
d = sys.argv[1]; r = json.load(open(os.path.join(d, "report.json")))
base = r["findings"][0]
r["findings"] = [
    dict(base, id="C1", severity="critical", provenance="fresh", title="Cold pass caught this one"),
    dict(base, id="M1", severity="medium", provenance="both", title="Both passes caught this one"),
]
r["confession"] = [
    {"point": "I could not test the retry path.", "corroborated_by": ["M1"]},
    {"point": "The fallback in resolveModel is a guess.", "corroborated_by": []},
]
json.dump(r, open(os.path.join(d, "two-pass.json"), "w"))
# Partly-tagged: an untagged finding is indistinguishable from one the cold pass missed, which
# inverts the meaning of the whole section. Must be rejected.
half = json.loads(json.dumps(r)); half["findings"][1].pop("provenance")
json.dump(half, open(os.path.join(d, "half-tagged.json"), "w"))
# A corroborated_by pointing at a finding that does not exist would cite an id the reader cannot find.
ghost = json.loads(json.dumps(r)); ghost["confession"][0]["corroborated_by"] = ["C9"]
json.dump(ghost, open(os.path.join(d, "prov-ghost.json"), "w"))
bad = json.loads(json.dumps(r)); bad["findings"][0]["provenance"] = "implementer"
json.dump(bad, open(os.path.join(d, "prov-bad.json"), "w"))
PY
python3 "$S/check-report.py" "$OUT/two-pass.json" >/dev/null || fail "a valid two-pass report must pass"
for bad in half-tagged prov-ghost prov-bad; do
  if python3 "$S/check-report.py" "$OUT/$bad.json" >/dev/null 2>&1; then fail "check-report accepted $bad"; fi
done
HALF_MSG="$(python3 "$S/check-report.py" "$OUT/half-tagged.json" 2>&1 || true)"
case "$HALF_MSG" in *provenance*) ;; *) fail "the rejection must name provenance: $HALF_MSG" ;; esac
# The section renders, names all three groups, and the TOC entry points at a section that exists.
cp "$OUT/two-pass.json" "$OUT/report.json"; python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'id="two-readings"' "$OUT/index.html" || fail "no Two readings section on a two-pass report"
grep -q 'href="#two-readings"' "$OUT/index.html" || fail "Two readings missing from the TOC"
grep -q "The author did not flag these" "$OUT/index.html" || fail "blind spots group missing"
grep -q "Declared, but nothing was found there" "$OUT/index.html" || fail "uncorroborated-doubt group missing"
grep -q "Both arrived at these" "$OUT/index.html" || fail "agreement group missing"
grep -q 'class="prov prov-fresh"' "$OUT/index.html" || fail "provenance badge missing from the finding card"
# A finding BOTH passes raised is corroboration, not a blind spot — it must not appear in the first
# group, or the section that exists to say "the author missed this" says it about something they did
# not miss. Asserted on the section's own slice, since M1's title appears on its card too.
python3 - "$OUT/index.html" <<'PY' || fail "a corroborated finding is listed as a blind spot"
import re, sys
h = open(sys.argv[1]).read()
sec = h.split('id="two-readings"', 1)[1].split("</section>", 1)[0]
# Slice to the group's own </ul>: the first </div> closes the inner .empty blurb, not the group.
blind = sec.split("The author did not flag these", 1)[1].split("</ul>", 1)[0]
assert "Cold pass caught this one" in blind, "the fresh-only finding is missing from blind spots"
assert "Both passes caught this one" not in blind, "a corroborated finding leaked into blind spots"
print("two readings OK")
PY
# …and a single-pass report renders NO section and NO nav entry pointing at nothing.
cp "$OUT/report-single.json" "$OUT/report.json"; python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'id="two-readings"' "$OUT/index.html" && fail "single-pass report must not render Two readings"
grep -q 'href="#two-readings"' "$OUT/index.html" && fail "single-pass report must not link Two readings"
echo "two-pass provenance OK"

# feedback round trip
printf '%s\n' '{"ts":"2026-01-01T00:00:00Z","type":"less","finding":"C1","report_id":"x"}' '{"ts":"2026-01-01T00:00:01Z","type":"gut_flag","file":"script.py","report_id":"x"}' > "$OUT/feedback.jsonl"
python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT" | grep -q "ingested 2" || fail "ingest"
python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT" | grep -q "ingested 0" || fail "ingest dedupe"
python3 "$S/feedback.py" question "why upsert?" --dir "$OUT" --finding C1 >/dev/null
python3 "$S/feedback.py" digest | grep -q "over-rated" || fail "digest"
python3 "$S/feedback.py" push | grep -q "no shared backend" || fail "push without backend"

# serve: the token gate, then the round trip through it.
# The negative rows come first and carry a pristine positive control below them: a gate that
# refuses everything passes every negative row, so the 403s prove nothing on their own.
python3 "$S/serve.py" "$OUT" --port 8799 --token testtoken >"$T/serve.log" 2>&1 & SP=$!; sleep 0.7
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
[ "$(code localhost:8799/raw.diff)" = 403 ] || { kill $SP; fail "serve: unauthenticated GET must be 403"; }
[ "$(code 'localhost:8799/?k=wrongtoken')" = 403 ] || { kill $SP; fail "serve: wrong token must be 403"; }
[ "$(code -X POST localhost:8799/feedback -d '{"events":[{"type":"smuggled"}]}')" = 403 ] || { kill $SP; fail "serve: unauthenticated POST must be 403"; }
# the URL serve.py prints works, and hands out the cookie the page's relative requests ride
curl -sf -c "$T/jar" -o /dev/null 'localhost:8799/?k=testtoken' || { kill $SP; fail "serve: printed token URL must work"; }
grep -q dc_report "$T/jar" || { kill $SP; fail "serve: token URL must set the cookie"; }
curl -sf -b "$T/jar" -X POST localhost:8799/feedback -d '{"events":[{"ts":"2026-01-01T00:00:02Z","type":"more","finding":"C1"}]}' | grep -q '"stored": 1' || { kill $SP; fail "serve POST"; }
curl -sf -b "$T/jar" -o "$T/get.html" localhost:8799/ && grep -q '<title>' "$T/get.html" || { kill $SP; fail "serve GET"; }
# a dict `events` iterates to its KEYS, so this used to append the bare string "x" to the store and
# break every consumer that expects an object per line. Authenticated, so it is the shape check —
# not the token gate — being tested here.
[ "$(curl -s -o /dev/null -w '%{http_code}' -b "$T/jar" -X POST localhost:8799/feedback -d '{"events":{"x":1}}')" = 400 ] || { kill $SP; fail "serve: malformed events must be 400"; }
[ "$(curl -s -o /dev/null -w '%{http_code}' -b "$T/jar" -X POST localhost:8799/feedback -d '{"events":["bare string"]}')" = 400 ] || { kill $SP; fail "serve: non-object event must be 400"; }
kill $SP; wait $SP 2>/dev/null || true
grep -q '"type": "more"' "$OUT/feedback.jsonl" || fail "feedback not appended"
grep -q smuggled "$OUT/feedback.jsonl" && fail "serve: refused POST still reached the store"
grep -qx '"x"' "$OUT/feedback.jsonl" && fail "serve: malformed events wrote a bare string to the store"
python3 -c "
import json,sys
bad=[l for l in open('$OUT/feedback.jsonl') if l.strip() and not isinstance(json.loads(l), dict)]
sys.exit('non-object lines in the store: %r' % bad[:3]) if bad else print('feedback store shape OK')" || fail "feedback store shape"
# --no-token is the documented escape hatch; it must genuinely serve open
python3 "$S/serve.py" "$OUT" --port 8799 --no-token >"$T/serve2.log" 2>&1 & SP=$!; sleep 0.7
curl -sf -o /dev/null localhost:8799/raw.diff || { kill $SP; fail "serve --no-token must serve openly"; }
kill $SP; wait $SP 2>/dev/null || true
echo "serve token gate OK"

# tree-hash: the pin's content hash must be stable, and must move for any edit that ships
TH="$T/th"; rm -rf "$TH"; mkdir -p "$TH/a/sub"
printf 'hello\n' > "$TH/a/f.txt"; printf 'x\n' > "$TH/a/sub/g.py"; chmod +x "$TH/a/sub/g.py"
cp -a "$TH/a" "$TH/b"
BASE=$(python3 "$S/tree-hash.py" "$TH/a")
[ "$(python3 "$S/tree-hash.py" "$TH/b")" = "$BASE" ] || fail "tree-hash: identical copy must hash the same"
printf 'hello!\n' > "$TH/b/f.txt"
[ "$(python3 "$S/tree-hash.py" "$TH/b")" != "$BASE" ] || fail "tree-hash: blind to a content edit"
cp -a "$TH/a" "$TH/c"; chmod -x "$TH/c/sub/g.py"
[ "$(python3 "$S/tree-hash.py" "$TH/c")" != "$BASE" ] || fail "tree-hash: blind to an exec-bit change"
cp -a "$TH/a" "$TH/d"; mkdir -p "$TH/d/__pycache__"; printf 'junk' > "$TH/d/__pycache__/x.pyc"
[ "$(python3 "$S/tree-hash.py" "$TH/d")" = "$BASE" ] || fail "tree-hash: __pycache__ must not move the hash"
cp -a "$TH/a" "$TH/e"; mv "$TH/e/f.txt" "$TH/e/renamed.txt"
[ "$(python3 "$S/tree-hash.py" "$TH/e")" != "$BASE" ] || fail "tree-hash: blind to a rename"
cp -a "$TH/a" "$TH/g"; rm "$TH/g/sub/g.py"
[ "$(python3 "$S/tree-hash.py" "$TH/g")" != "$BASE" ] || fail "tree-hash: blind to a deletion"
echo "tree-hash OK"
# comments: ask → list → answer → rendered
printf '%s\n' '{"ts":"2026-01-01T00:00:03Z","type":"comment","id":"cabc","text":"what is this?","anchor":{"text":"saveUser","context":"…saveUser now persists…","section":"summary","finding":null}}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q '\[cabc\] OPEN' || fail "comments list"
python3 "$S/feedback.py" answer --dir "$OUT" --id cabc --improvement "name the persistence call in the summary" --text "It upserts via \`db.upsert\`." | grep -q "answered cabc" || fail "answer"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q 'no open comments' || fail "answered thread still open"
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'id="t-cabc"' "$OUT/index.html" && grep -q '<code>db.upsert</code>' "$OUT/index.html" || fail "thread/answer not rendered"
python3 "$S/feedback.py" digest | grep -q 'improvement: name the persistence' || fail "digest improvement"
# line comments: every diff line carries a real new-side number, and a comment left on one reports
# the location rather than only the quoted text. The numbers are what make the thread openable —
# a gutter that renders an index into the snippet would look identical here and be useless.
grep -q 'class="ln" role="button"' "$OUT/index.html" || fail "diff lines have no comment gutter"
# The sheet must own its scroll. Reported from a phone: a diff SHORTER than the sheet has no inner
# scroll, so the drag chained to the document and the report slid about behind a sheet that looked
# frozen. Two halves, and both must hold — the containment AND the page lock. The third assertion is
# the one that actually ratchets: a future opener that sets `.show` itself would skip `lockPage()`
# and silently reintroduce this, which is invisible to the other two.
python3 - "$OUT" <<'PY' || fail "the file sheet does not own its scroll (background would scroll instead)"
import re, sys
h = open(sys.argv[1] + "/index.html", encoding="utf-8").read()
sb = re.search(r'\.sheet-b\{([^}]*)\}', h)
assert sb, "no .sheet-b rule"
assert "overscroll-behavior:contain" in sb.group(1), "sheet body does not contain its overscroll"
assert "min-height:0" in sb.group(1), "sheet body cannot shrink below its content in the flex column"
assert re.search(r'\.diff\{[^}]*overscroll-behavior:contain', h), "diffs do not contain their overscroll"
assert "lockPage()" in h and "unlockPage()" in h, "the page behind the sheet is never locked"
# Every place that shows the sheet goes through showSheet(), which is what carries the lock.
bare = [m for m in re.findall(r'\n[^\n]*sheet\.classList\.add\([\'"]show[\'"]\)[^\n]*', h)
        if "showSheet" not in m]
assert not bare, f"a sheet opener bypasses showSheet() and so never locks the page: {bare}"
print("sheet scroll containment OK")
PY
python3 - "$OUT" <<'PY' || fail "gutter line numbers are not real new-side numbers"
import re, sys, html
h = open(sys.argv[1] + "/index.html", encoding="utf-8").read()
# Pick one hunk from the rendered page and re-derive its numbering from its own @@ header.
m = re.search(r'<div class="diff" data-file="[^"]+"><div class="hh">[^<]*?-\d+(?:,\d+)? \+(\d+)', h)
assert m, "no diff with an @@ header rendered"
start = int(m.group(1))
seg = h[m.end():]
first = re.search(r'data-n="(\d+)" data-side="(new|old)"', seg)
assert first, "no numbered line after the header"
# The first line of a hunk is context or an addition often enough to assert the common case; a
# leading deletion is old-side and legitimately differs, so only the new-side claim is checked.
if first.group(2) == "new":
    assert int(first.group(1)) == start, f"first new-side line {first.group(1)} != @@ start {start}"
print("gutter numbering OK")
PY
printf '%s\n' '{"ts":"2026-01-01T00:00:07Z","type":"comment","id":"cdef","text":"why the cast?","anchor":{"text":"const x = y as any","context":"a\nb\nc","section":"findings","finding":"C1","file":"src/api/users.ts","line":42,"side":"new","hunk":"F3H1"}}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q 'at:        src/api/users.ts:42' || fail "line comment does not report its location"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q '\[F3H1\]' || fail "line comment does not report its hunk"
python3 "$S/feedback.py" answer --dir "$OUT" --id cdef --improvement "explain the cast in the finding" --text "It is narrowed downstream." >/dev/null || fail "answer a line comment"
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'src/api/users.ts:42' "$OUT/index.html" || fail "line-comment thread does not show path:line"
# notes: check ticks + "didn't work" text are readable. `comments` is blind to both by design, so a
# reader's note used to sit unread while the tooling reported "no open comments".
printf '%s\n' '{"ts":"2026-01-01T00:00:04Z","type":"check_verified","check":"V1"}' >> "$OUT/feedback.jsonl"
printf '%s\n' '{"ts":"2026-01-01T00:00:05Z","type":"check_note","check":"V2","text":"401 instead of 200"}' >> "$OUT/feedback.jsonl"
printf '%s\n' '{"ts":"2026-01-01T00:00:06Z","type":"note","finding":"C1","text":"intended, ship it"}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" notes --dir "$OUT" | grep -q 'verified: V1' || fail "notes: verified tick not reported"
python3 "$S/feedback.py" notes --dir "$OUT" | grep -q '401 instead of 200' || fail "notes: check note not reported"
python3 "$S/feedback.py" notes --dir "$OUT" | grep -q 'intended, ship it' || fail "notes: finding note not reported"
printf '%s\n' '{"ts":"2026-01-01T00:00:07Z","type":"undo","undo":"check_verified","check":"V1"}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" notes --dir "$OUT" | grep -q 'un-marked again: V1' || fail "notes: untick not reported"
# A note typed into a finding card is a THREAD, and must be visible everywhere a comment is —
# `comments` (one entry point, so it cannot be forgotten again), the card's own box after a
# re-render, and the Conversation section. A reader who left six notes could find none of them and
# concluded they had been dropped; they had been stored the whole time.
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q '\[note-C1\] OPEN · note' || fail "a card note is invisible to \`comments\`"
# On a finding the CURRENT report still renders (an earlier block re-worded C1 into M1), so the
# replay-into-the-box assertion has a card to land in.
# The note carries the finding's CONTENT key, which is what the renderer matches on — an event with
# only an id cannot be placed, because ids get reassigned when the report is re-authored.
python3 - "$OUT" "$S" <<'PY'
import json, os, sys
d, s = sys.argv[1], sys.argv[2]
sys.path.insert(0, s)
from report_keys import finding_key
r = json.load(open(os.path.join(d, "report.json")))
m1 = next(f for f in r["findings"] if f["id"] == "M1")
with open(os.path.join(d, "feedback.jsonl"), "a") as fh:
    fh.write(json.dumps({"ts": "2026-01-01T00:00:07Z", "type": "note", "finding": "M1",
                         "finding_key": finding_key(m1), "text": "replayed into the box"}) + "\n")
PY
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'replayed into the box</textarea>' "$OUT/index.html" || fail "a card note is not replayed into its box on re-render"
# The thread id is the CONTENT key, so an answer stays attached to the note it answered rather than
# to whatever finding later inherits the id. `comments` prints the id to answer with — use that,
# exactly as the operator would, instead of assuming its shape.
NOTE_ID="$(python3 "$S/feedback.py" comments --dir "$OUT" --json | python3 -c "
import json,sys
rows=[r for r in json.load(sys.stdin) if r['text']=='replayed into the box']
print(rows[0]['id'] if rows else '')")"
[ -n "$NOTE_ID" ] || fail "a card note is missing from the comments listing"
grep -q "id=\"t-$NOTE_ID\"" "$OUT/index.html" || fail "a card note is missing from the Conversation section"
python3 "$S/feedback.py" answer --dir "$OUT" --id "$NOTE_ID" --improvement "state the intent in the finding" --text "Agreed — noted." | grep -q "answered $NOTE_ID" || fail "a card note cannot be answered"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q "$NOTE_ID" && fail "an answered note is still open"
# A finding id is a POSITION in a severity-sorted list, not an identity. Re-authoring the report
# hands `M1` to a different claim, and a note replayed by id then appears under a finding the reader
# never wrote it about. That shipped: five of seven cards carried someone else's note. The note must
# follow the CONTENT, and must not be silently re-attached when its finding is gone.
python3 - "$OUT" "$S" <<'PY' || fail "a note re-attaches to a DIFFERENT finding that inherited its id"
import json, os, subprocess, sys
d, s = sys.argv[1], sys.argv[2]
sys.path.insert(0, s)
from report_keys import finding_key
r = json.load(open(os.path.join(d, "report.json")))
target = r["findings"][0]
# The note the reader wrote, keyed to the finding as it was at the time.
with open(os.path.join(d, "feedback.jsonl"), "a") as fh:
    fh.write(json.dumps({"ts": "2026-01-02T00:00:00Z", "type": "note", "finding": target["id"],
                         "finding_key": finding_key(target), "text": "NOTE ABOUT THE ORIGINAL CLAIM"}) + "\n")
subprocess.run(["python3", os.path.join(s, "render-report.py"), "--dir", d], check=True, capture_output=True)
h = open(os.path.join(d, "index.html"), encoding="utf-8").read()
assert "NOTE ABOUT THE ORIGINAL CLAIM" in h, "the note vanished from its own finding"
# Now re-author: the SAME id, a completely different claim, at a different place.
r["findings"][0] = dict(target, title="An entirely different claim about something else",
                        file=r["findings"][-1]["file"])
json.dump(r, open(os.path.join(d, "report.json"), "w"))
subprocess.run(["python3", os.path.join(s, "render-report.py"), "--dir", d], check=True, capture_output=True)
h = open(os.path.join(d, "index.html"), encoding="utf-8").read()
card = h.split('data-id="' + target["id"] + '"', 1)[1].split("</textarea>", 1)[0]
assert "NOTE ABOUT THE ORIGINAL CLAIM" not in card, "the note re-attached to the finding that inherited the id"
# …and it is not lost either: it surfaces as a note on an earlier version.
assert "NOTE ABOUT THE ORIGINAL CLAIM" in h, "the orphaned note was dropped instead of surfaced"
assert "no longer in the report" in h, "an orphaned note must say which report it belongs to"
listing = subprocess.run(["python3", os.path.join(s, "feedback.py"), "comments", "--dir", d],
                         capture_output=True, text=True).stdout
assert "earlier version" in listing, f"`comments` must flag an orphaned note, got:\n{listing}"
print("finding-note identity OK")
PY
# Undelivered feedback must be loud, not a muted count: the events are safe in localStorage but
# Claude has not seen them, and the reader cannot tell those two states apart by looking.
grep -q 'NOT SENT' "$OUT/index.html" || fail "the footer never shouts about unsent feedback"
grep -q '\.footer\.warn{' "$OUT/index.html" || fail "no red state for unsent feedback"
# A tick belongs to the REPORT, not to one browser and not to a positional id. It must survive a
# re-render, and it must NOT survive an edit to the very steps the reader followed.
python3 - "$OUT" "$S" <<'PY' || fail "check ticks do not survive a re-render (or survive an edit they should not)"
import json, os, re, subprocess, sys
d, S = sys.argv[1], sys.argv[2]
html = open(os.path.join(d, "index.html")).read()
keys = dict(re.findall(r'class="card ck" data-id="(V\d+)" data-key="([0-9a-f]+)"', html))
if len(keys) < 2: print("FAIL: check cards carry no content key", keys); sys.exit(1)
# The reader ticks V2 in the page: the event carries the content key, and the server stores it.
with open(os.path.join(d, "feedback.jsonl"), "a") as fh:
    fh.write(json.dumps({"ts": "2026-01-01T00:00:09Z", "type": "check_verified",
                         "check": "V2", "check_key": keys["V2"]}) + "\n")
def rendered():
    subprocess.run([sys.executable, os.path.join(S, "render-report.py"), "--dir", d], check=True, capture_output=True)
    return open(os.path.join(d, "index.html")).read()
h = rendered()
prior = json.loads(re.search(r'id="report-data">(.*?)</script>', h, re.S).group(1).replace("<\\/", "</"))["prior"]
if not any(e.get("check_key") == keys["V2"] for e in prior):
    print("FAIL: the re-rendered page does not carry the stored tick"); sys.exit(1)
# Now edit that card's steps. Same V2, different content → the key moves and the tick must not follow.
r = json.load(open(os.path.join(d, "report.json")))
for c in r["how_to_check"]:
    if c["id"] == "V2": c["steps"] = ["Something else entirely."]
json.dump(r, open(os.path.join(d, "report.json"), "w"))
h2 = rendered()
keys2 = dict(re.findall(r'class="card ck" data-id="(V\d+)" data-key="([0-9a-f]+)"', h2))
ok = keys2["V2"] != keys["V2"] and keys2["V1"] == keys["V1"]
print("check identity OK" if ok else f"FAIL: keys {keys} -> {keys2}")
sys.exit(0 if ok else 1)
PY
# digest: the same check events reach the MAINTAINER's view, with the check's identity attached.
# They used to land in the generic event mix only — collected, never read.
printf '%s\n' '{"ts":"2026-01-01T00:00:08Z","type":"check_run","check":"V2","status":401}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT" >/dev/null
python3 "$S/feedback.py" digest > "$DESCRIBE_CHANGES_HOME/digest.txt"
grep -q 'How-to-check results' "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: no how-to-check section"
grep -q "1 reported not working" "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: failing check not counted"
grep -q "V2 · Save user endpoint (api) — ✗ didn't work" "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: check identity/verdict missing"
grep -q '401 instead of 200' "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: check note text missing"
grep -q 'sent: 401×1' "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: inline-send status missing"
grep -q 'V1 · Saving a user persists it (ui) — un-ticked after verifying' "$DESCRIBE_CHANGES_HOME/digest.txt" || fail "digest: untick not carried"
# scope: branch mode includes commits + uncommitted; --check detects a moved tree; --committed-only excludes
git commit -qm "wip" && git checkout -qb feat/x && echo 'export const z = 1' > src/z.ts && git add src/z.ts && echo 'export const y = 2' > src/y.ts
OUT2="$(bash "$S/collect-diff.sh" --base main | tail -1 | sed 's/^OUT=//')"
python3 -c "
import json,sys; m=json.load(open('$OUT2/meta.json')); d=json.load(open('$OUT2/diff-model.json'))
paths={f['path'] for f in d['files']}
assert m['mode']=='branch' and m['commits']==0, m
assert {u['path'] for u in m['uncommitted_files']}=={'src/z.ts','src/y.ts'}, m['uncommitted_files']
assert 'src/z.ts' in paths and 'src/y.ts' in paths, paths
print('scope OK')" || fail "branch scope meta"
bash "$S/collect-diff.sh" --check "$OUT2" | grep -q unchanged || fail "check unchanged"
echo 'export const w = 3' > src/w.ts
if bash "$S/collect-diff.sh" --check "$OUT2" >/dev/null; then fail "check should detect moved tree"; fi
CHK="$(bash "$S/collect-diff.sh" --check "$OUT2" || true)"; echo "$CHK" | grep -q 'src/w.ts' || fail "check should list the new file: $CHK"
git commit -qam "c1" 2>/dev/null || { git add -A; git commit -qm c1; }
if bash "$S/collect-diff.sh" --base main --committed-only >/dev/null 2>&1; then
  OUT3="$(bash "$S/collect-diff.sh" --base main --committed-only | tail -1 | sed 's/^OUT=//')"
  python3 -c "import json; m=json.load(open('$OUT3/meta.json')); assert m['committed_only'] and m['commits']==1 and m['uncommitted_files']==[], m; print('committed-only OK')" || fail "committed-only"
fi
git add -A && git commit -qm "clean" && OUT4="$(bash "$S/collect-diff.sh" --base main | tail -1 | sed 's/^OUT=//')" || fail "collect on a CLEAN tree must not die (grep/pipefail)"
python3 -c "import json; m=json.load(open('$OUT4/meta.json')); assert m['uncommitted_files']==[] and m['commits']>=1, m; print('clean tree OK')" || fail "clean tree meta"
bash "$S/collect-diff.sh" --check "$OUT4" | grep -q unchanged || fail "check on clean tree"
# ── regression rows for the review findings on the vendoring MR ─────────────────────────────
# version parity: four files declare the version and feedback.py reads VERSION. They drifted
# (VERSION 1.8.2 vs 1.0.0 in the other three), so lessons and discovery metadata named different
# releases. Assert the class, not the instance.
python3 - "$HERE/.." <<'PV' || fail "version parity"
import json, re, sys, pathlib
root = pathlib.Path(sys.argv[1])
v = (root / "skills/describe-changes/VERSION").read_text().strip()
sk = re.search(r'^version:\s*"([^"]+)"', (root / "skills/describe-changes/SKILL.md").read_text(), re.M).group(1)
pl = json.loads((root / ".claude-plugin/plugin.json").read_text())["version"]
mk = json.loads((root / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
assert sk == v and pl == v and mk == v, f"VERSION={v} SKILL.md={sk} plugin={pl} marketplace={mk}"
print("version parity OK")
PV

# ASI: a line break is semantic in JS/TS/Go, so a block whose line COUNT moved can never fold as
# whitespace/format there — `return\n value` returns undefined where `return value` does not.
python3 - "$S" <<'PA' || fail "ASI classification"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("cd", sys.argv[1] + "/classify-diff.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cb = m.classify_block
assert cb(["  return value;\n"], ["  return\n", "  value;\n"], False, asi=True) == "substantive", "ASI split must not fold"
assert cb(["  return\n", "  value;\n"], ["  return value;\n"], False, asi=True) == "substantive", "ASI join must not fold"
# controls: the folds this feature exists for must survive
assert cb(["  a();\n", "  b();\n"], ["    a();\n", "    b();\n"], False, asi=True) == "whitespace", "re-indent must still fold"
assert cb(["  a();  \n"], ["  a();\n"], False, asi=True) == "whitespace", "trailing ws must still fold"
assert cb(["  return value;\n"], ["  return\n", "  value;\n"], False, asi=False) == "whitespace", "non-ASI reflow still folds"
assert m.ASI_LANGS >= {".js", ".ts", ".tsx", ".go"}, m.ASI_LANGS
print("ASI classification OK")
PA

# fingerprint: a snapshot is skipped when the fingerprint matches, so any report field a reader
# reads must be in it — otherwise editing only that field shows a returning reader "nothing moved".
python3 - "$S" <<'PF' || fail "fingerprint coverage"
import importlib.util, sys, copy
spec = importlib.util.spec_from_file_location("sn", sys.argv[1] + "/snapshots.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
base = {"summary": "s", "intent": "i",
        "findings": [{"id": "C1", "severity": "critical", "title": "t", "file": "a.ts",
                      "lines": "1-2", "verify": "old question?", "why_human": "w", "what": "x"}],
        "phases": [{"id": "p1", "title": "P", "narrative": "n"}],
        "graph": {"nodes": [], "edges": []}, "views": [], "confession": [{"point": "p"}],
        "how_to_check": []}
meta = {"fingerprint": "tree1"}
fp0 = m._fingerprint(base, meta)
assert m._fingerprint(copy.deepcopy(base), meta) == fp0, "fingerprint must be stable for equal input"
for path, mutate in [
    ("finding.verify",    lambda r: r["findings"][0].__setitem__("verify", "NEW question?")),
    ("finding.why_human", lambda r: r["findings"][0].__setitem__("why_human", "NEW")),
    ("finding.what",      lambda r: r["findings"][0].__setitem__("what", "NEW")),
    ("finding.lines",     lambda r: r["findings"][0].__setitem__("lines", "9-9")),
    ("phases",            lambda r: r["phases"].__setitem__(0, {"id": "p1", "title": "P", "narrative": "NEW"})),
    ("graph",             lambda r: r["graph"].__setitem__("nodes", [{"id": "n"}])),
    ("views",             lambda r: r.__setitem__("views", [{"kind": "flow", "steps": []}])),
    ("confession",        lambda r: r["confession"].__setitem__(0, {"point": "NEW"})),
    ("intent",            lambda r: r.__setitem__("intent", "NEW")),
]:
    r = copy.deepcopy(base); mutate(r)
    assert m._fingerprint(r, meta) != fp0, f"fingerprint blind to {path}"
print("fingerprint coverage OK")
PF

# vendored subtrees fold only on PROOF. The whole value is that a reviewer reads the pin instead of
# thousands of upstream lines — and the whole danger is folding a copy somebody edited in place,
# which this skill's own workflow encourages. Both directions, plus the unverifiable pin.
python3 - "$S" "$T" <<'PVEN' || fail "vendored fold"
import importlib.util, os, sys, hashlib
S, T = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("cd", S + "/classify-diff.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
th = m._tree_hash_fn(); assert th, "tree-hash helper must load"

root = os.path.join(T, "vend"); sub = os.path.join(root, ".claude/skills/thing")
os.makedirs(sub, exist_ok=True)
open(os.path.join(sub, "a.py"), "w").write("print(1)\n")
open(os.path.join(sub, "b.md"), "w").write("# doc\n")
pin = os.path.join(root, ".claude/skills/.describe-changes-version")
def write_pin(h):
    open(pin, "w").write("# comment line\norigin=https://example.invalid/x.git\nsha=abc1234def\n"
                         "skills=thing\n" + (f"tree_sha256={h}\n" if h else ""))

# 1. hash matches -> folded, with provenance the reviewer can act on
write_pin(th(sub))
verified, notes = m.vendor_scan(root)
assert ".claude/skills/thing" in verified, (verified, notes)
assert verified[".claude/skills/thing"]["sha"] == "abc1234", verified
assert "example.invalid" in verified[".claude/skills/thing"]["origin"], verified
assert not notes, notes
class F:
    def __init__(s_, p): s_.path, s_.binary, s_.status = p, False, "added"
assert m.file_noise_kind(F(".claude/skills/thing/a.py"), [], verified) == "vendored"
# the pin itself is NOT under the subtree, so it stays reviewable — it is the thing to review
assert m.file_noise_kind(F(".claude/skills/.describe-changes-version"), [], verified) != "vendored"
# and an unrelated file is untouched
assert m.file_noise_kind(F("src/app.ts"), [], verified) is None

# 2. copy edited in place -> folds NOTHING, and says why
open(os.path.join(sub, "a.py"), "a").write("print(2)\n")
verified2, notes2 = m.vendor_scan(root)
assert not verified2, verified2
assert any("differs from its pin" in n["why"] for n in notes2), notes2
assert m.file_noise_kind(F(".claude/skills/thing/a.py"), [], verified2) != "vendored"

# 3. a pin with no content hash proves nothing -> folds nothing, and says why
write_pin(None)
verified3, notes3 = m.vendor_scan(root)
assert not verified3, verified3
assert any("no tree_sha256" in n["why"] for n in notes3), notes3
# 4. the pin is INSIDE the diff it authorises, and its origin cannot be reached. Every LOCAL
#    check passes — hash matches pin — and that is exactly the state an author can manufacture,
#    so the fold must fail CLOSED rather than trust it. The fixture's origin is the reserved
#    `.invalid` TLD (RFC 2606), which is guaranteed never to resolve — the fetch fails fast and
#    the test needs no network.
write_pin(th(sub))
v4, n4 = m.vendor_scan(root, None, {".claude/skills/.describe-changes-version"})
assert ".claude/skills/thing" not in v4, "an unverifiable in-diff pin authorised a fold"
assert any("this same change" in n["why"] for n in n4), n4
# a pin NOT in the diff is provenance a previous review already accepted: folds on the hash alone
v5, n5 = m.vendor_scan(root, None, {"src/other.ts"})
assert ".claude/skills/thing" in v5, v5
assert v5[".claude/skills/thing"]["pin_in_diff"] is False, v5
assert not n5, n5
print("vendored fold OK")
PVEN

# A pin that arrives WITH the change it authorises is the author's own word, so the bytes are
# re-derived from the real remote or nothing folds. Uses a local file:// origin — no network.
python3 - "$S" "$T" <<'PUP' || fail "vendored fold upstream provenance"
import importlib.util, os, subprocess, sys
S, T = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("cd", S + "/classify-diff.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
th = m._tree_hash_fn()
up = os.path.join(T, "upstream")                       # the real upstream repo
os.makedirs(os.path.join(up, "skills/thing"), exist_ok=True)
U = lambda *a: subprocess.run(["git", "-C", up, *a], capture_output=True, text=True, check=True)
subprocess.run(["git", "init", "-q", up], check=True); U("config", "user.email", "u@u"); U("config", "user.name", "u")
open(os.path.join(up, "skills/thing/a.py"), "w").write("print('genuine upstream')\n")
U("add", "-A"); U("commit", "-qm", "upstream v1")
up_sha = U("rev-parse", "HEAD").stdout.strip()
origin = "file://" + up

con = os.path.join(T, "consumer"); sub = os.path.join(con, ".claude/skills/thing")
os.makedirs(sub, exist_ok=True)
pin_rel = ".claude/skills/.describe-changes-version"
def write_pin(sha, body_dir):
    open(os.path.join(con, pin_rel), "w").write(
        f"origin={origin}\nsha={sha}\nskills=thing\nupstream_path=skills/thing\n"
        f"tree_sha256={th(body_dir)}\n")

# 1. GENUINE vendoring: the copy really is the upstream commit -> folds, and says it was re-derived
open(os.path.join(sub, "a.py"), "w").write("print('genuine upstream')\n")
write_pin(up_sha, sub)
v, n = m.vendor_scan(con, None, {pin_rel})
assert ".claude/skills/thing" in v, (v, n)
assert "re-derived" in v[".claude/skills/thing"]["detail_src"], v
print("  genuine in-diff vendoring folds, re-derived from the remote")

# 2. THE ATTACK: attacker code, self-consistent pin, real origin+sha -> must NOT fold
open(os.path.join(sub, "a.py"), "w").write("print('attacker payload')\n")
write_pin(up_sha, sub)          # hash recomputed over the payload: every LOCAL check passes
assert th(sub) == open(os.path.join(con, pin_rel)).read().split("tree_sha256=")[1].strip()
v2, n2 = m.vendor_scan(con, None, {pin_rel})
assert ".claude/skills/thing" not in v2, "attacker payload was folded out of review"
assert any("does NOT match" in x["why"] for x in n2), n2
print("  attacker payload refused, and the note says the content does not match upstream")

# 3. unreachable origin -> fails CLOSED
open(os.path.join(sub, "a.py"), "w").write("print('genuine upstream')\n")
open(os.path.join(con, pin_rel), "w").write(
    f"origin=file://{T}/does-not-exist\nsha={up_sha}\nskills=thing\nupstream_path=skills/thing\n"
    f"tree_sha256={th(sub)}\n")
v3, n3 = m.vendor_scan(con, None, {pin_rel})
assert ".claude/skills/thing" not in v3, "an unreachable origin still folded"
print("  unreachable origin folds nothing (fails closed)")

# 4. control: the SAME pin, not in the diff, still folds cheaply without any network
write_pin(up_sha, sub)
v4, _ = m.vendor_scan(con, None, {"src/other.ts"})
assert ".claude/skills/thing" in v4, v4
assert "content verified against the pin" in v4[".claude/skills/thing"]["detail_src"], v4
assert "re-derived" not in v4[".claude/skills/thing"]["detail_src"], v4
print("  a pre-existing pin still folds against the hash alone")
print("vendored fold upstream provenance OK")
PUP

# committed-only reports describe HEAD, so the vendored proof must be read from HEAD — not from a
# working tree that may have been re-vendored since the edit was committed.
python3 - "$S" "$T" <<'PREF' || fail "vendored fold verify-ref"
import importlib.util, os, subprocess, sys
S, T = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("cd", S + "/classify-diff.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
th = m._tree_hash_fn()
root = os.path.join(T, "vref"); sub = os.path.join(root, "v/thing")
os.makedirs(sub, exist_ok=True)
run = lambda *a: subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, check=True)
subprocess.run(["git", "init", "-q", root], check=True)
run("config", "user.email", "t@t"); run("config", "user.name", "t")
open(os.path.join(sub, "a.py"), "w").write("print(1)\n")
pin = os.path.join(root, "v/.describe-changes-version")
def write_pin():
    open(pin, "w").write("origin=https://example.invalid/x.git\nsha=deadbeefcafe\nskills=thing\n"
                         f"tree_sha256={th(sub)}\n")
write_pin(); run("add", "-A"); run("commit", "-qm", "vendored, clean")
# commit an EDIT to the vendored copy, then re-vendor the worktree so it matches the pin again
open(os.path.join(sub, "a.py"), "a").write("print('edit inside the reported range')\n")
run("add", "-A"); run("commit", "-qm", "edit the vendored copy")
head = run("rev-parse", "HEAD").stdout.strip()
open(os.path.join(sub, "a.py"), "w").write("print(1)\n")   # worktree back to the pinned content
assert th(sub) == open(pin).read().split("tree_sha256=")[1].strip(), "worktree must match the pin again"
# worktree proof would fold — and would hide the committed edit that IS the reported range
vw, _ = m.vendor_scan(root, None, set())
assert "v/thing" in vw, vw
# proof at HEAD must refuse
vr, nr = m.vendor_scan(root, head, set())
assert "v/thing" not in vr, "committed-only report folded a subtree that is edited at HEAD"
assert any("differs from its pin" in n["why"] for n in nr), nr
# ...and the pin must be read at that ref too. Proving the SUBTREE at HEAD while reading its
# expected hash from the WORKING TREE leaves the same hole open from the other side.
open(os.path.join(sub, "a.py"), "a").write("print('committed edit')\n")
run("add", "-A"); run("commit", "-qm", "edit again")
head2 = run("rev-parse", "HEAD").stdout.strip()
write_pin()  # UNCOMMITTED pin naming the edited subtree's hash — worktree and HEAD subtree agree
assert run("status", "--porcelain").stdout.strip(), "the pin must be uncommitted for this case"
v6, n6 = m.vendor_scan(root, head2, set())
assert "v/thing" not in v6, "an uncommitted pin authorised a fold in a committed-only report"
print("vendored fold verify-ref OK")
PREF

# delta pairing: two independent findings in one file must NOT collapse into one "changed" row.
python3 - "$S" <<'PD' || fail "delta pairing"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("sn", sys.argv[1] + "/snapshots.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
mk = lambda i, sev, t: {"id": i, "severity": sev, "title": t, "file": "src/a.ts", "verify": "?", "why_human": "?"}
# one resolved + one unrelated new, same file, same severity → ambiguous, so no pairing
snap = lambda fs: {"report": {"findings": fs}}
d = m.compute_delta(snap([mk("C1", "critical", "old risk"), mk("C2", "critical", "other old risk")]),
                    snap([mk("C3", "critical", "brand new risk")]))
assert len(d["findings_changed"]) == 0, d["findings_changed"]
assert len(d["findings_added"]) == 1 and len(d["findings_resolved"]) == 2, d
# controls: a lone re-wording in a file IS a change; a pure re-rating (same claim, new severity)
# is reported too — finding_key is file+claim and excludes severity, so it used to vanish from the
# delta while _fingerprint still saved a snapshot for it.
d2 = m.compute_delta(snap([mk("C1", "critical", "old wording")]),
                     snap([mk("C1", "critical", "new wording")]))
assert len(d2["findings_changed"]) == 1, d2["findings_changed"]
d3 = m.compute_delta(snap([mk("C1", "critical", "same claim")]),
                     snap([mk("M1", "medium", "same claim")]))
assert len(d3["findings_changed"]) == 1, d3["findings_changed"]
assert d3["findings_changed"][0]["was_severity"] == "critical", d3["findings_changed"]
assert d3["findings_changed"][0]["severity"] == "medium", d3["findings_changed"]
assert not d3["findings_added"] and not d3["findings_resolved"], d3
# and an untouched finding produces no row at all (the pristine control for the three above)
d4 = m.compute_delta(snap([mk("C1", "critical", "same claim")]), snap([mk("C1", "critical", "same claim")]))
assert not d4["findings_changed"] and not d4["findings_added"] and not d4["findings_resolved"], d4
print("delta pairing OK")
PD
echo "ALL TESTS PASSED"
