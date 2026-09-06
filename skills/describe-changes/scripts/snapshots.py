#!/usr/bin/env python3
"""snapshots.py — keep every version of a report, and say what changed between two of them.

A report is read more than once: first when the change is described, again after the review's
fixes land. The second reading asks a different question — *what moved since I last looked* — and
answering it by re-reading the whole report is the failure this tool exists to prevent.

A snapshot is the small, durable part of a report (report.json + meta.json + the model's stats),
saved under `<out>/snapshots/<seq>-<head7>[-dirty]/`. Identical consecutive states are not saved
twice, so re-rendering while editing does not bury the version the reader actually read.

  save  --dir OUT [--label L]        snapshot the current report (no-op when nothing changed)
  list  --dir OUT                    what snapshots exist
  diff  --dir OUT [--from A --to B]  what changed between them (default: last saved → current)

`--to working` (the default) compares the saved snapshot against the report on disk right now.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_keys import check_key, finding_key, finding_site_key, norm_claim

SNAP_DIR = "snapshots"
KEEP = 20

def _read(path, default=None):
    try:
        return json.load(open(path))
    except Exception:
        return default

def snap_dir(d):
    return os.path.join(d, SNAP_DIR)

def list_snapshots(d):
    root = snap_dir(d)
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        info = _read(os.path.join(root, name, "snapshot.json"))
        if info:
            info["name"] = name
            out.append(info)
    return sorted(out, key=lambda s: s.get("seq", 0))

def load_snapshot(d, name):
    p = os.path.join(snap_dir(d), name)
    return {"info": _read(os.path.join(p, "snapshot.json"), {}),
            "report": _read(os.path.join(p, "report.json"), {}),
            "meta": _read(os.path.join(p, "meta.json"), {})}

def current(d):
    return {"info": {"name": "working", "label": "the report as it stands now"},
            "report": _read(os.path.join(d, "report.json"), {}),
            "meta": _read(os.path.join(d, "meta.json"), {}),
            "model": _read(os.path.join(d, "diff-model.json"), {})}

def _fingerprint(report, meta):
    return json.dumps({"findings": [(f.get("id"), f.get("severity"), f.get("title"), f.get("file"))
                                    for f in report.get("findings", [])],
                       "checks": [check_key(c) for c in report.get("how_to_check") or []],
                       "summary": report.get("summary"),
                       "tree": meta.get("fingerprint")}, sort_keys=True, ensure_ascii=False)

def cmd_save(a):
    d = a.dir
    report, meta = _read(os.path.join(d, "report.json")), _read(os.path.join(d, "meta.json"), {})
    if not report:
        print("no report.json to snapshot"); return
    prior = list_snapshots(d)
    fp = _fingerprint(report, meta)
    if prior and prior[-1].get("fingerprint") == fp:
        print(f"unchanged since {prior[-1]['name']} — not snapshotting again"); return
    seq = (prior[-1]["seq"] + 1) if prior else 1
    head = (meta.get("head_sha") or "")[:7] or "nohead"
    dirty = "-dirty" if meta.get("uncommitted_files") else ""
    name = f"{seq:03d}-{head}{dirty}"
    dest = os.path.join(snap_dir(d), name)
    os.makedirs(dest, exist_ok=True)
    for f in ("report.json", "meta.json"):
        if os.path.exists(os.path.join(d, f)):
            shutil.copy2(os.path.join(d, f), os.path.join(dest, f))
    model = _read(os.path.join(d, "diff-model.json"), {})
    info = {"seq": seq, "name": name, "label": a.label or "",
            "saved_at": meta.get("generated_at") or "",
            "head_sha": meta.get("head_sha", ""), "range_label": meta.get("range_label", ""),
            "uncommitted": len(meta.get("uncommitted_files") or []),
            "tree_sha": tree_commit(meta.get("root"), os.path.basename(d.rstrip("/")), seq,
                                    exclude=[os.path.relpath(d, meta["root"])] if meta.get("root") else []),
            "stats": model.get("stats", {}), "fingerprint": fp}
    json.dump(info, open(os.path.join(dest, "snapshot.json"), "w"), indent=2)
    for old in list_snapshots(d)[:-KEEP]:
        shutil.rmtree(os.path.join(snap_dir(d), old["name"]), ignore_errors=True)
    print(f"snapshot {name} saved" + (f" ({a.label})" if a.label else ""))

def _git(root, *args, **kw):
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60, **kw)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None

def tree_commit(root, slug, seq, exclude=()):
    """Freeze the worktree — tracked, staged and untracked alike — as a real commit, on a private ref.

    Without this a snapshot can only ever be compared as PROSE: `head_sha` describes the last commit,
    and the uncommitted work a report mostly consists of leaves no trace once it is edited. A commit
    built through a throwaway index touches neither the user's index nor their worktree, and the ref
    (`refs/describe-changes/…`) keeps the object alive against gc while staying out of branches,
    tags and pushes. This is what lets a later reading diff CODE against an earlier reading.
    """
    if not root or not os.path.isdir(os.path.join(root, ".git")):
        return None
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return None
    idx = os.path.join(root, ".git", f"dc-index-{seq}")
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        if _git(root, "read-tree", head, env=env) is None: return None
        if _git(root, "add", "-A", env=env) is None: return None
        # The report's own output is not the user's change: without this the frozen tree swallows
        # `.describe-changes/**` and the delta between two readings is mostly its own artifacts.
        # Dropped from the index AFTER the add rather than excluded by pathspec — `git add` fails
        # outright when an exclude pathspec names a gitignored path, which is the normal case.
        for x in (".describe-changes", *exclude):
            _git(root, "rm", "-r", "--cached", "-q", "--ignore-unmatch", "--", x, env=env)
        tree = _git(root, "write-tree", env=env)
        if not tree: return None
        commit = _git(root, "commit-tree", tree, "-p", head, "-m", f"describe-changes snapshot {seq}",
                      env=dict(env, GIT_AUTHOR_NAME="describe-changes", GIT_AUTHOR_EMAIL="dc@local",
                               GIT_COMMITTER_NAME="describe-changes", GIT_COMMITTER_EMAIL="dc@local"))
        if not commit: return None
        _git(root, "update-ref", f"refs/describe-changes/{slug}/{seq:03d}", commit)
        return commit
    finally:
        try: os.remove(idx)
        except OSError: pass

def _commits_between(root, a_sha, b_sha):
    if not root or not a_sha or not b_sha or a_sha == b_sha:
        return []
    try:
        out = subprocess.run(["git", "-C", root, "log", "--oneline", f"{a_sha}..{b_sha}"],
                             capture_output=True, text=True, timeout=15)
        return [l for l in out.stdout.splitlines() if l.strip()] if out.returncode == 0 else []
    except Exception:
        return []

def compute_delta(before, after):
    """What a reader who already read `before` needs to know about `after`."""
    rb, ra = before.get("report") or {}, after.get("report") or {}
    fb_ = {finding_key(f): f for f in rb.get("findings", [])}
    fa = {finding_key(f): f for f in ra.get("findings", [])}
    added_keys, gone_keys = [k for k in fa if k not in fb_], [k for k in fb_ if k not in fa]
    # A re-worded or re-rated finding is neither new nor gone; pair the leftovers by site so the
    # reader is told "this one moved", not "one vanished and another appeared".
    changed = []
    site_b = {}
    for k in gone_keys:
        site_b.setdefault(finding_site_key(fb_[k]), []).append(k)
    still_added, matched_gone = [], set()
    for k in added_keys:
        f = fa[k]
        pool = ([x for x in gone_keys if x not in matched_gone and fb_[x].get("file") == f.get("file")])
        if pool:
            old = fb_[pool[0]]; matched_gone.add(pool[0])
            changed.append({"id": f.get("id"), "was_id": old.get("id"), "file": f.get("file"),
                            "title": f.get("title"), "was_title": old.get("title"),
                            "severity": f.get("severity"), "was_severity": old.get("severity")})
        else:
            still_added.append(f)
    resolved = [fb_[k] for k in gone_keys if k not in matched_gone]

    cb = {check_key(c): c for c in (rb.get("how_to_check") or [])}
    ca = {check_key(c): c for c in (ra.get("how_to_check") or [])}
    # Same id, different content: the reader verified the OLD steps, so their tick was dropped —
    # which is only defensible if the report says so out loud. Such a card is re-written, NOT one
    # check appearing and another vanishing; listing it three times was worse than not saying it.
    id_b = {c.get("id"): check_key(c) for c in (rb.get("how_to_check") or [])}
    reworded_ids = {c.get("id") for c in (ra.get("how_to_check") or [])
                    if c.get("id") in id_b and id_b[c["id"]] != check_key(c)}
    checks_reworded = [c for c in (ra.get("how_to_check") or []) if c.get("id") in reworded_ids]
    checks_added = [c for k, c in ca.items() if k not in cb and c.get("id") not in reworded_ids]
    checks_gone = [c for k, c in cb.items() if k not in ca and c.get("id") not in reworded_ids]

    mb = before.get("meta") or {}
    ma = after.get("meta") or {}
    sb = (before.get("info") or {}).get("stats") or {}
    sa = (after.get("model") or {}).get("stats") or (after.get("info") or {}).get("stats") or {}
    commits = _commits_between(ma.get("root") or mb.get("root"), mb.get("head_sha"), ma.get("head_sha"))
    files_b = {f["path"] for f in (before.get("model") or {}).get("files", [])}
    return {
        "from": (before.get("info") or {}).get("name", "?"),
        "to": (after.get("info") or {}).get("name", "working"),
        "from_head": (mb.get("head_sha") or "")[:7], "to_head": (ma.get("head_sha") or "")[:7],
        "commits": commits,
        "uncommitted_before": len(mb.get("uncommitted_files") or []),
        "uncommitted_now": len(ma.get("uncommitted_files") or []),
        "findings_added": [{"id": f.get("id"), "severity": f.get("severity"), "title": f.get("title"),
                            "file": f.get("file")} for f in still_added],
        "findings_resolved": [{"id": f.get("id"), "severity": f.get("severity"), "title": f.get("title"),
                               "file": f.get("file")} for f in resolved],
        "findings_changed": changed,
        "checks_added": [{"id": c.get("id"), "feature": c.get("feature")} for c in checks_added],
        "checks_removed": [{"id": c.get("id"), "feature": c.get("feature")} for c in checks_gone],
        "checks_reworded": [{"id": c.get("id"), "feature": c.get("feature")} for c in checks_reworded],
        "stats_before": sb, "stats_after": sa,
        "summary_changed": (rb.get("summary") or "") != (ra.get("summary") or ""),
    }

def build_code_delta(d, snap, report, dl):
    """A REAL report over the code between a snapshot and now — its own diff, folds, map and stats.

    The filtered-cards page answers "which findings moved"; this answers "show me what changed",
    which is the question a reviewer actually returns with. It is the ordinary pipeline pointed at a
    narrower range: collect-diff over `<snapshot tree>..<now>`, then a report.json whose narrative is
    the current report's, filtered to what that range contains. Findings keep `file`/`lines` but lose
    `hunks` — hunk ids belong to the model they were computed in, and a stale id opens the wrong code.

    Returns the delta report dir, or None when the range cannot be built (a snapshot taken before
    tree refs existed, a repo that has moved on, nothing changed).
    """
    root = (snap.get("meta") or {}).get("root")
    a_sha = (snap.get("info") or {}).get("tree_sha")
    if not root or not a_sha or _git(root, "cat-file", "-e", a_sha + "^{commit}") is None:
        return None
    seq = (snap.get("info") or {}).get("seq", 0)
    b_sha = (tree_commit(root, os.path.basename(d.rstrip("/")) + "-now", 999,
                         exclude=[os.path.relpath(d, root)]) or _git(root, "rev-parse", "HEAD"))
    if not b_sha or a_sha == b_sha:
        return None
    out = os.path.join(d, "deltas", f"{seq:03d}")
    collect = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect-diff.sh")
    r = subprocess.run(["bash", collect, "--out", out, a_sha, b_sha], capture_output=True, text=True, cwd=root)
    if r.returncode != 0:                       # exit 2 = the two trees are identical
        return None
    model = _read(os.path.join(out, "diff-model.json"), {})
    files = {f["path"] for f in model.get("files", [])}
    if not files:
        return None
    # This range already CONTAINS the uncommitted work (both ends are frozen trees), so the repo's
    # "still uncommitted" list is not a fact about this page — and rendering it would offer file
    # chips for paths outside the range, which open nothing.
    dmeta = _read(os.path.join(out, "meta.json"), {})
    dmeta["uncommitted_files"] = []
    dmeta["range_label"] = f"since {(snap.get('info') or {}).get('label') or (snap.get('info') or {}).get('name','the last reading')}"
    json.dump(dmeta, open(os.path.join(out, "meta.json"), "w"), indent=2)

    fin_by_id = {f["id"]: f for f in report.get("findings", [])}
    moved_ids = [f["id"] for f in dl["findings_added"]] + [c["id"] for c in dl["findings_changed"]]
    keep = [fin_by_id[i] for i in moved_ids if i in fin_by_id]
    keep += [f for f in report.get("findings", [])
             if f.get("file") in files and f["id"] not in moved_ids]
    findings = [{k: v for k, v in f.items() if k != "hunks"} for f in keep]
    chk_by_id = {c["id"]: c for c in (report.get("how_to_check") or [])}
    checks = [chk_by_id[c["id"]] for c in dl["checks_reworded"] + dl["checks_added"] if c["id"] in chk_by_id]

    graph = report.get("graph") or {}
    nodes = [n for n in graph.get("nodes", []) if not n.get("file") or n["file"] in files]
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in graph.get("edges", []) if e.get("from") in node_ids and e.get("to") in node_ids]
    if len(nodes) < 2:
        nodes, edges = [], []
    phases = []
    for p in report.get("phases", []):
        inside = [f for f in p.get("files", []) if f in files]
        if inside:
            phases.append(dict(p, files=inside))

    label = (snap.get("info") or {}).get("label") or (snap.get("info") or {}).get("name", "the last reading")
    st = model.get("stats", {})
    bits = []
    if dl["commits"]: bits.append(f"{len(dl['commits'])} commit{'s' if len(dl['commits']) != 1 else ''}")
    bits.append(f"{st.get('files_substantive', len(files))} file{'s' if st.get('files_substantive', 1) != 1 else ''} with substantive changes")
    if dl["findings_resolved"]: bits.append(f"{len(dl['findings_resolved'])} finding{'s' if len(dl['findings_resolved']) != 1 else ''} resolved")
    if dl["findings_added"]: bits.append(f"{len(dl['findings_added'])} new")
    delta_report = {
        "title": f"{report.get('title', 'Changes')} — since {label}",
        "intent": f"Only what changed since {label}. The whole change is in the full report.",
        "summary": "This page is the code that moved since that reading: " + ", ".join(bits)
                   + ". Findings and checks are the ones that concern it; everything settled before "
                     "that reading is deliberately absent.",
        "phases": phases,
        "graph": {"narrative": (graph.get("narrative") or "") and f"{graph['narrative']} (scoped to what changed since {label})",
                  "nodes": nodes, "edges": edges},
        "findings": findings,
        "how_to_check": checks,
        "folded": model.get("folds", []),
        "unreviewed_notes": {k: v for k, v in (report.get("unreviewed_notes") or {}).items() if k in files},
    }
    json.dump(delta_report, open(os.path.join(out, "report.json"), "w"), ensure_ascii=False, indent=2)
    return out

def _resolve(d, which, default_last=True):
    snaps = list_snapshots(d)
    if which in (None, "", "last", "latest"):
        return load_snapshot(d, snaps[-1]["name"]) if snaps else None
    if which == "working":
        return current(d)
    if which == "first":
        return load_snapshot(d, snaps[0]["name"]) if snaps else None
    for s in snaps:
        if which in (s["name"], str(s["seq"]), f"{s['seq']:03d}"):
            return load_snapshot(d, s["name"])
    raise SystemExit(f"no snapshot '{which}' in {snap_dir(d)} — try `snapshots.py list --dir {d}`")

def cmd_list(a):
    snaps = list_snapshots(a.dir)
    if not snaps:
        print("no snapshots yet — the first render of this report will create one"); return
    for s in snaps:
        st = s.get("stats") or {}
        print(f"{s['seq']:>3}  {s['name']:<24} {s.get('saved_at','')[:16]:<17} "
              f"{st.get('files_substantive','?')} files, {st.get('noise_pct','?')}% folded"
              + (f", {s['uncommitted']} uncommitted" if s.get("uncommitted") else "")
              + (f"  — {s['label']}" if s.get("label") else ""))

def render_text(delta):
    L = []
    head = f"Since {delta['from']}"
    if delta["from_head"] and delta["to_head"] and delta["from_head"] != delta["to_head"]:
        head += f" ({delta['from_head']} → {delta['to_head']}, {len(delta['commits'])} commit"
        head += f"{'s' if len(delta['commits']) != 1 else ''})"
    L.append(head)
    for c in delta["commits"][:10]:
        L.append(f"    {c}")
    def block(title, rows, fmt):
        if rows:
            L.append(f"\n{title} ({len(rows)})")
            L.extend(f"  {fmt(r)}" for r in rows)   # extend, not `+=`: `+=` rebinds L as local
    block("Findings resolved — gone from the report", delta["findings_resolved"],
          lambda f: f"− {f['id']} [{f['severity']}] {f['title']}")
    block("Findings added", delta["findings_added"],
          lambda f: f"+ {f['id']} [{f['severity']}] {f['title']}")
    block("Findings changed", delta["findings_changed"],
          lambda c: (f"~ {c['id']} [{c['severity']}]" +
                     (f" (was {c['was_severity']})" if c["was_severity"] != c["severity"] else "") +
                     f" {c['title']}"))
    block("Checks added", delta["checks_added"], lambda c: f"+ {c['id']} {c['feature']}")
    block("Checks removed", delta["checks_removed"], lambda c: f"− {c['id']} {c['feature']}")
    block("Checks re-written — any tick on these was dropped, the steps are not the ones you ran",
          delta["checks_reworded"], lambda c: f"~ {c['id']} {c['feature']}")
    sb, sa = delta["stats_before"] or {}, delta["stats_after"] or {}
    if sb and sa and (sb.get("files_substantive") != sa.get("files_substantive")
                      or sb.get("noise_pct") != sa.get("noise_pct")):
        L.append(f"\nScope: {sb.get('files_substantive','?')} → {sa.get('files_substantive','?')} files to read, "
                 f"{sb.get('noise_pct','?')}% → {sa.get('noise_pct','?')}% folded")
    if delta["summary_changed"]:
        L.append("\nThe summary was rewritten — read the header again.")
    if len(L) == 1:
        L.append("\nNothing changed in the report.")
    return "\n".join(L)

def cmd_diff(a):
    before = _resolve(a.dir, a.__dict__["from"])
    if before is None:
        print("no snapshot to compare against yet"); return
    after = _resolve(a.dir, a.to) if a.to else current(a.dir)
    if a.__dict__["from"] in (None, "", "last", "latest") and (a.to in (None, "working")):
        after = current(a.dir)
    delta = compute_delta(before, after)
    print(json.dumps(delta, indent=2, ensure_ascii=False) if a.json else render_text(delta))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("save"); p.add_argument("--dir", required=True); p.add_argument("--label"); p.set_defaults(fn=cmd_save)
    p = sp.add_parser("list"); p.add_argument("--dir", required=True); p.set_defaults(fn=cmd_list)
    p = sp.add_parser("diff"); p.add_argument("--dir", required=True)
    p.add_argument("--from", dest="from", help="snapshot name, seq, 'first' or 'last' (default: last)")
    p.add_argument("--to", help="snapshot name, seq, or 'working' (default: the report as it stands)")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_diff)
    a = ap.parse_args(); a.fn(a)

if __name__ == "__main__":
    main()
