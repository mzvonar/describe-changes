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
