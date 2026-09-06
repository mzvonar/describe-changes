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
printf 'home/\nget.html\nserve.log\n' > .gitignore

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
# `<div class="diff">` lives inside the file-store JSON, so look for it there, not in the markup.
has_code = ('id="folded"' in h and 'id="unreviewed"' in h
            and any('<div class="diff">' in v.get("html", "") for v in store.values()))
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

# feedback round trip
printf '%s\n' '{"ts":"2026-01-01T00:00:00Z","type":"less","finding":"C1","report_id":"x"}' '{"ts":"2026-01-01T00:00:01Z","type":"gut_flag","file":"script.py","report_id":"x"}' > "$OUT/feedback.jsonl"
python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT" | grep -q "ingested 2" || fail "ingest"
python3 "$S/feedback.py" ingest "$OUT/feedback.jsonl" --dir "$OUT" | grep -q "ingested 0" || fail "ingest dedupe"
python3 "$S/feedback.py" question "why upsert?" --dir "$OUT" --finding C1 >/dev/null
python3 "$S/feedback.py" digest | grep -q "over-rated" || fail "digest"
python3 "$S/feedback.py" push | grep -q "no shared backend" || fail "push without backend"

# serve: POST /feedback
python3 "$S/serve.py" "$OUT" --port 8799 >"$T/serve.log" 2>&1 & SP=$!; sleep 0.7
curl -sf -X POST localhost:8799/feedback -d '{"events":[{"ts":"2026-01-01T00:00:02Z","type":"more","finding":"C1"}]}' | grep -q '"stored": 1' || { kill $SP; fail "serve POST"; }
curl -sf -o "$T/get.html" localhost:8799/ && grep -q '<title>' "$T/get.html" || { kill $SP; fail "serve GET"; }
kill $SP; wait $SP 2>/dev/null || true
grep -q '"type": "more"' "$OUT/feedback.jsonl" || fail "feedback not appended"
# comments: ask → list → answer → rendered
printf '%s\n' '{"ts":"2026-01-01T00:00:03Z","type":"comment","id":"cabc","text":"what is this?","anchor":{"text":"saveUser","context":"…saveUser now persists…","section":"summary","finding":null}}' >> "$OUT/feedback.jsonl"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q '\[cabc\] OPEN' || fail "comments list"
python3 "$S/feedback.py" answer --dir "$OUT" --id cabc --improvement "name the persistence call in the summary" --text "It upserts via \`db.upsert\`." | grep -q "answered cabc" || fail "answer"
python3 "$S/feedback.py" comments --dir "$OUT" --open | grep -q 'no open comments' || fail "answered thread still open"
python3 "$S/render-report.py" --dir "$OUT" >/dev/null
grep -q 'id="t-cabc"' "$OUT/index.html" && grep -q '<code>db.upsert</code>' "$OUT/index.html" || fail "thread/answer not rendered"
python3 "$S/feedback.py" digest | grep -q 'improvement: name the persistence' || fail "digest improvement"
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
echo "ALL TESTS PASSED"
