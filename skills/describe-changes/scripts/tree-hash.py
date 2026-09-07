#!/usr/bin/env python3
"""tree-hash.py — deterministic content hash of a vendored skill directory.

    python3 tree-hash.py <dir>        → prints a sha256 hex digest

Exists so a consumer can answer "does the copy on disk still match the commit its pin names?".
The commit sha in `.describe-changes-version` cannot answer that: it records where the copy CAME
FROM, and hand-editing the vendored copy is a sanctioned workflow, so tree and pin drift apart by
design between a backward sync and the re-vendor that follows it.

Digest covers, for every file in POSIX-sorted path order: the relative path, whether the file is
executable, and the sha256 of its bytes. `__pycache__` and `*.pyc` are excluded — they are build
residue that appears from merely running the skill and would make every hash unstable.
"""
import hashlib, os, sys

def tree_hash(root):
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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: tree-hash.py <dir>", file=sys.stderr); sys.exit(2)
    if not os.path.isdir(sys.argv[1]):
        print(f"not a directory: {sys.argv[1]}", file=sys.stderr); sys.exit(2)
    print(tree_hash(sys.argv[1]))
