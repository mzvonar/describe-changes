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
