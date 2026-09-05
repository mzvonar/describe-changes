#!/usr/bin/env python3
"""render-report.py — report.json + diff-model.json + raw.diff → self-contained mobile-first index.html.

Usage: render-report.py --dir <out-dir> [--template <path>] [--out <index.html>]
The LLM never writes HTML: it writes report.json (see reference/report-schema.md); this script
pulls code snippets straight from raw.diff by hunk id, builds the mermaid map, and lays out the
cards. Deterministic: same inputs → same HTML.
"""
import argparse, html, json, os, re, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
_spec = importlib.util.spec_from_file_location("classify_diff", os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify-diff.py"))
classify_diff = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(classify_diff)

E = html.escape
SEV_ORDER = {"critical": 0, "medium": 1, "low": 2}
CHANGE_FILL = {"added": "#1f5a3a", "modified": "#6b4a12", "removed": "#6b1f1f", "moved": "#1f3f6b", "renamed": "#1f3f6b",
               "split": "#3b2a6b", "unchanged": "#2d3748"}
EDGE_STYLE = {"calls": "-->", "dataflow": "==>", "imports": "-.->", "renders": "-->", "extends": "-->", "moved_to": "-.->",
              "split_into": "-.->", "emits": "-->", "reads": "-.->", "writes": "==>"}

def mid(s): return "n" + hashlib.md5(s.encode()).hexdigest()[:8]

def mermaid(graph):
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    if not nodes: return ""
    out = ["flowchart TD"]
    by_file = {}
    for n in nodes: by_file.setdefault(n.get("file") or "", []).append(n)
    use_sub = 1 < len(by_file) <= 12
    def node_line(n):
        label = n["label"].replace('"', "'")
        kind = n.get("kind", "")
        if kind in ("component",): shape = f'(["{label}"])'
        elif kind in ("type", "interface", "schema"): shape = f'[/"{label}"/]'
        elif kind in ("module", "file"): shape = f'[["{label}"]]'
        elif kind in ("store", "db", "table"): shape = f'[("{label}")]'
        else: shape = f'["{label}"]'
        return f'  {mid(n["id"])}{shape}'
    for f, ns in by_file.items():
        if use_sub and f:
            out.append(f'  subgraph {mid("f:"+f)}["{f.replace(chr(34), "")}"]')
            out += ["  " + node_line(n) for n in ns]
            out.append("  end")
        else:
            out += [node_line(n) for n in ns]
    for e in edges:
        arrow = EDGE_STYLE.get(e.get("kind", "calls"), "-->")
        lab = (e.get("label") or e.get("kind") or "").replace('"', "'").replace("|", "/")
        out.append(f'  {mid(e["from"])} {arrow}{"|" + chr(34) + lab + chr(34) + "|" if lab else ""} {mid(e["to"])}')
    for ch, fill in CHANGE_FILL.items():
        ids = [mid(n["id"]) for n in nodes if n.get("change") == ch]
        if ids:
            style = f"fill:{fill},stroke:#cbd5e0,color:#ffffff" + (",stroke-dasharray:4 3" if ch == "removed" else "")
            out.append(f"  classDef {ch} {style}")
            out.append(f"  class {','.join(ids)} {ch}")
    return "\n".join(out)

def map_list(graph):
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    rows = []
    for n in graph.get("nodes", []):
        rows.append(f'<div><span class="ch-{E(n["change"])}">{E(n["label"])}</span> <span style="color:var(--fg3)">{E(n.get("kind",""))} · {E(n["change"])}{(" · " + E(n["file"])) if n.get("file") else ""}</span></div>')
    for e in graph.get("edges", []):
        a, b = nodes.get(e["from"], {}).get("label", e["from"]), nodes.get(e["to"], {}).get("label", e["to"])
        rows.append(f'<div>{E(a)} —{E(e.get("label") or e.get("kind",""))}→ {E(b)}</div>')
    return "\n".join(rows)

def hunk_html(h, path):
    lines = []
    for l in h.lines:
        cls = "a" if l.startswith("+") else "d" if l.startswith("-") else "c"
        lines.append(f'<div class="l {cls}">{E(l)}</div>')
    return f'<div class="diff"><div class="hh">{E(path)} {E(h.header.split("@@")[1].strip() if "@@" in h.header else "")} <span style="color:var(--fg3)">[{E(h.id)}]</span></div><pre>{"".join(lines)}</pre></div>'

def index_hunks(files):
    idx = {}
    for fi, f in enumerate(files, 1):
        for hi, h in enumerate(f.hunks, 1):
            h.id = f"F{fi}H{hi}"; idx[h.id] = (h, f.path)
    return idx

def finding_card(f, hunks):
    sev = f["severity"]; tags = f.get("tags", [])
    loc = f["file"] + (f":{f['lines']}" if f.get("lines") else "")
    snippets = "".join(hunk_html(*hunks[h]) for h in f.get("hunks", []) if h in hunks)
    before_after = ""
    if f.get("before") or f.get("after"):
        before_after = '<div class="diff"><pre>' + "".join(
            f'<div class="l d">{E(l)}</div>' for l in (f.get("before") or "").splitlines()) + "".join(
            f'<div class="l a">{E(l)}</div>' for l in (f.get("after") or "").splitlines()) + "</pre></div>"
    code = snippets or before_after
    return f'''<div class="card sev-{sev}" data-id="{E(f["id"])}" data-sev="{sev}" data-tags="{E(" ".join(tags))}">
  <div class="card-h"><span class="tw">▶</span><span class="pill {sev}">{E(f["id"])}</span>
    <div class="title">{E(f["title"])}<small>{E(loc)}</small></div></div>
  <div class="card-b">
    <div class="verify"><b>Verify</b>{E(f["verify"])}</div>
    <div class="kv"><b>Why a human</b>{E(f["why_human"])}</div>
    {('<div class="kv"><b>What changed</b>' + E(f["what"]) + '</div>') if f.get("what") else ""}
    {('<div class="tags">' + "".join(f'<span class="tag">{E(t)}</span>' for t in tags) + '</div>') if tags else ""}
    <div><span class="loc" data-loc="{E(loc)}">⧉ {E(loc)}</span></div>
    {('<details class="more"><summary>Show code</summary>' + code + '</details>') if code else ""}
    <div class="fb"><button data-t="more">▲ More important</button><button data-t="less">▼ Less important</button><button data-t="noise" class="danger">✕ Noise</button><button data-t="checked">✓ Checked</button></div>
    <div class="fb"><textarea placeholder="Note for the skill (what was wrong / missing / useful)…"></textarea></div>
  </div></div>'''

def render_confession(conf):
    """Author doubt as a scannable list — one line per item, detail folded behind it.

    Accepts the legacy free-text string too: a paragraph of confession is still worth showing, and
    old reports must keep rendering. But the list form is the one that gets READ, which is the whole
    point — a reviewer skims four one-liners and opens the one that worries them, where the same
    content as prose gets skipped wholesale and the doubt may as well not have been declared.
    """
    if not conf:
        return ""
    if isinstance(conf, str):
        return f'<div class="conf"><b>Author confession</b><div class="narr">{E(conf)}</div></div>'
    items = []
    for c in conf:
        point = E(c.get("point", "")) if isinstance(c, dict) else E(str(c))
        detail = c.get("detail") if isinstance(c, dict) else None
        if detail:
            items.append(f'<li><details><summary>{point}</summary><div class="d">{E(detail)}</div></details></li>')
        else:
            items.append(f"<li>{point}</li>")
    return '<div class="conf"><b>Author confession</b><ul>' + "".join(items) + "</ul></div>"

CH_LABEL = {"added": "new", "modified": "changed", "removed": "deleted", "moved": "moved", "renamed": "renamed", "split": "split", "unchanged": ""}

def fchip(node):
    """Clickable file chip → opens that file's changed code in the sheet."""
    f = node.get("file")
    if not f: return ""
    return f'<button class="fchip" data-open="{E(f)}" title="{E(f)}">⟨/⟩ {E(os.path.basename(f))}</button>'

def fpath(path, known=None):
    """A file path listed in prose (phases, uncommitted set) — clickable to its diff.

    Shows the FULL path, unlike `fchip`: these appear in lists where sibling features routinely
    contribute two `actions.ts` or two `membership.ts`, and a basename alone cannot tell them apart.

    A path the diff does not contain renders inert instead of opening an empty sheet — a control
    that does nothing when clicked teaches the reader that none of them work.
    """
    if known is not None and path not in known:
        return f"<span>{E(path)}</span>"
    return f'<button class="fpath" data-open="{E(path)}" title="Show the changes in {E(path)}">{E(path)}</button>'

def pill(change):
    return f'<span class="chg chg-{E(change)}">{E(CH_LABEL.get(change, change))}</span>' if change and change != "unchanged" else ""

def view_screen(v):
    def box(n, depth=0):
        slot = f'<span class="slot">{E(n["slot"])} ▸</span>' if n.get("slot") else ""
        kids = "".join(box(c, depth + 1) for c in n.get("children", []))
        note = f'<div class="scr-note">{E(n["note"])}</div>' if n.get("note") else ""
        cls = "scr scr-" + E(n.get("change", "unchanged")) + (" scr-slot" if n.get("slot") else "")
        return f'<div class="{cls}"><div class="scr-h">{slot}<span class="scr-l">{E(n["label"])}</span>{pill(n.get("change"))}{fchip(n)}</div>{note}{kids}</div>'
    return f'<div class="screen">{box(v["screen"])}</div>'

def view_flow(v):
    def step(st, i=None):
        kids = "".join(step(c) for c in st.get("then", []))
        note = f'<div class="st-note">{E(st["note"])}</div>' if st.get("note") else ""
        files = "".join(fchip({"file": f}) for f in st.get("files", []))
        return (f'<div class="step step-{E(st.get("change", "unchanged"))}"><div class="st-h">{("<span class=st-n>" + str(i) + "</span>") if i else ""}<span class="st-l">{E(st["label"])}</span>{pill(st.get("change"))}{fchip(st)}{files}</div>{note}'
                + (f'<div class="st-then">{kids}</div>' if kids else "") + '</div>')
    return '<div class="flow">' + "".join(step(st, i) for i, st in enumerate(v["steps"], 1)) + "</div>"

def view_adoption(v):
    root = v["root"]
    roots = root if isinstance(root, list) else [root]
    rh = "".join(f'<div class="ad-root ad-{E(r.get("change","added"))}"><div class="scr-h"><span class="scr-l">{E(r["label"])}</span>{pill(r.get("change"))}{fchip(r)}</div>' + (f'<div class="scr-note">{E(r["note"])}</div>' if r.get("note") else "") + '</div>' for r in roots)
    uses = "".join(f'<div class="ad-use ad-{E(u.get("change","modified"))}"><div class="scr-h"><span class="scr-l">{E(u["label"])}</span>{pill(u.get("change"))}{fchip(u)}</div>' + (f'<div class="scr-note">{E(u["note"])}</div>' if u.get("note") else "") + '</div>' for u in v.get("uses", []))
    repl = "".join(f'<div class="ad-use ad-removed"><div class="scr-h"><span class="scr-l">{E(u["label"])}</span>{pill("removed")}{fchip(u)}</div>' + (f'<div class="scr-note">{E(u["note"])}</div>' if u.get("note") else "") + '</div>' for u in v.get("replaces", []))
    return (f'<div class="adoption"><div class="ad-roots">{rh}</div><div class="ad-arrow">used in ↓</div><div class="ad-uses">{uses}</div>'
            + (f'<div class="ad-arrow">replaces ↓</div><div class="ad-uses">{repl}</div>' if repl else "") + '</div>')

VIEWS = {"screen": view_screen, "flow": view_flow, "adoption": view_adoption}

SURFACE_LABEL = {"ui": "screen", "api": "API", "cli": "command"}

def check_card(c):
    """One shipped capability, with the steps to exercise it for real.

    The API affordances (curl / Postman / inline send) are built in the browser from `request`, not
    baked in here, because they all depend on a base URL the reader picks at read time — their laptop,
    a preview deployment, a colleague's tunnel.
    """
    surface = c.get("surface", "ui")
    req = c.get("request") if surface == "api" else None
    steps = "".join(f"<li>{E(s)}</li>" for s in c.get("steps", []))
    where = f'<div class="ck-where">{E(c["where"])}</div>' if c.get("where") else ""
    setup = f'<div class="kv"><b>First</b>{E(c["setup"])}</div>' if c.get("setup") else ""
    expect = f'<div class="verify"><b>Expect</b>{E(c["expect"])}</div>' if c.get("expect") else ""
    covered = (f'<div class="ck-cov">Regression cover: {fpath(c["covered_by"])}</div>'
               if c.get("covered_by") else "")
    api = ""
    if req:
        mutating = str(req.get("method", "GET")).upper() not in ("GET", "HEAD", "OPTIONS")
        api = (f'<div class="ck-api" data-id="{E(c["id"])}">'
               f'<div class="ck-req"><span class="m m-{E(str(req.get("method","GET")).lower())}">{E(str(req.get("method","GET")).upper())}</span>'
               f'<code>{E(req["path"])}</code></div>'
               + (f'<div class="ck-note">{E(req["note"])}</div>' if req.get("note") else "")
               + '<div class="fb"><button data-act="curl">Copy as curl</button>'
                 f'<button data-act="send" class="{"danger" if mutating else ""}">▶ Send{" (writes)" if mutating else ""}</button></div>'
               + '<div class="ck-out"></div></div>')
    # The tick lives in the HEADER so a card can be marked without expanding it — on a second pass a
    # reviewer is confirming a list, not re-reading it. The note lives in the body, next to the steps
    # it is about.
    return (f'<div class="card ck" data-id="{E(c["id"])}"><div class="card-h"><span class="tw">▶</span>'
            f'<label class="ck-done" title="Mark {E(c["id"])} verified"><input type="checkbox"><span></span></label>'
            f'<span class="pill check">{E(c["id"])}</span>'
            f'<div class="title">{E(c["feature"])}<small>{E(SURFACE_LABEL.get(surface, surface))}</small></div></div>'
            f'<div class="card-b">{where}{setup}<ol class="ck-steps">{steps}</ol>{expect}{api}{covered}'
            '<div class="ck-mark"><textarea placeholder="Didn\'t work? What happened instead…"></textarea></div>'
            '</div></div>')

def postman_collection(items, name):
    """A Postman v2.1 collection of every runnable request in the report.

    `{{base}}` stays a Postman variable rather than a resolved host: the collection is meant to be
    shared and re-pointed, and a baked-in localhost is the reason exported collections rot.
    """
    reqs = []
    for c in items:
        req = c.get("request")
        if not req: continue
        headers = [{"key": k, "value": str(v)} for k, v in (req.get("headers") or {}).items()]
        item = {"name": f'{c["id"]} · {c["feature"]}',
                "request": {"method": str(req.get("method", "GET")).upper(), "header": headers,
                            "url": {"raw": "{{base}}" + req["path"], "host": ["{{base}}"],
                                    "path": [p for p in req["path"].lstrip("/").split("/") if p]}}}
        if req.get("body") is not None:
            item["request"]["body"] = {"mode": "raw", "raw": json.dumps(req["body"], indent=2),
                                       "options": {"raw": {"language": "json"}}}
        if req.get("note"):
            item["request"]["description"] = req["note"]
        reqs.append(item)
    return {"info": {"name": name, "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "variable": [{"key": "base", "value": "http://localhost:3000"}],
            "item": reqs}

def fold_ref(path, hunk_ids, hunks, label=None):
    """A file inside a fold card, opening the FOLDED hunks for that file — not its whole diff.

    The distinction is the point of the section. A file listed under "import-only changes" usually
    also has substantive hunks elsewhere (the repository that gained three functions AND re-pointed
    one import); opening it to the substantive diff answers a question the reader did not ask and
    hides the one line the card is actually about. Worse, a folded hunk is otherwise rendered
    NOWHERE — the import that justified the fold was unviewable in the whole report.
    """
    mine = [hid for hid in (hunk_ids or []) if hid in hunks and hunks[hid][1] == path]
    if not mine:
        return fpath(path, known=None) if label is None else f"<span>{E(label or path)}</span>"
    return (f'<button class="fpath" data-open-hunks="{E(",".join(mine))}" data-open-label="{E(path)}"'
            f' title="Show the folded change in {E(path)}">{E(label or path)}</button>')

def fold_card(g, known=None, hunks=None):
    # Folded files stay openable. The reader is told to skip this section, which is exactly why the
    # escape hatch matters: the one failure folding can cause is hiding a real change inside a
    # "rename", and a reviewer who suspects that must be able to check without leaving the page.
    items = []
    for it in g["items"]:
        sub = ""
        if it.get("followers"):
            sub = ("<ul>" + "".join(
                f'<li>{fold_ref(x["file"], x.get("hunk_ids"), hunks or {}) if x.get("hunk_ids") else fpath(x["file"], known)}'
                f' — {E(x["detail"])}</li>' for x in it["followers"]) + "</ul>")
        if it.get("files"):
            sub = ('<details class="more"><summary>show files</summary><ul>'
                   + "".join(f'<li>{fold_ref(x, it.get("hunk_ids"), hunks or {})}</li>' for x in it["files"])
                   + "</ul></details>")
            # Direction comes from the model — re-deriving it here is how the page once said
            # "unused imports dropped" over a fold whose files only ADDED imports.
            n = len(it["files"])
            verb = it.get("verb") or f'imports changed in {n} file{"s" if n != 1 else ""}'
            lab = f'{E(it["module"])} <span style="color:var(--fg3)">← {E(verb)}</span>' if it.get("module") else E(verb)
            items.append(f'<li>{lab}{sub}</li>'); continue
        if it.get("targets"):
            sub = "<ul>" + "".join(f'<li>→ {fpath(t["path"], known)} ({int(t["overlap"]*100)}% of its lines came from the source)</li>' for t in it["targets"]) + "</ul>"
        # An item that names a real file AND its hunks becomes a control, whatever `detail` says —
        # for a comment-only fold `detail` is the hunk header (`@@ -27,6 +27,10 @@`), a label rather
        # than prose, and treating it as prose is what left those hunks unviewable. Items whose
        # `file` is a module name rather than a path fall back to plain text via fold_ref.
        if it.get("hunk_ids") and it.get("file"):
            label = f'{it["file"]}{(" · " + it["detail"]) if it.get("detail") else ""}'
            head = fold_ref(it["file"], it["hunk_ids"], hunks or {}, label=label)
        else:
            head = E(it["detail"]) if it.get("detail") else fpath(it["file"], known)
        items.append(f'<li>{head}{sub}</li>')
    n = g["count"] + sum(len(it.get("followers", [])) for it in g["items"])
    return f'''<div class="card fold"><div class="card-h"><span class="tw">▶</span><span class="pill noise">{n}</span><div class="title">{E(g["title"])}</div></div>
  <div class="card-b"><ul>{"".join(items)}</ul></div></div>'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--template"); ap.add_argument("--out")
    a = ap.parse_args()
    d = a.dir
    report = json.load(open(os.path.join(d, "report.json")))
    model = json.load(open(os.path.join(d, "diff-model.json")))
    meta = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
    raw = open(os.path.join(d, "raw.diff"), encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(d, "raw.diff")) else ""
    hunks = index_hunks(classify_diff.parse(raw)) if raw else {}
    tpl_path = a.template or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "template.html")
    tpl = open(tpl_path).read()

    findings = sorted(report["findings"], key=lambda f: (SEV_ORDER[f["severity"]], int(re.sub(r"\D", "", f["id"]) or 0)))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEV_ORDER}
    st = model["stats"]
    report_id = report.get("report_id") or hashlib.md5((meta.get("repo", "") + meta.get("range_label", "") + meta.get("head_sha", "")).encode()).hexdigest()[:10]
    title = report["title"]
    tags = sorted({t for f in findings for t in f.get("tags", [])})

    b = []
    unc = meta.get("uncommitted_files") or []
    # Every path the diff actually contains — what decides whether a listed file is clickable.
    known_paths = {f["path"] for f in model["files"]} | {f["old_path"] for f in model["files"] if f.get("old_path")}
    scope = ""
    if meta.get("mode") == "branch":
        scope = f' · {meta.get("commits", 0)} commits' + (f' + <b style="color:var(--med)">{len(unc)} uncommitted files</b>' if unc else " · tree clean")
    elif meta.get("mode") == "worktree":
        scope = f' · {len(unc)} uncommitted files'
    b.append(f'<header class="top"><h1>{E(title)}</h1><div class="sub">{E(meta.get("repo",""))} · {E(meta.get("range_label", report.get("range","")))}{scope}</div>')
    b.append('<div class="chips">'
             + (f'<span class="chip crit"><i class="dot"></i>{counts["critical"]} critical</span>' if counts["critical"] else "")
             + (f'<span class="chip med"><i class="dot"></i>{counts["medium"]} medium</span>' if counts["medium"] else "")
             + (f'<span class="chip low"><i class="dot"></i>{counts["low"]} low</span>' if counts["low"] else "")
             + f'<span class="chip"><b>{st["files_substantive"]}</b>/{st["files"]} files matter</span>'
             + f'<span class="chip"><b>{st["lines_substantive"]}</b>/{st["lines_changed"]} lines matter</span>'
             + f'<span class="chip noise"><i class="dot"></i>{st["noise_pct"]}% folded</span></div>')
    # Listed in the order the page actually renders them — a nav that disagrees with the page is a
    # small lie the reader catches immediately, and it costs the report credibility it needs later.
    b.append('<div class="toc"><a href="#summary">Summary</a><a href="#map">Map</a><a href="#phases">Phases</a><a href="#findings">Review</a>'
             + ('<a href="#check">How to check</a>' if report.get("how_to_check") else "")
             + '<a href="#conversation">Conversation</a><a href="#unreviewed">Everything else</a><a href="#folded">Folded</a></div></header>')

    # Intent leads, small and quiet — it FRAMES the summary instead of repeating it. Rendering it
    # after, as an equal-weight paragraph, is what made the two read as duplicates.
    b.append(f'<section id="summary"><h2>What was done</h2><div class="card open"><div class="card-b" style="border:0;padding-top:1rem">'
             + (f'<div class="lede"><b>Asked for</b>{E(report["intent"])}</div>' if report.get("intent") else "")
             + f'<div class="narr">{E(report["summary"])}</div>'
             + render_confession(report.get("confession"))
             + (('<details class="more" style="margin-top:.6rem"><summary>Included uncommitted changes (' + str(len(unc)) + ' files — not yet in any commit)</summary><div class="files">'
                 + "".join(f'<span>{E(u["status"])}</span>' + fpath(u["path"], known_paths) for u in unc) + '</div></details>') if unc else "")
             + '</div></div></section>')

    # Pictures before prose. The map and views answer "what shape is this change?", which is the
    # question a reviewer has immediately after the summary — and the one that decides how carefully
    # they read everything below. Phases are the walkthrough you want AFTER you can see the terrain;
    # printed first they are a list of unfamiliar names in dependency order.
    #
    # Views (the visualization toolset) — chosen per change by the analysis.
    for i, v in enumerate(report.get("views") or [], 1):
        fn = VIEWS.get(v.get("kind"))
        if not fn: continue
        b.append(f'<section id="view-{i}" class="view"><h2>{E(v.get("title") or v["kind"])} <span class="cnt">{E(v["kind"])}</span></h2>'
                 + (f'<div class="narr" style="margin-bottom:.6rem">{E(v["narrative"])}</div>' if v.get("narrative") else "")
                 + '<div class="legend"><span><i style="background:#1f5a3a"></i>new</span><span><i style="background:#6b4a12"></i>changed</span><span><i style="background:#6b1f1f"></i>deleted</span><span><i style="background:#1f3f6b"></i>moved</span><span>⟨/⟩ tap a file to see its changed code</span></div>'
                 + fn(v) + '</section>')

    mm = mermaid(report["graph"]) if report["graph"].get("nodes") else ""
    b.append('<section id="map"' + ('' if mm else ' class="hidden"') + '><h2>Map of the change</h2>'
             '<div class="legend"><span><i style="background:#1f5a3a"></i>added</span><span><i style="background:#6b4a12"></i>modified</span><span><i style="background:#6b1f1f"></i>removed</span><span><i style="background:#1f3f6b"></i>moved / renamed</span><span><i style="background:#3b2a6b"></i>split</span><span>→ calls · ⇒ data flows · ⇢ imports/moved</span></div>')
    if mm:
        b.append(f'<div class="map"><pre class="mermaid">{E(mm)}</pre></div><div class="map-tools"><button class="btn hidden" id="map-zoom">Actual size</button></div><div class="map-list" id="map-fallback">{map_list(report["graph"])}</div>')
        if report["graph"].get("narrative"): b.append(f'<div class="narr" style="margin-top:.6rem">{E(report["graph"]["narrative"])}</div>')
    else:
        b.append('<div class="empty">No structural map for this change.</div>')
    b.append("</section>")

    b.append(f'<section id="phases"><h2>How it was built <span class="cnt">{len(report["phases"])} phases, in dependency order</span></h2>')
    for i, p in enumerate(report["phases"], 1):
        files = "".join(fpath(x, known_paths) for x in p.get("files", []))
        b.append(f'<div class="card{" open" if i == 1 else ""}"><div class="card-h"><span class="tw">▶</span><span class="pill phase">{i}</span><div class="title">{E(p["title"])}</div></div>'
                 f'<div class="card-b"><div class="narr">{E(p["narrative"])}</div><div class="files">{files}</div></div></div>')
    b.append("</section>")

    b.append(f'<section id="findings"><h2>What a human must check <span class="cnt">important first</span></h2>')
    b.append('<div class="filter"><button class="on" data-f="all">All</button><button data-f="critical">Critical</button><button data-f="medium">Medium</button><button data-f="low">Low</button>'
             + "".join(f'<button data-f="{E(t)}">{E(t)}</button>' for t in tags) + "</div>")
    if findings:
        b.extend(finding_card(f, hunks) for f in findings)
    else:
        b.append('<div class="empty">Nothing flagged. That is a claim, not a guarantee — the "Everything else" list below is what was looked at.</div>')
    b.append("</section>")

    # How to check — after the findings (those are the priority) but before the noise, because it is
    # the section a reviewer acts on when they decide not to take the report's word for it.
    checks = report.get("how_to_check") or []
    if checks:
        runnable = [c for c in checks if c.get("request")]
        b.append(f'<section id="check"><h2>How to check <span class="cnt" id="ck-count" data-total="{len(checks)}">0 of {len(checks)} verified</span></h2>')
        if runnable:
            b.append('<div class="ck-bar"><label for="base-url">Base URL</label>'
                     '<input id="base-url" type="url" spellcheck="false" placeholder="http://localhost:3000">'
                     '<button class="btn" id="dl-postman">⬇ Postman collection</button></div>'
                     '<div class="ck-warn">Requests are sent from this page to the URL above — a real server, with your '
                     'cookies. Cross-origin calls need that server to allow this origin; when it does not, the browser '
                     'blocks the send and the curl button is the way through.</div>')
        b.extend(check_card(c) for c in checks)
        b.append("</section>")
        b.append('<script type="application/json" id="check-store">'
                 + json.dumps({c["id"]: c["request"] for c in runnable}).replace("</", "<\\/") + "</script>")
        b.append('<script type="application/json" id="postman-store">'
                 + json.dumps(postman_collection(checks, f'{meta.get("repo", "change")} · {meta.get("branch", "")}'.strip(" ·"))).replace("</", "<\\/") + "</script>")

    # The MODEL wins over `report.folded`. That field is a verbatim copy the analyst makes for
    # chat/export consumers, so when the two disagree the copy is the stale one — a re-render after
    # a classifier fix kept showing the old, wrong fold labels because the copy was preferred.
    folded = model.get("folds") or report.get("folded") or []

    # Conversation: comments (feedback.jsonl, type=comment) + answers (answers.jsonl)
    def read_jsonl(name):
        fp = os.path.join(d, name); out = []
        if os.path.exists(fp):
            for l in open(fp):
                try: out.append(json.loads(l))
                except Exception: pass
        return out
    comments = [e for e in read_jsonl("feedback.jsonl") if e.get("type") == "comment" and e.get("id")]
    answers = {a["id"]: a for a in read_jsonl("answers.jsonl") if a.get("id")}
    seen_c = set(); threads = []
    for c in comments:
        if c["id"] in seen_c: continue
        seen_c.add(c["id"]); threads.append(c)
    def answer_html(t):
        paras = [p for p in re.split(r"\n\s*\n", t.strip()) if p.strip()]
        def inl(x): return re.sub(r"`([^`]+)`", lambda m: "<code>" + E(m.group(1)) + "</code>", E(x)).replace("\n", "<br>")
        return "".join(f"<p>{inl(p)}</p>" for p in paras)
    b.append(f'<section id="conversation"><h2>Conversation <span class="cnt">select any text → Ask</span></h2><div id="threads">')
    for c in reversed(threads):
        ans = answers.get(c["id"]); an = c.get("anchor") or {}
        b.append('<div class="thread" id="t-' + E(c["id"]) + '"><div class="anchor">“' + E(an.get("text", "")) + '” <small>· ' + E(an.get("section", "")) + ((" · " + E(an["finding"])) if an.get("finding") else "") + '</small></div>'
                 + '<div class="ctext">' + E(c.get("text", "")) + '</div>'
                 + (('<div class="ans"><b>Claude</b>' + answer_html(ans["text"]) + '</div>') if ans else '<div class="st open">Open — not answered yet</div>')
                 + '</div>')
    b.append('</div>' + ('<div class="empty" id="threads-empty">No comments yet. Select a word or sentence anywhere above and tap <b>Ask about this</b>.</div>' if not threads else '') + '</section>')

    flagged_files = {f["file"] for f in findings}
    rest = [f for f in model["files"] if f["substantive_hunks"] and f["path"] not in flagged_files]
    b.append(f'<section id="unreviewed"><h2>Everything else that changed <span class="cnt">{len(rest)} files, nothing flagged</span></h2><div class="unrev">')
    b.append('<div class="empty">Substantive but not surfaced. Fresh eyes welcome — ⚑ raises a gut-flag for Claude to dig into.</div>')
    # One store of per-file changed code (substantive hunks, capped) — read lazily by the
    # "Everything else" rows and by every ⟨/⟩ file chip in the views.
    MAX_LINES = 400
    store = {}
    for f in model["files"]:
        hs = [h["id"] for h in f["hunks"] if h["category"] == "substantive"]
        body, used, cut = [], 0, 0
        for hid in hs:
            if hid not in hunks: continue
            h, path = hunks[hid]
            if used >= MAX_LINES: cut += len(h.lines); continue
            body.append(hunk_html(h, path)); used += len(h.lines)
        if cut: body.append(f'<div class="empty">… {cut} more lines not shown (open the file for the rest)</div>')
        status = f["status"] + (f' ← {f["old_path"]}' if f.get("old_path") else "") + (f' ← moved from {f["moved_from"]}' if f.get("moved_from") else "")
        store[f["path"]] = {"status": status, "html": "".join(body) or '<div class="empty">no substantive hunks (folded as noise: ' + E(f.get("noise_kind") or ", ".join(sorted({h["category"] for h in f["hunks"]})) or "—") + ')</div>'}
    for f in rest:
        why = (report.get("unreviewed_notes") or {}).get(f["path"], "")
        b.append(f'<div class="row fold-row" data-file="{E(f["path"])}"><span class="tw">▶</span><span class="rp">{E(f["path"])} <span style="color:var(--fg3)">· {E(store[f["path"]]["status"])} · {f["substantive_hunks"]} hunk{"s" if f["substantive_hunks"] != 1 else ""}{(" · " + E(why)) if why else ""}</span></span><button data-file="{E(f["path"])}">⚑</button></div>'
                 f'<div class="row-body" data-file="{E(f["path"])}"><div class="row-code"></div><div class="row-close"><button class="btn">▲ Collapse {E(os.path.basename(f["path"]))}</button></div></div>')
    b.append("</div></section>")

    # Noise goes LAST. Everything above it is something the reader must act on or account for;
    # this is the register of what was deliberately hidden, which matters for trust but never
    # competes for attention with the findings or the substantive-but-unflagged list.
    b.append(f'<section id="folded"><h2>Folded as noise <span class="cnt">{st["noise_pct"]}% of changed lines</span></h2>')
    b.extend(fold_card(g, known_paths, hunks) for g in folded) if folded else b.append('<div class="empty">No noise detected.</div>')
    b.append("</section>")

    b.append('<script type="application/json" id="file-store">' + json.dumps(store).replace("</", "<\\/") + '</script>')
    # Folded hunks, keyed by id. The file store holds only SUBSTANTIVE hunks, so without this the
    # very lines a fold card is about — the moved import, the reworded comment — render nowhere in
    # the report, and "show files" opened the file's unrelated real changes instead.
    # Walk followers too — an import rewrite nested under the rename it follows is exactly the kind
    # of hunk a reader opens to confirm the rename really was only a rename.
    fold_hunk_ids = {
        hid
        for g in folded
        for it in g.get("items", [])
        for node in (it, *it.get("followers", []))
        for hid in (node.get("hunk_ids") or [])
    }
    hunk_store = {hid: hunk_html(*hunks[hid]) for hid in sorted(fold_hunk_ids) if hid in hunks}
    b.append('<script type="application/json" id="hunk-store">' + json.dumps(hunk_store).replace("</", "<\\/") + '</script>')
    b.append('<div class="sheet-bg" id="sheet-bg"></div><div class="sheet" id="sheet"><div class="sheet-h"><span class="sheet-t" id="sheet-t"></span><button class="btn" id="sheet-x">✕</button></div><div class="sheet-b" id="sheet-b"></div></div>')

    data = {"report_id": report_id, "repo": meta.get("repo", ""), "range_label": meta.get("range_label", ""),
            "findings": [{"id": f["id"], "severity": f["severity"], "tags": f.get("tags", [])} for f in findings]}
    out = tpl.replace("__TITLE__", E(title)).replace("__BODY__", "\n".join(b)).replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out_path = a.out or os.path.join(d, "index.html")
    open(out_path, "w").write(out)
    print(f"rendered {out_path} ({len(out)//1024} KB): {counts['critical']}C/{counts['medium']}M/{counts['low']}L, {len(report['graph'].get('nodes', []))} map nodes")

if __name__ == "__main__":
    main()
