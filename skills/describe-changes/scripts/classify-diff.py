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
# A named specifier alone on a line inside a multi-line import block: `  Foo,` / `  type Bar,` /
# `  Foo as Baz,`. Counted as import noise ONLY when the hunk is demonstrably inside an import
# statement (see IMPORT_CONTEXT_RE) — on its own such a line is indistinguishable from an object
# literal entry, an enum member or an array element, and folding those would hide real changes.
# Without this, re-pointing an import at a barrel reads as substantive: the DELETED deep-path
# `import { X } from "…/x"` lines match IMPORT_RE, but the ADDED `X,` inside the existing braces
# does not, so the hunk is half import-rewrite and half "substantive" and never folds.
SPECIFIER_RE = re.compile(r"^\s*(type\s+)?[A-Za-z_$][\w$]*(\s+as\s+[A-Za-z_$][\w$]*)?\s*,?\s*$")
# Deliberately `import` ONLY, not `export {`. Both are brace-and-specifier blocks, but adding a
# specifier to an EXPORT widens a module's public API — in this codebase a barrel is rule-bound
# (`service/index.ts` may export only `AsUser` functions), so a new export line is exactly the kind
# of thing a reviewer must see. An import moving to a different path changes nothing it can observe.
IMPORT_CONTEXT_RE = re.compile(r"^\s*import\b")
SYMBOL_RE = re.compile(r"""^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:static\s+)?
    (?:function\*?|def|fn|func|class|interface|type|enum|struct|trait|impl|module|object|
       (?:const|let|var|val)|(?:public|private|protected|internal)\s+(?:static\s+)?(?:[\w<>\[\],.?]+\s+)?)
    \s+([A-Za-z_$][\w$]*)""", re.X)
SPEC_RE = re.compile(r"""(['"])([^'"]+)\1""")
UNRESOLVED_MODULE = "(module not named in the hunk)"

# Working notes: the prose a change PRODUCES rather than the change itself — plans, handoffs, a
# lessons inbox, an append-only journal, a deferred-work backlog. Markdown only, and a decision
# record (ADR), a wiki page, a README or a changelog is deliberately NOT here: those are the "why"
# a reviewer most needs. Override with DESCRIBE_CHANGES_NOTES_RE when a repo names them differently.
NOTES_RE = re.compile(os.environ.get("DESCRIBE_CHANGES_NOTES_RE") or
                      r"(^|/)_bmad-output/|(^|/)plans?/|(^|/)(deferred-work|lessons-inbox|scratch)\.md$"
                      r"|(^|/)[^/]*handoff[^/]*\.md$|(^|/)wiki/log\.md$", re.I)
MD_EXT = (".md", ".mdx")
LINK_RE = re.compile(r"\]\(([^)\s]+)")
JSX_OPEN_RE = re.compile(r"<([A-Z][\w.]*)")
# A TYPE annotation, not an object-literal entry: the value side must be a TS primitive, a
# capitalised type, or a function type. `foo: bar,` in a literal does not qualify, and JSON keys
# are quoted so they never reach here.
PROP_DECL_RE = re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_$][\w$]*)\??\s*:\s*"
                          r"(?:boolean|string|number|bigint|symbol|\(|[A-Z][\w.<>\[\]|\s]*)")

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
    """Split a hunk into change blocks: maximal runs of -/+ lines (a replace = one block).

    `start`/`end` index back into `h.lines` so a block of bare specifiers can find the `from "…"`
    on the CONTEXT line that closes its import statement — see `enclosing_module`."""
    blocks, cur = [], None
    for i, l in enumerate(h.lines):
        if l.startswith("-") or l.startswith("+"):
            if cur is None: cur = {"removed": [], "added": [], "start": i}
            cur["removed" if l.startswith("-") else "added"].append(l[1:])
        elif cur is not None:
            cur["end"] = i; blocks.append(cur); cur = None
    if cur is not None: cur["end"] = len(h.lines); blocks.append(cur)
    return blocks

def classify_block(rem, add, ws_sensitive, in_import=False):
    changed = rem + add
    if not changed: return "substantive"
    if all(not l.strip() for l in changed):
        return "substantive" if ws_sensitive else "whitespace"
    if norm_ws("".join(rem)) == norm_ws("".join(add)):
        return "substantive" if ws_sensitive else "whitespace"
    if rem and add and norm_fmt("".join(rem)) == norm_fmt("".join(add)):
        return "format"
    nonblank = [l for l in changed if l.strip()]
    # Mixed noise is still noise: every changed line must be an import OR a comment. Inside an
    # import statement, a bare specifier counts too — that is what makes a barrel re-point fold.
    def import_ish(l):
        return bool(IMPORT_RE.match(l) or (in_import and SPECIFIER_RE.match(l)))

    if nonblank and all(import_ish(l) or COMMENT_RE.match(l) for l in nonblank):
        return "import-rewrite" if any(import_ish(l) for l in nonblank) else "comment-only"
    return "substantive"

def hunk_in_import(h):
    """Is this hunk inside an import statement? Used to let bare specifiers count as import noise.

    Two independent signals, either sufficient: git's own context suffix on the `@@` header (it
    names the enclosing construct — `@@ … @@ import {`), and an import-shaped line among the hunk's
    OWN lines (context, added or removed). The header alone is a heuristic git can get wrong, and a
    hunk that opens mid-block has no `import` line of its own, so neither is reliable by itself.
    """
    if IMPORT_CONTEXT_RE.search((getattr(h, "header", "") or "").split("@@")[-1]):
        return True
    return any(IMPORT_CONTEXT_RE.match(l[1:] if l[:1] in "+- " else l) for l in getattr(h, "lines", []))

NOISE_ORDER = ["import-rewrite", "format", "whitespace", "comment-only"]

def classify_hunk(h, ws_sensitive):
    """Hunk category = substantive if ANY block is; else the most significant noise kind present.
    Also records h.blocks (per-block categories) so import rewrites inside a substantive hunk can
    still be attached to the rename they follow."""
    in_import = hunk_in_import(h)
    h.blocks = [dict(b, category=classify_block(b["removed"], b["added"], ws_sensitive, in_import))
                for b in blocks_of(h)]
    cats = {b["category"] for b in h.blocks}
    if not cats or "substantive" in cats: return "substantive"
    return next(c for c in NOISE_ORDER if c in cats)

def file_noise_kind(f, added_text):
    base = os.path.basename(f.path)
    if f.binary: return "binary"
    if base in LOCKFILES: return "lockfile"
    if SNAPSHOT_RE.search(f.path): return "snapshot"
    if GENERATED_RE.search(f.path): return "generated"
    if ext_of(f.path) in MD_EXT and NOTES_RE.search(f.path): return "notes"
    head = "\n".join(added_text[:8])
    if f.status == "added" and any(m in head for m in GENERATED_MARKERS): return "generated"
    return None

def kebab(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name.split(".")[-1]).lower()

def registry_row(path, block, added_paths):
    """A one-line index/table row pointing at a file ADDED in this same change.

    `| [ADR-0051](0051-….md) | … |` restates a file the reviewer is already reading in full; it is
    bookkeeping the change owes its index, not a change. Folds ONLY when the link target is one of
    this diff's new files — a row pointing anywhere else is an edit to a live document."""
    if ext_of(path) not in MD_EXT or block["removed"] or len(block["added"]) != 1: return None
    line = block["added"][0].strip()
    if not (line.startswith("|") or line.startswith("- ") or line.startswith("* ")): return None
    here = os.path.dirname(path)
    for target in LINK_RE.findall(line):
        p = os.path.normpath(os.path.join(here, target.split("#")[0]))
        if p in added_paths: return p
    return None

def prop_uses_re(name):
    return re.compile(r"\b" + re.escape(name) + r"\b\s*(?:=\s*\{[^{}]*\}|=\s*\"[^\"]*\")?\s*,?")

def thread_block(block, name):
    """Is this block a pure pass-site for `name` — the prop added (or removed) and nothing else?

    Exactly one side may mention the prop, and after deleting its occurrences the two sides must be
    textually identical. `items={ACCOUNTANT_MORE_ITEMS}` → `items={moreItems}` therefore does NOT
    fold: the prop is absent from both sides, and were it present on both, the remainders differ."""
    rem = [l for l in block["removed"] if l.strip()]; add = [l for l in block["added"] if l.strip()]
    has_r, has_a = any(name in l for l in rem), any(name in l for l in add)
    if has_r == has_a: return None
    sub = prop_uses_re(name)
    norm = lambda ls: re.sub(r"[\s,]+", "", "".join(sub.sub("", l) for l in ls))
    if norm(rem) != norm(add): return None
    return "removed" if has_r else "added"

def target_component(hunk, block, lines, prev=None):
    """The component a pass-site hands the prop to: the tag on the changed line, else the nearest
    opening tag above it (a multi-line JSX element puts each prop on its own line).

    A long element can push its `<Tag` past the hunk's three context lines and into the PREVIOUS
    hunk — that is how `<AccountantTopSidebar` went missing while the prop line was right there. The
    scan continues into that hunk only when the two are contiguous, so a tag 200 lines up is never
    claimed as the target."""
    for l in lines:
        m = JSX_OPEN_RE.search(l)
        if m: return m.group(1)
    def scan(h, upto):
        for i in range(upto - 1, -1, -1):
            raw = h.lines[i]; m = JSX_OPEN_RE.search(raw[1:] if raw[:1] in "+- " else raw)
            if m: return m.group(1)
        return None
    found = scan(hunk, block.get("start", 0))
    if found or prev is None: return found
    if prev.new_start + prev.new_len >= hunk.new_start - 3:
        return scan(prev, len(prev.lines))
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

FROM_RE = re.compile(r"""\bfrom\s+(['"])([^'"]+)\1""")

def enclosing_module(h, block):
    """The module a block of BARE specifiers belongs to.

    `import_specs` reads quoted module paths off the changed lines. A block that only adds
    `  Foo,` inside an existing `import { … } from "@/x"` has none — the path sits on the context
    line that closes the statement — so such a block used to look like "no module", which the fold
    then read as "an import was removed". It is the opposite: an import was ADDED. Scan forward to
    the first `from "…"`, stopping if a new `import` statement starts first (then the block was not
    inside one after all)."""
    lines = getattr(h, "lines", [])
    for i in range(block.get("end", 0), len(lines)):
        raw = lines[i]; l = raw[1:] if raw[:1] in "+- " else raw
        if IMPORT_CONTEXT_RE.match(l): break
        m = FROM_RE.search(l)
        if m: return m.group(2)
    return None

def block_modules(h, block, side):
    """Module paths the block imports FROM on `side` ("added"/"removed"), bare specifiers included."""
    mods = list(dict.fromkeys(import_specs(block[side])))
    if not mods and any(SPECIFIER_RE.match(l) for l in block[side] if l.strip()):
        enc = enclosing_module(h, block)
        if enc: mods = [enc]
    return mods

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
                added_specs = block_modules(h, b, "added"); removed_specs = block_modules(h, b, "removed")
                specs = specs or added_specs + removed_specs
                targets = targets or [rename_bases[k] for k in rename_bases if any(k in sp for sp in specs)]
                what = " / ".join(added_specs) or (("dropped: " + " / ".join(removed_specs)) if removed_specs else "")
                # Direction is known even when the module is not: a hunk can add a specifier whose
                # `} from "…"` sits past the last context line, and "which way" still matters more
                # to a reviewer than "from where".
                item = {"file": f.path, "hunk_ids": [h.id], "partial": partial, "added": added_specs, "removed": removed_specs,
                        "dir_added": any(l.strip() for l in b["added"]), "dir_removed": any(l.strip() for l in b["removed"]),
                        "detail": (what or h.header) + (" (inside a substantive hunk)" if partial else "")}
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

    # Registry rows + prop threading. Both are mechanical restatement the block classifier cannot
    # see, because both are ordinary code/prose lines — what makes them noise is a relationship to
    # something ELSE in the same diff (a file it adds, a prop it declares).
    added_paths = {e["path"] for e in model_files if e["status"] == "added"}
    declared = defaultdict(lambda: {"added": [], "removed": []})   # prop -> where its type was declared
    for f in files:
        if ext_of(f.path) not in (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"): continue
        for h in f.hunks:
            for side in ("added", "removed"):
                for l in getattr(h, side):
                    m = PROP_DECL_RE.match(l)
                    if m and f.path not in declared[m.group(1)][side]: declared[m.group(1)][side].append(f.path)
    threads = defaultdict(lambda: {"files": [], "hunk_ids": [], "flow": [], "kind": None})
    for f in files:
        for hi, h in enumerate(f.hunks):
            for b in getattr(h, "blocks", []):
                if b["category"] != "substantive": continue
                target = registry_row(f.path, b, added_paths)
                if target:
                    b["category"] = "registry"
                    folds["registry"].append({"file": f.path, "hunk_ids": [h.id], "target": target,
                                              "detail": f"index row for {target}"})
                    continue
                declares = {m.group(1) for l in b["added"] + b["removed"] for m in [PROP_DECL_RE.match(l)] if m}
                for name, where in declared.items():
                    if not (where["added"] or where["removed"]): continue
                    if name in declares: continue     # the declaration itself stays visible; only pass-sites fold
                    kind = thread_block(b, name)
                    if not kind: continue
                    b["category"] = "prop-thread"
                    t = threads[name]; t["kind"] = kind if t["kind"] in (None, kind) else "changed"
                    if f.path not in t["files"]: t["files"].append(f.path)
                    t["hunk_ids"].append(h.id)
                    side = b["added"] if kind == "added" else b["removed"]
                    # A `prop,` line RECEIVES the value (a destructured parameter); only a JSX
                    # attribute PASSES it on. Without the distinction every receiving component
                    # emitted an edge to an unknown child and the flow filled with "not named".
                    if all(re.match(r"^\s*" + re.escape(name) + r"\s*,\s*$", l) for l in side if l.strip()):
                        continue
                    passes = re.compile(r"^\s*" + re.escape(name) + r"(?:\s*=\s*\{[^{}]*\}|\s*=\s*\"[^\"]*\")?\s*/?>?\s*$")
                    if not any(passes.match(l) or (JSX_OPEN_RE.search(l) and name in l) for l in side):
                        continue      # a parameter list or type member: the file RECEIVES, it does not pass on
                    comp = target_component(h, b, side, f.hunks[hi - 1] if hi else None)
                    # An unresolved target is still an edge: the pass-site file is a fact, and
                    # dropping it would silently shrink the flow to the tags that happened to be
                    # inside a hunk. The renderer says "component not named in the hunk".
                    if not any(x["from"] == f.path and x["to"] == comp for x in t["flow"]):
                        t["flow"].append({"from": f.path, "to": comp})
                    break
    for f in files:
        for h in f.hunks:
            if getattr(h, "blocks", None) and all(b["category"] in ("registry", "prop-thread") for b in h.blocks):
                h.category = h.blocks[0]["category"]

    # A prop threaded inside ONE file is a local rename, not drilling: require a pass-site outside
    # the file that declares it, or the item says nothing a reviewer could not see in one hunk.
    base_to_path = {kebab(os.path.splitext(os.path.basename(e["path"]))[0]): e["path"] for e in model_files}
    for name, t in list(threads.items()):
        decl = declared[name]["added"] + declared[name]["removed"]
        if len(set(t["files"]) | set(decl)) < 2: del threads[name]; continue
        for edge in t["flow"]: edge["to_file"] = base_to_path.get(kebab(edge["to"] or ""))
        n = len(t["files"])       # files is exact; component names are only known where a tag was in reach
        where = f"{n} file{'s' if n != 1 else ''}"
        t["verb"] = (f"new prop threaded through {where}" if t["kind"] == "added"
                     else f"prop removed from {where}" if t["kind"] == "removed"
                     else f"prop re-threaded through {where}")
        folds["prop-thread"].append({"file": name, "prop": name, "kind": t["kind"], "verb": t["verb"],
                                     "files": sorted(t["files"]), "hunk_ids": list(dict.fromkeys(t["hunk_ids"])),
                                     "declared_in": sorted(set(decl)), "flow": t["flow"],
                                     "detail": f"{name} — {t['verb']}: " + ", ".join(sorted(t["files"]))})
    folds["prop-thread"].sort(key=lambda it: -len(it["files"]))

    for f in files:
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
        # Group by module, and keep the DIRECTION per file: a group that only added the import must
        # not be described as a removal (it was, for every barrel re-point — the added lines carry
        # no quoted path, so the module was unknown and the item fell into an "imports removed"
        # bucket while the diff showed additions only).
        by_mod = defaultdict(lambda: {"files": [], "hunk_ids": [], "added_in": [], "removed_in": []})
        for it in folds["import-rewrite"]:
            add, rem = it.get("added") or [], it.get("removed") or []
            named = list(dict.fromkeys(add + rem))
            # Unnamed modules still split by direction — one "added and dropped" bucket would hide
            # which files did which, and the module name is the only thing missing, not the fact.
            unnamed_key = UNRESOLVED_MODULE + ("+" if it.get("dir_added") else "") + ("-" if it.get("dir_removed") else "")
            for mod in named or [unnamed_key]:
                g = by_mod[mod]
                hits = (("files", True), ("added_in", mod in add if named else it.get("dir_added")),
                        ("removed_in", mod in rem if named else it.get("dir_removed")))
                for key, hit in hits:
                    if hit and it["file"] not in g[key]: g[key].append(it["file"])
                g["hunk_ids"] += it["hunk_ids"]
        def verb(mod, v):
            n = len(v["files"]); files = f"{n} file{'s' if n != 1 else ''}"
            add, rem = bool(v["added_in"]), bool(v["removed_in"])
            if mod.startswith(UNRESOLVED_MODULE):               # direction known, module named outside the hunk
                what = "imports added" if add and not rem else "imports dropped" if rem and not add else "imports added and dropped"
                return f"{what} in {files} (the module is named outside the hunk)"
            if add and not rem: return f"now imported in {files}"
            if rem and not add: return f"no longer imported in {files}"
            return f"imports changed in {files} (added in {len(v['added_in'])}, dropped in {len(v['removed_in'])})"
        folds["import-rewrite"] = [{"file": mod, "module": "" if mod.startswith(UNRESOLVED_MODULE) else mod, "files": sorted(v["files"]),
                                    "hunk_ids": list(dict.fromkeys(v["hunk_ids"])), "verb": verb(mod, v),
                                    "added_in": sorted(v["added_in"]), "removed_in": sorted(v["removed_in"]),
                                    "detail": (f"{mod} ← " if not mod.startswith(UNRESOLVED_MODULE) else "") + verb(mod, v) + ": " + ", ".join(sorted(v["files"]))}
                                   for mod, v in sorted(by_mod.items(), key=lambda kv: -len(kv[1]["files"]))]
    fold_titles = {"rename": "Renamed files (imports updated to match)", "move": "Moved files", "split": "Files split",
                   "import-rewrite": "Import-only changes (module ← the files whose imports of it changed)",
                   "prop-thread": "Props threaded through components (prop ← where it flows)",
                   "whitespace": "Whitespace-only hunks",
                   "format": "Formatting-only hunks", "comment-only": "Comment-only hunks",
                   "registry": "Index / registry rows for files added here", "notes": "Working notes (plans, handoffs, journals)",
                   "lockfile": "Lockfiles", "generated": "Generated / build output", "snapshot": "Test snapshots",
                   "vendored": "Vendored code", "binary": "Binary files"}
    ORDER = ["rename", "move", "split", "import-rewrite", "prop-thread", "format", "whitespace", "comment-only",
             "registry", "notes", "lockfile", "generated", "snapshot", "vendored", "binary"]
    fold_list = [{"kind": k, "title": fold_titles.get(k, k), "count": len(v), "items": v}
                 for k, v in folds.items() if v]
    fold_list.sort(key=lambda x: ORDER.index(x["kind"]) if x["kind"] in ORDER else 99)

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
