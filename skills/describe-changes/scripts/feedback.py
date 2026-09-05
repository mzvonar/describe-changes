#!/usr/bin/env python3
"""feedback.py — the describe-changes learning loop (local store + pluggable shared backend).

Store: $DESCRIBE_CHANGES_HOME (default ~/.describe-changes/) holding
  lessons.jsonl   every normalised feedback event (append-only)
  config.json     optional: {"backend": {"type": "http", "url": "...", "token_env": "DC_TOKEN"},
                             "user": "mato", "team": "..."}

Subcommands
  ingest  <feedback.jsonl | feedback.json> --dir <report-dir>   normalise UI events + attach finding context
  question "<text>" --dir <report-dir> [--finding C1] [--answered-by-reading file:lines]
                                                               log a follow-up question the user asked in chat
  outcome --dir <report-dir> --kind <missed|false_positive|confirmed> --finding <id|new> --text "..."
                                                               log what the Q&A revealed (a missed finding etc.)
  push    [--since ISO]                                        send unsent events to the configured shared backend
  digest  [--since ISO] [--repo X]                             maintainer view: cluster lessons by kind/tag/severity
  export  [--since ISO]                                        dump raw JSON to stdout
Every event carries: ts, type, repo, range, finding (id/severity/tags/title), skill_version, user.
"""
import argparse, json, os, sys, datetime, urllib.request, collections

HOME = os.environ.get("DESCRIBE_CHANGES_HOME") or os.path.expanduser("~/.describe-changes")
LESSONS = os.path.join(HOME, "lessons.jsonl")
CONFIG = os.path.join(HOME, "config.json")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
def cfg():
    try: return json.load(open(CONFIG))
    except Exception: return {}
def skill_version():
    for p in (os.path.join(SKILL_DIR, "VERSION"), os.path.join(os.path.dirname(SKILL_DIR), ".describe-changes-version")):
        if os.path.exists(p):
            for l in open(p):
                if l.startswith("sha="): return l.strip()[4:11]
                if not l.startswith("#") and l.strip(): return l.strip()
    return "dev"
def load_ctx(d):
    ctx = {"repo": "", "range": "", "findings": {}}
    try:
        m = json.load(open(os.path.join(d, "meta.json"))); ctx["repo"], ctx["range"] = m.get("repo", ""), m.get("range_label", "")
    except Exception: pass
    try:
        r = json.load(open(os.path.join(d, "report.json")))
        ctx["findings"] = {f["id"]: {"id": f["id"], "severity": f["severity"], "tags": f.get("tags", []), "title": f["title"], "file": f["file"]} for f in r["findings"]}
        ctx["repo"] = ctx["repo"] or r.get("repo", "")
    except Exception: pass
    return ctx
def append(events):
    os.makedirs(HOME, exist_ok=True)
    with open(LESSONS, "a") as fh:
        for e in events: fh.write(json.dumps(e) + "\n")
def read_all(since=None):
    if not os.path.exists(LESSONS): return []
    out = []
    for l in open(LESSONS):
        l = l.strip()
        if not l: continue
        try: e = json.loads(l)
        except Exception: continue
        if since and e.get("ts", "") < since: continue
        out.append(e)
    return out
def base(ctx, typ, **kw):
    e = {"ts": now(), "type": typ, "repo": ctx["repo"], "range": ctx["range"], "skill_version": skill_version(),
         "user": cfg().get("user") or os.environ.get("USER", ""), "pushed": False}
    e.update(kw); return e

def cmd_ingest(a):
    ctx = load_ctx(a.dir)
    raw = open(a.src).read().strip()
    events = []
    try:
        doc = json.loads(raw); events = doc.get("events", []) if isinstance(doc, dict) else doc
    except json.JSONDecodeError:
        for l in raw.splitlines():
            if l.strip(): events.append(json.loads(l))
    def fid(x): return x.get("id") if isinstance(x, dict) else x
    seen = {(e.get("ts"), e.get("type"), fid(e.get("finding")), e.get("file")) for e in read_all()}
    out = []
    for ev in events:
        key = (ev.get("ts"), ev.get("type"), fid(ev.get("finding")), ev.get("file"))
        if key in seen: continue
        f = ctx["findings"].get(ev.get("finding") or "")
        out.append(base(ctx, ev.get("type", "unknown"), ts=ev.get("ts") or now(), source="ui",
                        finding=f or ({"id": ev.get("finding")} if ev.get("finding") else None),
                        file=ev.get("file"), text=ev.get("text"), undo=ev.get("undo")))
    append(out)
    kinds = collections.Counter(e["type"] for e in out)
    print(f"ingested {len(out)} new events → {LESSONS}" + (f" ({dict(kinds)})" if out else ""))

def cmd_question(a):
    ctx = load_ctx(a.dir); f = ctx["findings"].get(a.finding or "")
    append([base(ctx, "question", source="chat", text=a.text, finding=f, answered_by=a.answered_by_reading)])
    print("logged question")

def cmd_outcome(a):
    ctx = load_ctx(a.dir); f = ctx["findings"].get(a.finding or "")
    append([base(ctx, "outcome", source="chat", kind=a.kind, finding=f or {"id": a.finding}, text=a.text, file=a.file)])
    print(f"logged outcome {a.kind}")

def _jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            try: out.append(json.loads(l))
            except Exception: pass
    return out

def cmd_comments(a):
    """List comment threads from the report dir (feedback.jsonl + answers.jsonl)."""
    fb = _jsonl(os.path.join(a.dir, "feedback.jsonl")); ans = {x["id"]: x for x in _jsonl(os.path.join(a.dir, "answers.jsonl")) if x.get("id")}
    seen = set(); rows = []
    for e in fb:
        if e.get("type") != "comment" or not e.get("id") or e["id"] in seen: continue
        seen.add(e["id"]); an = e.get("anchor") or {}
        rows.append({"id": e["id"], "ts": e.get("ts"), "text": e.get("text"), "selection": an.get("text"), "context": an.get("context"),
                     "section": an.get("section"), "finding": an.get("finding"), "answered": e["id"] in ans})
    if a.open: rows = [r for r in rows if not r["answered"]]
    if a.json: print(json.dumps(rows, indent=2)); return
    if not rows: print("no " + ("open " if a.open else "") + "comments"); return
    for r in rows:
        print(f"[{r['id']}] {'answered' if r['answered'] else 'OPEN'} · {r['section']}{(' · ' + r['finding']) if r['finding'] else ''}")
        print(f"   selection: {r['selection']!r}")
        print(f"   context:   {(r['context'] or '')[:200]!r}")
        print(f"   question:  {r['text']}")

def cmd_notes(a):
    """Everything the reader typed or ticked that is NOT a comment thread.

    `comments` lists only ask-about-a-selection threads, so a note left on a finding card or a
    how-to-check card is invisible to it — it reports "no open comments" while real feedback sits
    unread in the file. That happened on the first report this shipped with, which is why this
    exists: one command answering "did the reader say anything, anywhere?".
    """
    fb = _jsonl(os.path.join(a.dir, "feedback.jsonl"))
    notes, verified, unmarked = [], set(), set()
    for e in fb:
        t = e.get("type")
        if t == "note" and e.get("text"):
            notes.append(("finding " + (e.get("finding") or "?"), e.get("ts"), e["text"]))
        elif t == "check_note" and e.get("text"):
            notes.append(("check " + (e.get("check") or "?"), e.get("ts"), e["text"]))
        elif t == "check_verified" and e.get("check"):
            verified.add(e["check"]); unmarked.discard(e["check"])
        elif t == "undo" and e.get("undo") == "check_verified" and e.get("check"):
            verified.discard(e["check"]); unmarked.add(e["check"])
    latest = {}          # later events win: a note edited twice shows once, with its final text
    for where, ts, text in notes: latest[where] = (ts, text)
    if a.json:
        print(json.dumps({"notes": [{"where": w, "ts": t, "text": x} for w, (t, x) in latest.items()],
                          "verified": sorted(verified), "unmarked": sorted(unmarked)}, indent=2)); return
    if verified: print("verified: " + ", ".join(sorted(verified)))
    if unmarked: print("un-marked again: " + ", ".join(sorted(unmarked)))
    if not latest:
        print("no notes")
        return
    for where, (ts, text) in latest.items():
        print(f"[{where}] {ts}\n   {text}")

def cmd_answer(a):
    """Store an answer for a comment id AND log the question as a lesson (the report failed to pre-answer it)."""
    text = a.text if a.text is not None else sys.stdin.read()
    fb = _jsonl(os.path.join(a.dir, "feedback.jsonl"))
    c = next((e for e in fb if e.get("type") == "comment" and e.get("id") == a.id), None)
    if c is None: raise SystemExit(f"comment {a.id} not found in {a.dir}/feedback.jsonl")
    with open(os.path.join(a.dir, "answers.jsonl"), "a") as fh:
        fh.write(json.dumps({"id": a.id, "ts": now(), "text": text.strip()}) + "\n")
    ctx = load_ctx(a.dir); an = c.get("anchor") or {}
    f = ctx["findings"].get(an.get("finding") or "")
    append([base(ctx, "question", source="comment", comment_id=a.id, text=c.get("text"), selection=an.get("text"),
                 section=an.get("section"), finding=f, improvement=a.improvement)])
    print(f"answered {a.id}; logged as improvement candidate → {LESSONS}. Re-render the report to show it.")

def cmd_push(a):
    c = cfg().get("backend") or {}
    evs = [e for e in read_all(a.since) if not e.get("pushed")]
    if not evs: print("nothing to push"); return
    if c.get("type") != "http" or not c.get("url"):
        print(f"no shared backend configured in {CONFIG} — {len(evs)} events stay local. See reference/learning-loop.md"); return
    hdr = {"Content-Type": "application/json"}
    tok = os.environ.get(c.get("token_env", ""), "")
    if tok: hdr["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(c["url"], data=json.dumps({"source": "describe-changes", "team": cfg().get("team"), "events": evs}).encode(), headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 300: raise SystemExit(f"push failed: HTTP {r.status}")
    allev = read_all(); pushed_ts = {e["ts"] + e["type"] for e in evs}
    for e in allev:
        if e["ts"] + e["type"] in pushed_ts: e["pushed"] = True
    with open(LESSONS, "w") as fh:
        for e in allev: fh.write(json.dumps(e) + "\n")
    print(f"pushed {len(evs)} events to {c['url']}")

def cmd_digest(a):
    evs = [e for e in read_all(a.since) if not a.repo or e.get("repo") == a.repo]
    if not evs: print("no lessons yet"); return
    by_type = collections.Counter(e["type"] for e in evs)
    print(f"# describe-changes lessons digest — {len(evs)} events, {len({e.get('repo') for e in evs})} repos, skill versions {sorted({e.get('skill_version') for e in evs})}\n")
    print("## Event mix"); [print(f"- {k}: {v}") for k, v in by_type.most_common()]
    def sev_tag(e): return (e.get("finding") or {}).get("severity", "-"), tuple((e.get("finding") or {}).get("tags", []))
    print("\n## Severity calibration (what the human disagreed with)")
    for typ, label in (("more", "under-rated (human: MORE important)"), ("less", "over-rated (human: LESS important)"), ("noise", "flagged as NOISE — credibility cost")):
        rows = [e for e in evs if e["type"] == typ]
        if not rows: continue
        c = collections.Counter(f"{sev_tag(e)[0]} / {','.join(sev_tag(e)[1]) or 'untagged'}" for e in rows)
        print(f"- {label}: {len(rows)}"); [print(f"    - {k}: {v}") for k, v in c.most_common(8)]
    gut = [e for e in evs if e["type"] == "gut_flag"]
    if gut:
        print(f"\n## Gut-flags on unflagged files ({len(gut)}) — candidate blind spots")
        for k, v in collections.Counter(os.path.splitext(e.get('file') or '')[1] or e.get('file') for e in gut).most_common(10): print(f"- {k}: {v}")
    q = [e for e in evs if e["type"] == "question"]
    if q:
        print(f"\n## Questions asked ({len(q)}) — what the report failed to answer up front")
        for e in q[-30:]:
            src = "page" if e.get("source") == "comment" else "chat"
            where = e.get("section") or (e.get("finding") or {}).get("id") or "—"
            print(f"- ({src} · {where}) {e.get('text')}" + (f" — on “{e['selection']}”" if e.get("selection") else "") + (f"\n    → improvement: {e['improvement']}" if e.get("improvement") else ""))
        secs = collections.Counter(e.get("section") for e in q if e.get("source") == "comment")
        if secs: print("  sections that raise questions: " + ", ".join(f"{k}={v}" for k, v in secs.most_common()))
    oc = [e for e in evs if e["type"] == "outcome"]
    if oc:
        print(f"\n## Outcomes ({len(oc)})")
        for e in oc[-25:]: print(f"- {e.get('kind')}: {e.get('text')} ({(e.get('finding') or {}).get('id')})")
    notes = [e for e in evs if e["type"] == "note" and e.get("text")]
    if notes:
        print(f"\n## Free-text notes ({len(notes)})")
        for e in notes[-25:]: print(f"- [{(e.get('finding') or {}).get('id', '—')}] {e.get('text')}")
    print("\nNext: turn the recurring patterns above into edits to reference/analysis-guide.md (severity rules, tags, noise rules) and bump VERSION.")

def cmd_export(a): print(json.dumps(read_all(a.since), indent=2))

def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("ingest"); p.add_argument("src"); p.add_argument("--dir", required=True); p.set_defaults(fn=cmd_ingest)
    p = sp.add_parser("question"); p.add_argument("text"); p.add_argument("--dir", required=True); p.add_argument("--finding"); p.add_argument("--answered-by-reading"); p.set_defaults(fn=cmd_question)
    p = sp.add_parser("outcome"); p.add_argument("--dir", required=True); p.add_argument("--kind", required=True, choices=["missed", "false_positive", "confirmed", "severity_changed"]); p.add_argument("--finding", default="new"); p.add_argument("--text", required=True); p.add_argument("--file"); p.set_defaults(fn=cmd_outcome)
    p = sp.add_parser("comments"); p.add_argument("--dir", required=True); p.add_argument("--open", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_comments)
    p = sp.add_parser("notes"); p.add_argument("--dir", required=True); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_notes)
    p = sp.add_parser("answer"); p.add_argument("--dir", required=True); p.add_argument("--id", required=True); p.add_argument("--text", help="answer text (markdown-lite: paragraphs, `code`); omit to read stdin"); p.add_argument("--improvement", help="one line: what the report should have said up front"); p.set_defaults(fn=cmd_answer)
    p = sp.add_parser("push"); p.add_argument("--since"); p.set_defaults(fn=cmd_push)
    p = sp.add_parser("digest"); p.add_argument("--since"); p.add_argument("--repo"); p.set_defaults(fn=cmd_digest)
    p = sp.add_parser("export"); p.add_argument("--since"); p.set_defaults(fn=cmd_export)
    a = ap.parse_args(); a.fn(a)

if __name__ == "__main__":
    main()
