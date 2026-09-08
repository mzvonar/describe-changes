#!/usr/bin/env python3
"""Stable identities for the things a reader tracks across re-renders.

Ids in a report are positional — `V7`, `M2` — so re-authoring hands them to different subjects, and
anything replayed by id (a tick, a vote, "what changed since I last read this") ends up attached to
work nobody did. Both keys below hash the CONTENT a reader actually engaged with, so an untouched
item keeps its identity for as long as it says the same thing, and stops the moment it does not.
"""
import hashlib, json, re

def _h(payload):
    return hashlib.sha1(payload.encode()).hexdigest()[:12]

def check_key(c):
    """What the reader was asked to DO. `covered_by` is excluded: moving a spec file does not
    change the steps, and a tick should survive it."""
    return _h(json.dumps({k: c.get(k) for k in
                          ("feature", "surface", "where", "setup", "steps", "expect", "request")},
                         sort_keys=True, ensure_ascii=False))

def norm_claim(s):
    """A title, reduced to its claim: case, punctuation and code formatting dropped. Re-wording
    `saveUser` to ``saveUser()`` is not a new finding."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()

def finding_key(f):
    """A finding is the same finding while it points at the same place and makes the same claim."""
    return _h(f"{f.get('file','')}|{norm_claim(f.get('title'))}")

def finding_site_key(f):
    """Weaker match: same file, same severity. Lets a re-WORDED finding read as changed rather than
    as one disappearing and another appearing — the reviewer needs to know which of the two it is."""
    return _h(f"{f.get('file','')}|{f.get('severity','')}")


def tree_hash(root):
    """Deterministic content hash of a directory: POSIX-sorted paths + exec bit + sha256 per file.

    Lives here, not in a script loaded by path, because it is the ONE function the vendored-fold
    proof cannot afford to have swapped: a `tree_hash` that returns whatever the pin claims makes
    every other check agree. `__pycache__` and `*.pyc` are excluded — they appear from merely
    running the skill and would make the hash unstable."""
    import hashlib, os
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".pyc"): continue
            rels.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    h = hashlib.sha256()
    for rel in sorted(rels):
        p = os.path.join(root, rel)
        h.update(rel.encode() + b"\0")
        h.update((b"x" if os.access(p, os.X_OK) else b"-") + b"\0")
        with open(p, "rb") as f:
            h.update(hashlib.sha256(f.read()).hexdigest().encode() + b"\0")
    return h.hexdigest()


def _ts_key(ts):
    """Sortable instant from an ISO timestamp, whichever of the two spellings wrote it.

    The page and the CLI stamp turns DIFFERENTLY — the browser writes `…T12:00:00.200Z` and
    `feedback.py` writes `…T12:00:00+00:00` — so ordering them as raw strings compares `.` against
    `+`, and `+` sorts first. A reply and an answer landing in the same second therefore came out
    answer-then-reply whatever the real order, and the thread read OPEN after it had been answered.
    Measured, not reasoned: `'+' < '.'` is True.

    Falls back to the raw string when a stamp will not parse, so an unexpected format degrades to
    the old behaviour instead of raising during a render.
    """
    import datetime
    try:
        return (0, datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return (1, str(ts))


def thread_turns(thread_id, feedback_events, answer_events):
    """The turns of one conversation thread, after the opening comment, oldest first.

    A thread is no longer "comment, then Claude answers, the end": the reader can reply to an
    answer, so it is an alternating conversation and every consumer has to agree on what it says.
    This lives here, and not in the renderer plus a copy in `feedback.py`, because those two answer
    the SAME question — what has been said on this thread — and two local walks of one question is
    how they drift apart. The page and the CLI must show the reader the same conversation.

    Supersede rule: consecutive Claude turns COLLAPSE to the last one. An `answer` written when the
    previous turn was also Claude's is a correction of that answer, not a second thing said — which
    is what re-running `feedback.py answer` on a thread has always meant. An answer written after a
    user reply is a genuine new turn and is kept. Without this, every re-answered thread would show
    the superseded text next to the text that replaced it.

    Returns `[{"role": "user"|"claude", "text": str, "ts": str, "rid": str}]`; `rid` is set on
    user turns only and is what the page matches its own replayed reply against.
    """
    turns = []
    for e in feedback_events:
        if e.get("type") == "reply" and e.get("thread") == thread_id and (e.get("text") or "").strip():
            # `rid` rides along because the RENDERED reply has to carry it: the page replays a
            # reply it already sent from localStorage, and its only way to know the renderer wrote
            # that one already is to find the same id in the DOM. Without it the authoring device
            # appends a second copy on every reload and re-marks the thread open.
            turns.append({"role": "user", "text": e["text"], "ts": e.get("ts") or "",
                          "rid": e.get("rid") or e.get("ts") or ""})
    for a in answer_events:
        if a.get("id") == thread_id and (a.get("text") or "").strip():
            turns.append({"role": "claude", "text": a["text"], "ts": a.get("ts") or "", "rid": ""})
    turns.sort(key=lambda t: _ts_key(t["ts"]))
    out = []
    for t in turns:
        if out and out[-1]["role"] == "claude" and t["role"] == "claude":
            out[-1] = t                      # a correction of the answer above it, not a new turn
        else:
            out.append(t)
    return out


def thread_is_open(turns):
    """Open = somebody is waiting on Claude: the thread has no turns yet, or the last one is the
    reader's. An answered thread the reader has replied to is OPEN again, which is the whole point
    of allowing replies — otherwise a reply lands in a thread marked done and nothing surfaces it."""
    return not turns or turns[-1]["role"] == "user"


# --- Thread identity -----------------------------------------------------------------------------
# A note is addressed by an id that BOTH the renderer and the CLI must derive the same way, or an
# answer is filed under one and looked up under the other. They used to derive it separately and
# agreed in two cases out of three: a note carrying a `finding_key` whose finding had since been
# resolved or RE-WORDED went to the renderer's orphan branch, which minted from the positional id
# while the CLI still minted from the key. That state is not exotic — it is what FIXING a finding
# creates, so it was reachable by the ordinary act of answering a review.
#
# These four are the single derivation. Nothing else may build one of these ids by hand; a guard in
# tests/run.sh asserts neither consumer constructs the `note-` / `checknote-` prefixes inline.

def note_group_key(e):
    """How note events collapse into ONE thread. An edited note is one thread, not two."""
    return e.get("finding_key") or ("id:" + (e.get("finding") or "unknown"))


def note_thread_id(e):
    """The id a note thread is addressed by. Content key when there is one, positional id otherwise.

    Deliberately independent of whether the finding is still in the report: an orphan is a thread
    with a different LABEL, never a different identity, or the reader's reply lands somewhere the
    answer cannot follow.
    """
    return "note-" + (e.get("finding_key") or e.get("finding") or "unknown")


def check_group_key(e):
    """`note_group_key` for a note left on a verification-check card."""
    return e.get("check_key") or ("id:" + (e.get("check") or "unknown"))


def check_thread_id(e):
    """`note_thread_id` for a note left on a verification-check card."""
    return "checknote-" + (e.get("check_key") or e.get("check") or "unknown")
