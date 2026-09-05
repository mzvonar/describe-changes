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
cd "$T" && git init -q -b main . && git config user.email t@t && git config user.name t
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
printf 'def f(x):\n    if x:\n        return 1\n    return 2\n' > script.py
printf '{"lockfileVersion": 3}\n' > package-lock.json
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
printf 'def f(x):\n    if x:\n        return 1\n        return 3\n    return 2\n' > script.py
printf '{"lockfileVersion": 3, "x": 1}\n' > package-lock.json
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
            'id="folded"', 'id="conversation"', 'id="unreviewed"')
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
grep -q 'class="fpath" data-open="src/util/big-a.ts"' "$OUT/index.html" || fail "folded-noise file paths are not clickable"
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

# budget violation must fail
python3 - "$OUT" <<'PY'
import json, sys, os, copy
d = sys.argv[1]; r = json.load(open(os.path.join(d, "report.json")))
for i in range(2, 6): r["findings"].append(dict(r["findings"][0], id=f"C{i}"))
json.dump(r, open(os.path.join(d, "bad.json"), "w"))
PY
if python3 "$S/check-report.py" "$OUT/bad.json" >/dev/null 2>&1; then fail "check-report accepted 5 criticals"; fi

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
