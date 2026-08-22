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

def main():
    if len(sys.argv) < 2:
        print("usage: check-report.py <report.json> [diff-model.json]"); sys.exit(2)
    rp = sys.argv[1]
    r = json.load(open(rp))
    model_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(rp), "diff-model.json")
    model = json.load(open(model_path)) if os.path.exists(model_path) else None
    known_files = {f["path"] for f in model["files"]} | {f["old_path"] for f in model["files"] if f.get("old_path")} if model else None
    errs, warns = [], []
    for k in REQ_TOP:
        if k not in r: errs.append(f"missing top-level key '{k}'")
    if errs: print("\n".join("ERROR: " + e for e in errs)); sys.exit(1)
    if not (20 <= len(r["summary"]) <= 900): warns.append(f"summary should be 1–4 sentences ({len(r['summary'])} chars)")

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
    if counts["critical"] > MAX_CRITICAL:
        errs.append(f"{counts['critical']} critical findings > budget {MAX_CRITICAL}. If everything is critical, nothing is — demote.")
    if counts["medium"] > MAX_MEDIUM: warns.append(f"{counts['medium']} medium findings > soft budget {MAX_MEDIUM}")

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
