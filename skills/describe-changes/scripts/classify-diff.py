#!/usr/bin/env python3
"""classify-diff.py — deterministic noise pass for describe-changes (stdlib only).

Reads a unified diff (git diff -M -C) and emits:
  diff-model.json   per-file / per-hunk classification, folds, symbol moves, stats
  substantive.diff  a unified diff containing ONLY hunks a human may need to read

Hunk categories (exactly one per hunk):
  substantive      real behaviour change — goes to the LLM and the human
  whitespace       identical after whitespace normalisation (not in whitespace-sensitive langs)
  format           identical after whitespace + trailing comma/semicolon + quote normalisation
  import-rewrite   only import/require specifiers changed (typically follow a rename/move)
  comment-only     every changed line is a comment
File-level noise kinds (whole file folded): lockfile, generated, snapshot, vendored, binary, rename (pure).

The LLM never re-derives any of this — it reads diff-model.json + substantive.diff.
"""
import argparse, json, os, re, sys
from collections import defaultdict

WS_SENSITIVE = {".py", ".pyi", ".hs", ".lhs", ".yml", ".yaml", ".nim", ".coffee", ".pug", ".jade",
                ".slim", ".haml", ".sass", ".styl", ".md", ".mdx", ".rst", ".f90", ".cbl"}
WS_SENSITIVE_NAMES = {"Makefile", "makefile", "GNUmakefile"}
LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "Cargo.lock",
             "poetry.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock", "go.sum", "flake.lock",
             "mix.lock", "pubspec.lock", "packages.lock.json", "uv.lock", "pdm.lock"}
GENERATED_RE = re.compile(r"(^|/)(dist|build|out|coverage|\.next|node_modules|vendor|__generated__|generated|"
                          r"\.gen|target)/|\.min\.(js|css)$|\.(map|pb\.go|pb2\.py|g\.cs|d\.ts)$|(^|/)_generated[./]", re.I)
SNAPSHOT_RE = re.compile(r"(^|/)__snapshots__/|\.snap$|\.snapshot$")
GENERATED_MARKERS = ("@generated", "DO NOT EDIT", "do not edit", "Code generated", "auto-generated", "AUTO-GENERATED")

IMPORT_RE = re.compile(r"""^\s*(
    import\s.*|                                  # js/ts/py/go/java/kotlin/swift/rust-ish
    from\s+\S+\s+import\s.*|                      # python
    export\s+(\*|\{[^}]*\})\s+from\s.*|           # js re-export
    (const|let|var)\s+.*=\s*require\(.*|          # cjs
    require\s*\(.*|                               # bare require / ruby
    use\s+[\w:]+.*|                               # rust/php
    using\s+[\w.]+\s*;|                           # c#
    #include\s.*                                  # c/c++
)\s*$""", re.X)
COMMENT_RE = re.compile(r"^\s*(//|#|/\*|\*|\*/|--|<!--|;;|%|'''|\"\"\"|///|\"\"\"\s*$)")
SYMBOL_RE = re.compile(r"""^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:static\s+)?
    (?:function\*?|def|fn|func|class|interface|type|enum|struct|trait|impl|module|object|
       (?:const|let|var|val)|(?:public|private|protected|internal)\s+(?:static\s+)?(?:[\w<>\[\],.?]+\s+)?)
    \s+([A-Za-z_$][\w$]*)""", re.X)
SPEC_RE = re.compile(r"""(['"])([^'"]+)\1""")

def ext_of(path):
    base = os.path.basename(path)
    if base in WS_SENSITIVE_NAMES: return "Makefile"
    return os.path.splitext(base)[1].lower()

def language(path):
    e = ext_of(path)
    return {".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "jsx", ".mjs": "javascript",
            ".cjs": "javascript", ".py": "python", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
            ".swift": "swift", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp",
            ".hs": "haskell", ".ex": "elixir", ".exs": "elixir", ".scala": "scala", ".clj": "clojure",
            ".css": "css", ".scss": "scss", ".html": "html", ".vue": "vue", ".svelte": "svelte", ".sql": "sql",
            ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".yml": "yaml", ".yaml": "yaml", ".json": "json",
            ".md": "markdown", ".mdx": "markdown", ".toml": "toml", "Makefile": "make"}.get(e, e.lstrip(".") or "text")

# ---------------------------------------------------------------- parsing
class Hunk:
    def __init__(s, header, old_start, old_len, new_start, new_len, context):
        s.header, s.old_start, s.old_len, s.new_start, s.new_len, s.context = header, old_start, old_len, new_start, new_len, context
        s.lines = []  # raw lines incl. leading ' ', '-', '+'
    @property
    def removed(s): return [l[1:] for l in s.lines if l.startswith("-")]
    @property
    def added(s): return [l[1:] for l in s.lines if l.startswith("+")]

class FileDiff:
    def __init__(s):
        s.old_path = s.new_path = None; s.status = "modified"; s.similarity = None
        s.binary = False; s.hunks = []; s.header_lines = []
    @property
    def path(s): return s.new_path if s.new_path and s.new_path != "/dev/null" else s.old_path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")

def strip_ab(p):
    if p.startswith("a/") or p.startswith("b/"): return p[2:]
    return p

def parse(text):
    files, cur, hunk = [], None, None
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            cur = FileDiff(); files.append(cur); hunk = None
            m = re.match(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', raw)
            if m: cur.old_path, cur.new_path = m.group(1), m.group(2)
            cur.header_lines.append(raw); continue
        if cur is None: continue
        if hunk is None or raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            if m:
                hunk = Hunk(raw, int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), m.group(5).strip())
                cur.hunks.append(hunk); continue
            cur.header_lines.append(raw)
            if raw.startswith("similarity index"): cur.similarity = int(raw.split()[-1].rstrip("%"))
            elif raw.startswith("rename from"): cur.old_path = raw[len("rename from "):]; cur.status = "renamed"
            elif raw.startswith("rename to"): cur.new_path = raw[len("rename to "):]
            elif raw.startswith("copy from"): cur.old_path = raw[len("copy from "):]; cur.status = "copied"
            elif raw.startswith("copy to"): cur.new_path = raw[len("copy to "):]
            elif raw.startswith("new file mode"): cur.status = "added"
            elif raw.startswith("deleted file mode"): cur.status = "deleted"
            elif raw.startswith("Binary files") or raw.startswith("GIT binary patch"): cur.binary = True
            elif raw.startswith("--- "):
                p = raw[4:].split("\t")[0]; cur.old_path = None if p == "/dev/null" else strip_ab(p)
            elif raw.startswith("+++ "):
                p = raw[4:].split("\t")[0]; cur.new_path = None if p == "/dev/null" else strip_ab(p)
            continue
        if raw.startswith("\\ No newline"): continue
        hunk.lines.append(raw if raw else " ")
    for f in files:
        if f.status == "modified" and f.old_path is None: f.status = "added"
        if f.status == "modified" and f.new_path is None: f.status = "deleted"
        if f.old_path is None: f.old_path = "/dev/null"
        if f.new_path is None: f.new_path = "/dev/null"
    return files

# ---------------------------------------------------------------- classification
def norm_ws(s): return re.sub(r"\s+", "", s)
def norm_fmt(s):
    s = norm_ws(s)
    s = re.sub(r"[;,]+(?=[)\]}]|$)", "", s)          # trailing commas / semicolons
    s = s.replace(";", ",")                            # separator style (type/object literals, statements)
    s = s.replace("'", '"').replace("`", '"')         # quote style
    return s

def blocks_of(h):
    """Split a hunk into change blocks: maximal runs of -/+ lines (a replace = one block)."""
    blocks, cur = [], None
    for l in h.lines:
        if l.startswith("-") or l.startswith("+"):
            if cur is None: cur = {"removed": [], "added": []}
            cur["removed" if l.startswith("-") else "added"].append(l[1:])
        elif cur is not None:
            blocks.append(cur); cur = None
    if cur is not None: blocks.append(cur)
    return blocks

def classify_block(rem, add, ws_sensitive):
    changed = rem + add
    if not changed: return "substantive"
    if all(not l.strip() for l in changed):
        return "substantive" if ws_sensitive else "whitespace"
    if norm_ws("".join(rem)) == norm_ws("".join(add)):
        return "substantive" if ws_sensitive else "whitespace"
    if rem and add and norm_fmt("".join(rem)) == norm_fmt("".join(add)):
        return "format"
    nonblank = [l for l in changed if l.strip()]
    # Mixed noise is still noise: every changed line must be an import OR a comment.
    if nonblank and all(IMPORT_RE.match(l) or COMMENT_RE.match(l) for l in nonblank):
        return "import-rewrite" if any(IMPORT_RE.match(l) for l in nonblank) else "comment-only"
    return "substantive"

NOISE_ORDER = ["import-rewrite", "format", "whitespace", "comment-only"]

def classify_hunk(h, ws_sensitive):
    """Hunk category = substantive if ANY block is; else the most significant noise kind present.
    Also records h.blocks (per-block categories) so import rewrites inside a substantive hunk can
    still be attached to the rename they follow."""
    h.blocks = [dict(b, category=classify_block(b["removed"], b["added"], ws_sensitive)) for b in blocks_of(h)]
    cats = {b["category"] for b in h.blocks}
    if not cats or "substantive" in cats: return "substantive"
    return next(c for c in NOISE_ORDER if c in cats)

def file_noise_kind(f, added_text):
    base = os.path.basename(f.path)
    if f.binary: return "binary"
    if base in LOCKFILES: return "lockfile"
    if SNAPSHOT_RE.search(f.path): return "snapshot"
    if GENERATED_RE.search(f.path): return "generated"
    head = "\n".join(added_text[:8])
    if f.status == "added" and any(m in head for m in GENERATED_MARKERS): return "generated"
    return None

TOPLEVEL_ONLY = ("const", "let", "var", "val")

def symbols_in(lines):
    """Declared symbol names. Variable declarations count only at top level (column 0) so local
    `const env = …` in five test files does not masquerade as a moved symbol."""
    out = []
    for l in lines:
        m = SYMBOL_RE.match(l)
        if not m: continue
        if l[:1].isspace() and re.match(r"\s*(?:export\s+)?(?:%s)\b" % "|".join(TOPLEVEL_ONLY), l): continue
        out.append(m.group(1))
    return out

def import_specs(lines):
    specs = []
    for l in lines:
        for m in SPEC_RE.finditer(l): specs.append(m.group(2))
    return specs

def content_lines(lines):
    return {l.strip() for l in lines if len(l.strip()) > 12 and not COMMENT_RE.match(l)}

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True); ap.add_argument("--numstat"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    text = open(a.diff, encoding="utf-8", errors="replace").read()
    files = parse(text)
    os.makedirs(a.out, exist_ok=True)

    model_files, folds = [], defaultdict(list)
    lines_changed = lines_sub = 0
    deleted_content, added_files = {}, []
    sym_removed, sym_added = defaultdict(set), defaultdict(set)
    renames = {}  # new_path -> old_path
    rename_targets = {}  # old_path -> {path, overlap} for low-similarity renames (split sources)

    for fi, f in enumerate(files, 1):
        all_added = [l for h in f.hunks for l in h.added]
        ws = ext_of(f.path) in WS_SENSITIVE or ext_of(f.path) == "Makefile"
        noise = file_noise_kind(f, all_added)
        hunks = []
        for hi, h in enumerate(f.hunks, 1):
            cat = classify_hunk(h, ws) if noise is None else noise
            hunks.append({"id": f"F{fi}H{hi}", "header": h.header, "symbol": h.context or None,
                          "old_start": h.old_start, "old_lines": h.old_len, "new_start": h.new_start,
                          "new_lines": h.new_len, "category": cat, "added": len(h.added), "removed": len(h.removed),
                          "blocks": [{"category": b["category"], "removed": len(b["removed"]), "added": len(b["added"])}
                                     for b in getattr(h, "blocks", [])]})
            h.category = cat; h.id = f"F{fi}H{hi}"
            if cat in ("whitespace", "format", "comment-only"):
                folds[cat].append({"file": f.path, "hunk_ids": [h.id], "detail": h.context or h.header})
            sym_removed[f.path].update(symbols_in(h.removed)); sym_added[f.path].update(symbols_in(h.added))
        if f.status == "renamed" and not f.hunks: cat_file = "rename"
        elif f.status == "renamed": cat_file = "rename+modified"
        else: cat_file = f.status
        if f.status in ("renamed", "copied"): renames[f.new_path] = f.old_path
        if f.status == "deleted": deleted_content[f.path] = content_lines(l for h in f.hunks for l in h.removed)
        elif f.status == "renamed" and f.hunks and (f.similarity or 100) < 80:
            deleted_content[f.old_path] = content_lines(l for h in f.hunks for l in h.removed)
            rename_targets[f.old_path] = {"path": f.new_path, "overlap": (f.similarity or 0) / 100}
        if f.status == "added" and noise is None: added_files.append(f)
        entry = {"id": f"F{fi}", "path": f.path, "old_path": f.old_path if f.old_path != f.path else None,
                 "status": cat_file, "similarity": f.similarity, "language": language(f.path),
                 "whitespace_sensitive": ws, "noise_kind": noise, "hunks": hunks,
                 "substantive_hunks": sum(1 for h in hunks if h["category"] == "substantive"),
                 "symbols_added": sorted(sym_added[f.path]), "symbols_removed": sorted(sym_removed[f.path])}
        model_files.append(entry)
        if noise: folds[noise].append({"file": f.path, "hunk_ids": [h["id"] for h in hunks], "detail": f"{f.status}, {len(hunks)} hunks"})
        if cat_file == "rename": folds["rename"].append({"file": f.path, "old_path": f.old_path, "hunk_ids": [], "detail": f"{f.old_path} → {f.path} (pure rename, {f.similarity}%)", "followers": []})

    # Import-rewrite hunks: attach as followers of the rename/move they reference, else stand-alone fold.
    rename_bases = {os.path.splitext(os.path.basename(n))[0]: n for n in renames}
    by_path = {e["path"]: e for e in model_files}
    for f in files:
        for h in f.hunks:
            for b in getattr(h, "blocks", []):
                if b["category"] != "import-rewrite": continue
                specs = import_specs(b["added"]) + import_specs(b["removed"])
                targets = [rename_bases[k] for k in rename_bases if any(k in sp for sp in specs)]
                partial = h.category == "substantive"
                added_specs = list(dict.fromkeys(import_specs(b["added"]))); removed_specs = list(dict.fromkeys(import_specs(b["removed"])))
                item = {"file": f.path, "hunk_ids": [h.id], "partial": partial, "added": added_specs, "removed": removed_specs,
                        "detail": (" / ".join(added_specs) or h.header) + (" (inside a substantive hunk)" if partial else "")}
                parents = [r for r in folds["rename"] if r["file"] in targets]
                for r in parents: r["followers"].append(item)
                if not parents and not partial: folds["import-rewrite"].append(item)

    # Move / split detection: added files whose content largely came from a deleted file.
    moves = []
    for af in added_files:
        mine = content_lines(l for h in af.hunks for l in h.added)
        if len(mine) < 3: continue
        best, best_frac = None, 0.0
        for dp, dl in deleted_content.items():
            if not dl: continue
            frac = len(mine & dl) / len(mine)
            if frac > best_frac: best, best_frac = dp, frac
        if best and best_frac >= 0.5:
            moves.append({"from": best, "to": af.path, "overlap": round(best_frac, 2)})
    split_groups = defaultdict(list)
    for m in moves: split_groups[m["from"]].append(m)
    for src, rt in rename_targets.items():
        if src in split_groups:  # the renamed remainder counts as one more split target
            split_groups[src].insert(0, {"from": src, "to": rt["path"], "overlap": rt["overlap"]})
    for src, ms in split_groups.items():
        kind = "split" if len(ms) > 1 else "move"
        folds[kind].append({"file": src, "hunk_ids": [], "detail": f"{src} → " + ", ".join(m['to'] for m in ms),
                            "targets": [{"path": m["to"], "overlap": m["overlap"]} for m in ms]})
        for m in ms:
            if m["to"] in by_path:
                by_path[m["to"]]["moved_from"] = src; by_path[m["to"]]["overlap"] = m["overlap"]

    # Blocks whose lines merely travelled between a split/move source and its targets are 'moved'.
    target_content = defaultdict(set)   # source path -> union of content lines of its targets
    for m in moves:
        target_content[m["from"]] |= content_lines(l for h in next(x for x in files if x.path == m["to"]).hunks for l in h.added)
    for src, rt in rename_targets.items():
        tf = next((x for x in files if x.path == rt["path"]), None)
        if tf: target_content[src] |= content_lines(l for h in tf.hunks for l in h.added) | content_lines(
            l[1:] for h in tf.hunks for l in h.lines if l.startswith(" "))
    source_of = {m["to"]: m["from"] for m in moves}
    for f in files:
        src_for_removed = f.path if f.path in target_content else (f.old_path if f.old_path in target_content else None)
        src_for_added = source_of.get(f.path)
        for h in f.hunks:
            for b in getattr(h, "blocks", []):
                if b["category"] != "substantive": continue
                rem = {l.strip() for l in b["removed"] if len(l.strip()) > 12}; add = {l.strip() for l in b["added"] if len(l.strip()) > 12}
                if src_for_removed and rem and not add and rem <= target_content[src_for_removed]: b["category"] = "moved"
                elif src_for_added and add and not rem and add <= deleted_content.get(src_for_added, set()): b["category"] = "moved"
            if getattr(h, "blocks", None) and all(b["category"] == "moved" for b in h.blocks): h.category = "moved"
        # refresh the model entry for this file
        e = by_path.get(f.path)
        if e:
            for mh, h in zip(e["hunks"], f.hunks):
                mh["category"] = h.category
                mh["blocks"] = [{"category": b["category"], "removed": len(b["removed"]), "added": len(b["added"])} for b in getattr(h, "blocks", [])]
            e["substantive_hunks"] = sum(1 for h in e["hunks"] if h["category"] == "substantive")
    for e in model_files:
        for h in e["hunks"]:
            if e["noise_kind"]:
                lines_changed += h["added"] + h["removed"]; continue
            for b in h["blocks"]:
                n = b["added"] + b["removed"]; lines_changed += n
                if b["category"] == "substantive": lines_sub += n

    # Symbol moves: same symbol removed in one file and added in another.
    # A true move: the symbol left `src` (removed, not re-added there) and landed in `dst` (added, not removed there).
    symbol_moves = []
    for src, removed in sym_removed.items():
        left = removed - sym_added[src]
        for dst, added in sym_added.items():
            if src == dst: continue
            for name in sorted(left & (added - sym_removed[dst])):
                symbol_moves.append({"name": name, "from": src, "to": dst})

    if folds.get("import-rewrite"):
        by_mod = defaultdict(lambda: {"files": [], "hunk_ids": []})
        for it in folds["import-rewrite"]:
            for spec in it.get("added") or ["(imports removed)"]:
                g = by_mod[spec]
                if it["file"] not in g["files"]: g["files"].append(it["file"])
                g["hunk_ids"] += it["hunk_ids"]
        folds["import-rewrite"] = [{"file": mod, "module": mod, "files": sorted(v["files"]), "hunk_ids": v["hunk_ids"],
                                    "detail": (f"unused imports dropped in {len(v['files'])} file{'s' if len(v['files']) != 1 else ''}: " if mod == "(imports removed)" else f"{mod} ← now imported in {len(v['files'])} file{'s' if len(v['files']) != 1 else ''}: ") + ", ".join(sorted(v["files"]))}
                                   for mod, v in sorted(by_mod.items(), key=lambda kv: -len(kv[1]["files"]))]
    fold_titles = {"rename": "Renamed files (imports updated to match)", "move": "Moved files", "split": "Files split",
                   "import-rewrite": "Import-only changes (module ← files that now import it)", "whitespace": "Whitespace-only hunks",
                   "format": "Formatting-only hunks", "comment-only": "Comment-only hunks",
                   "lockfile": "Lockfiles", "generated": "Generated / build output", "snapshot": "Test snapshots",
                   "vendored": "Vendored code", "binary": "Binary files"}
    fold_list = [{"kind": k, "title": fold_titles.get(k, k), "count": len(v), "items": v}
                 for k, v in folds.items() if v]
    fold_list.sort(key=lambda x: ["rename", "move", "split", "import-rewrite", "format", "whitespace", "comment-only",
                                  "lockfile", "generated", "snapshot", "vendored", "binary"].index(x["kind"])
                   if x["kind"] in fold_titles else 99)

    files_sub = [e for e in model_files if e["substantive_hunks"] > 0]
    model = {
        "stats": {"files": len(model_files), "files_substantive": len(files_sub), "lines_changed": lines_changed,
                  "lines_substantive": lines_sub,
                  "noise_pct": round(100 * (1 - lines_sub / lines_changed)) if lines_changed else 0,
                  "hunks_by_category": dict(sorted(defaultdict(int, {
                      c: sum(1 for e in model_files for h in e["hunks"] if h["category"] == c)
                      for c in {h["category"] for e in model_files for h in e["hunks"]}}).items()))},
        "files": model_files, "folds": fold_list, "symbol_moves": symbol_moves,
        "notes": [f"{e['path']}: whitespace-sensitive language — whitespace hunks kept as substantive"
                  for e in model_files if e["whitespace_sensitive"] and any(
                      h["category"] == "substantive" and not h["symbol"] for h in e["hunks"])][:20],
    }
    json.dump(model, open(os.path.join(a.out, "diff-model.json"), "w"), indent=2)

    # substantive.diff — only substantive hunks, with the file headers git produced.
    out = []
    for f in files:
        keep = [h for h in f.hunks if getattr(h, "category", None) == "substantive"]
        if not keep: continue
        out.extend(f.header_lines)
        for h in keep:
            mix = ",".join(b["category"] for b in getattr(h, "blocks", []))
            out.append(f"{h.header}  [{h.id}]" + (f"  blocks: {mix}" if mix and mix != "substantive" else ""))
            out.extend(h.lines)
    open(os.path.join(a.out, "substantive.diff"), "w").write("\n".join(out) + ("\n" if out else ""))

    s = model["stats"]
    print(f"classified {s['files']} files / {lines_changed} changed lines → {s['lines_substantive']} substantive "
          f"({s['noise_pct']}% folded as noise); {len(fold_list)} fold groups; {len(symbol_moves)} symbol moves")

if __name__ == "__main__":
    main()
