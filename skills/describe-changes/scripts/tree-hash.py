#!/usr/bin/env python3
"""tree-hash.py — deterministic content hash of a vendored skill directory.

    python3 tree-hash.py <dir>        → prints a sha256 hex digest

A thin CLI over `report_keys.tree_hash`, which is where the implementation lives. Consumers use
this to answer "does the copy on disk still match the commit its pin names?" — the commit sha in
`.describe-changes-version` cannot, since it records where the copy CAME FROM and editing a
vendored copy in place is a supported workflow.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_keys import tree_hash

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: tree-hash.py <dir>", file=sys.stderr); sys.exit(2)
    if not os.path.isdir(sys.argv[1]):
        print(f"not a directory: {sys.argv[1]}", file=sys.stderr); sys.exit(2)
    print(tree_hash(sys.argv[1]))
