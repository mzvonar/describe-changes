#!/usr/bin/env python3
"""check-report.py — deterministic guard on report.json before rendering.

Exit 0 when the report is well-formed; non-zero with a list of problems otherwise.
Enforces the credibility budget: ≤ 3 critical (hard), ≤ 7 medium (warn), every finding has
`why_human` + `verify`, every file referenced exists in diff-model.json, every graph edge
references a known node, ids are unique and follow C1/M1/L1 numbering.
"""
import json, sys, os, re

SEV = {"critical": "C", "medium": "M", "low": "L"}
MAX_CRITICAL, MAX_MEDIUM = 3, 7
REQ_TOP = ["title", "summary", "phases", "graph", "findings", "folded"]

def repo_root_of(report_path):
    d = os.path.dirname(os.path.abspath(report_path))
    try:
        meta = json.load(open(os.path.join(d, "meta.json")))
        if meta.get("root") and os.path.isdir(meta["root"]): return meta["root"]
    except Exception: pass
    while d != "/":                                   # the report lives inside the repo it describes
        if os.path.isdir(os.path.join(d, ".git")): return d
        d = os.path.dirname(d)
    return None

def check_divergence(f, fid, root):
    """A `convention` finding must cite what it diverges FROM.

    This is the whole difference between a convention finding and a style opinion. "I would have
    written it the other way" is taste and costs credibility; "the rule says X and these two
    siblings do X" is checkable, and the reviewer can open both. So the citation is required, its
    paths must exist, and a claim resting on local precedent needs TWO neighbours — one sibling
    doing it differently is a coincidence, not a convention."""
    errs, warns = [], []
    refs = f.get("diverges_from") or []
    if isinstance(refs, (str, dict)): refs = [refs]
    if "convention" not in (f.get("tags") or []):
        if refs: warns.append(f"{fid}: has 'diverges_from' but is not tagged 'convention'")
        return errs, warns
    if not refs:
        errs.append(f"{fid}: a 'convention' finding must cite what it diverges from in 'diverges_from' "
                    f"(a rule like CLAUDE.md:161, or 2+ neighbours that do it the other way). "
                    f"Uncited, it is taste — drop it or cite it.")
        return errs, warns
    paths = []
    for ref in refs:
        s = ref.get("ref", "") if isinstance(ref, dict) else str(ref)
        if not s: errs.append(f"{fid}: empty entry in 'diverges_from'"); continue
        p = s.split(":")[0]
        paths.append(p)
        if root and not os.path.exists(os.path.join(root, p)):
            errs.append(f"{fid}: diverges_from '{s}' — no such file in the repo")
    rules = [p for p in paths if os.path.splitext(p)[1] in (".md", ".mdc", ".txt") or os.path.basename(p).startswith(".")]
    if not rules and len(set(paths)) < 2:
        errs.append(f"{fid}: 'diverges_from' cites one neighbour and no written rule — one sibling is a "
                    f"coincidence. Cite the rule, or a second file that does it the other way.")
    return errs, warns

def main():
    if len(sys.argv) < 2:
        print("usage: check-report.py <report.json> [diff-model.json]"); sys.exit(2)
    rp = sys.argv[1]
    r = json.load(open(rp))
    model_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(rp), "diff-model.json")
    model = json.load(open(model_path)) if os.path.exists(model_path) else None
    repo_root = repo_root_of(rp)
    known_files = {f["path"] for f in model["files"]} | {f["old_path"] for f in model["files"] if f.get("old_path")} if model else None
    errs, warns = [], []
    for k in REQ_TOP:
        if k not in r: errs.append(f"missing top-level key '{k}'")
    if errs: print("\n".join("ERROR: " + e for e in errs)); sys.exit(1)
    # Brevity is a correctness property here, not taste: the failure this tool exists to prevent is a
    # rubber-stamped signature, and an over-long header is the cheapest way to cause one. Enforced
    # mechanically because "keep it short" as advice loses to the urge to explain your own work.
    n_sum = len(r["summary"])
    if n_sum < 20:
        warns.append(f"summary is too short to be useful ({n_sum} chars)")
    elif n_sum > 700:
        errs.append(f"summary is {n_sum} chars; hard cap 700. Cut to what a reviewer cannot infer from the intent line.")
    elif n_sum > 420:
        warns.append(f"summary is {n_sum} chars — aim for ≤ 420 (about 3 sentences)")
    if len(re.findall(r"[.!?](?:\s|$)", r["summary"])) > 4:
        warns.append("summary runs to more than 4 sentences — the header is skimmed, not read")
    # Mechanism-first tell. A functional summary names what a person can now do; a mechanical one
    # names the symbols that do it. Counting `backticked` identifiers is a crude proxy, but it fires
    # on exactly the shape that reads like a commit message — and that shape is the second-commonest
    # reason this section gets skipped, after length.
    n_sym = len(re.findall(r"`[^`]+`", r["summary"]))
    if n_sym > 3:
        warns.append(f"summary names {n_sym} code symbols — say what a PERSON can now do and which rule stops them; keep mechanism for where it IS the decision")
    if r.get("intent"):
        if len(r["intent"]) > 260:
            warns.append(f"intent is {len(r['intent'])} chars — it should be ONE line naming what was asked, not a retelling")
        # Duplicate detection: intent and summary answer different questions (asked vs done). When they
        # share most of their vocabulary the reader gets the same paragraph twice and starts skipping.
        sig = lambda s: {w for w in re.findall(r"[a-z]{5,}", s.lower())}
        a, c = sig(r["intent"]), sig(r["summary"])
        if a and c:
            overlap = len(a & c) / min(len(a), len(c))
            if overlap > 0.55:
                warns.append(f"intent and summary overlap {overlap:.0%} — intent is what was ASKED, summary is what CHANGED and why it is non-obvious; do not restate")
    conf = r.get("confession")
    if isinstance(conf, list):
        for i, item in enumerate(conf):
            if not isinstance(item, dict) or not item.get("point"):
                errs.append(f"confession[{i}]: each item needs a one-line 'point' (plus optional 'detail')")
            elif len(item["point"]) > 180:
                warns.append(f"confession[{i}]: point is {len(item['point'])} chars — it is a headline; move the rest into 'detail'")
        if len(conf) > 6:
            warns.append(f"{len(conf)} confession items — if everything is doubtful nothing is; keep the ones that would change what a reviewer does")
    elif isinstance(conf, str) and len(conf) > 300:
        warns.append("confession is a long string — use the list form [{point, detail}] so a reviewer can skim it and expand only what matters")

    ids, counts = set(), {"critical": 0, "medium": 0, "low": 0}
    for f in r["findings"]:
        fid = f.get("id", "?")
        if fid in ids: errs.append(f"duplicate finding id {fid}")
        ids.add(fid)
        sev = f.get("severity")
        if sev not in SEV: errs.append(f"{fid}: severity must be critical|medium|low (got {sev!r})"); continue
        counts[sev] += 1
        if not re.fullmatch(SEV[sev] + r"\d+", fid): errs.append(f"{fid}: id must be {SEV[sev]}<n> for severity {sev}")
        for key in ("title", "why_human", "verify", "file"):
            if not f.get(key): errs.append(f"{fid}: missing '{key}'")
        if known_files is not None and f.get("file") and f["file"] not in known_files:
            errs.append(f"{fid}: file '{f['file']}' is not in the diff")
        if f.get("lines") and not re.fullmatch(r"\d+(-\d+)?", str(f["lines"])): errs.append(f"{fid}: lines must be 'N' or 'N-M'")
        if len(f.get("why_human", "")) > 400: warns.append(f"{fid}: why_human is long ({len(f['why_human'])} chars) — compress")
        e2, w2 = check_divergence(f, fid, repo_root)
        errs += e2; warns += w2
    if counts["critical"] > MAX_CRITICAL:
        errs.append(f"{counts['critical']} critical findings > budget {MAX_CRITICAL}. If everything is critical, nothing is — demote.")
    if counts["medium"] > MAX_MEDIUM: warns.append(f"{counts['medium']} medium findings > soft budget {MAX_MEDIUM}")

    # How-to-check: the section exists so a reviewer can exercise the change instead of trusting the
    # report, so a step list that cannot be followed is worse than no card at all.
    check_ids = set()
    for i, c in enumerate(r.get("how_to_check") or []):
        cid = c.get("id", f"#{i}")
        if cid in check_ids: errs.append(f"duplicate how_to_check id {cid}")
        check_ids.add(cid)
        if not re.fullmatch(r"V\d+", str(cid)): errs.append(f"how_to_check {cid}: id must be V<n>")
        if not c.get("feature"): errs.append(f"how_to_check {cid}: missing 'feature'")
        if not c.get("steps"): errs.append(f"how_to_check {cid}: needs at least one step")
        if not c.get("expect"): warns.append(f"how_to_check {cid}: no 'expect' — a step list with no stated outcome cannot be failed")
        surface = c.get("surface", "ui")
        if surface not in ("ui", "api", "cli"): errs.append(f"how_to_check {cid}: surface must be ui|api|cli (got {surface!r})")
        req = c.get("request")
        if req:
            if surface != "api": warns.append(f"how_to_check {cid}: 'request' is only meaningful with surface:\"api\"")
            if not req.get("method") or not req.get("path"):
                errs.append(f"how_to_check {cid}: request needs 'method' and 'path'")
            elif not str(req["path"]).startswith("/"):
                errs.append(f"how_to_check {cid}: request.path must start with '/' (the base URL is chosen in the page)")
        elif surface == "api":
            warns.append(f"how_to_check {cid}: surface is api but there is no 'request' — no curl, Postman entry or inline send can be offered")

    g = r["graph"]; node_ids = {n.get("id") for n in g.get("nodes", [])}
    for n in g.get("nodes", []):
        for key in ("id", "label", "kind", "change"):
            if not n.get(key): errs.append(f"graph node {n.get('id','?')}: missing '{key}'")
        if n.get("change") not in {"added", "modified", "removed", "moved", "renamed", "split", "unchanged"}:
            errs.append(f"graph node {n.get('id')}: bad change '{n.get('change')}'")
    for e in g.get("edges", []):
        if e.get("from") not in node_ids or e.get("to") not in node_ids:
            errs.append(f"graph edge {e.get('from')}→{e.get('to')} references unknown node")
    if len(g.get("nodes", [])) > 40: warns.append(f"graph has {len(g['nodes'])} nodes — the map should fit a phone; prune to the change-relevant symbols")

    for i, p in enumerate(r["phases"]):
        for key in ("id", "title", "narrative"):
            if not p.get(key): errs.append(f"phase[{i}]: missing '{key}'")
        for fp in p.get("files", []):
            if known_files is not None and fp not in known_files: errs.append(f"phase {p.get('id')}: file '{fp}' not in diff")
    for fid in r.get("unreviewed", []):
        if known_files is not None and fid not in known_files: warns.append(f"unreviewed '{fid}' not in diff")

    for w in warns: print("WARN:", w)
    for e in errs: print("ERROR:", e)
    print(f"findings: {counts['critical']} critical / {counts['medium']} medium / {counts['low']} low; "
          f"{len(g.get('nodes', []))} nodes / {len(g.get('edges', []))} edges; {len(r['phases'])} phases")
    sys.exit(1 if errs else 0)

if __name__ == "__main__":
    main()
