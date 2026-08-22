#!/usr/bin/env python3
"""slice-diff.py — cut substantive.diff into per-phase slices for fan-out analysis.

Usage: slice-diff.py <substantive.diff> <out-dir> <name>=<path-regex> [<name>=<regex> ...] [--rest <name>]
Each file section (starting at `diff --git`) goes to the FIRST slice whose regex matches its path;
`--rest` collects the unmatched ones. Prints one line per slice: name, files, lines, path.
Use when substantive.diff is too big to read with care (> ~2500 lines): one analyst per slice.
"""
import re, sys, os

def main():
    args = sys.argv[1:]
    if len(args) < 3: print(__doc__); sys.exit(2)
    src, out = args[0], args[1]; rest = None; specs = []
    i = 2
    while i < len(args):
        if args[i] == "--rest": rest = args[i + 1]; i += 2; continue
        name, _, rx = args[i].partition("="); specs.append((name, re.compile(rx))); i += 1
    os.makedirs(out, exist_ok=True)
    buckets = {n: [] for n, _ in specs}
    if rest: buckets[rest] = []
    cur = None
    for line in open(src, encoding="utf-8", errors="replace"):
        if line.startswith("diff --git"):
            path = line.split(" b/")[-1].strip()
            cur = next((n for n, rx in specs if rx.search(path)), rest)
        if cur is not None: buckets[cur].append(line)
    for name, lines in buckets.items():
        p = os.path.join(out, f"slice-{name}.diff")
        open(p, "w").write("".join(lines))
        files = sum(1 for l in lines if l.startswith("diff --git"))
        print(f"{name}: {files} files, {len(lines)} lines → {p}")

if __name__ == "__main__":
    main()
