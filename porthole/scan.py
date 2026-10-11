"""Game detection: walk a directory, match it against every recipe.

Detection is deliberately boring. Case-insensitive glob matching on names and path
suffixes, plus optional size floors. No content hashing by default -- matching
`morrowind.esm` next to `morrowind.bsa` is already decisive, and hashing 2 GB to learn
what we already know is rude.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from . import registry

MAX_ENTRIES = 200_000
MAX_DEPTH = 8


@dataclass
class Tree:
    """A flattened, lowercased view of a directory."""

    root: Path
    paths: set[str] = field(default_factory=set)      # relative posix, lowercase
    names: set[str] = field(default_factory=set)      # basenames, lowercase
    exts: dict[str, list[str]] = field(default_factory=dict)
    total_bytes: int = 0
    truncated: bool = False


def walk(root: Path) -> Tree:
    t = Tree(root=root)
    root = root.resolve()
    count = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        if len(rel_dir.parts) >= MAX_DEPTH:
            dirnames[:] = []
            continue

        for d in dirnames:
            p = (rel_dir / d).as_posix().lower()
            t.paths.add(p)
            t.names.add(d.lower())

        for f in filenames:
            rel = (rel_dir / f).as_posix().lower()
            t.paths.add(rel)
            t.names.add(f.lower())

            ext = os.path.splitext(f)[1].lower()
            if ext:
                t.exts.setdefault(ext, []).append((rel_dir / f).as_posix())

            try:
                t.total_bytes += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass

            count += 1
            if count > MAX_ENTRIES:
                t.truncated = True
                return t
    return t


def _matches(pattern: str, t: Tree) -> bool:
    """A pattern with a slash matches a path suffix; otherwise it matches a basename."""
    pattern = pattern.lower()
    if "/" in pattern:
        return any(
            fnmatch(p, pattern) or fnmatch(p, f"*/{pattern}") for p in t.paths
        )
    return any(fnmatch(n, pattern) for n in t.names)


@dataclass
class Match:
    recipe: registry.Recipe
    score: int
    matched: list[str]
    confidence: str
    detail: dict = field(default_factory=dict)


def _score_recipe(rec: registry.Recipe, t: Tree) -> Match | None:
    det = rec.detect
    if not det:
        return None

    # Extension-table recipes (console ROMs) are handled separately.
    if "ext" in det:
        return _score_ext_recipe(rec, t, det["ext"])

    require = det.get("require", [])
    optional = det.get("any", [])

    hits_req = [p for p in require if _matches(p, t)]
    if len(hits_req) != len(require):
        return None

    hits_any = [p for p in optional if _matches(p, t)]

    need_count = det.get("require_count")
    if need_count and len(hits_any) < need_count:
        return None
    if not require and not hits_any:
        return None

    floor = det.get("min_bytes")
    if floor and t.total_bytes < floor:
        return None

    score = len(hits_req) * 10 + len(hits_any) * 2
    if require:
        score += 5                               # anchored recipes beat catch-alls

    declared = rec.raw.get("confidence")
    if declared == "low":
        conf = "low"
    elif require and len(require) >= 2:
        conf = "high"
    elif require:
        conf = "medium" if hits_any else "likely"
    else:
        conf = "medium"

    return Match(
        recipe=rec,
        score=score,
        matched=hits_req + hits_any,
        confidence=conf,
    )


def _score_ext_recipe(rec: registry.Recipe, t: Tree, table: dict) -> Match | None:
    found: dict[str, dict] = {}
    files: list[str] = []
    for ext, info in table.items():
        if ext in t.exts:
            found[ext] = info
            files.extend(t.exts[ext][:50])
    if not found:
        return None

    platforms = sorted({i.get("platform", "?") for i in found.values()})
    ambiguous = any(i.get("ambiguous") for i in found.values())

    return Match(
        recipe=rec,
        score=4 + len(files),
        matched=sorted(found),
        confidence="low" if ambiguous else "medium",
        detail={"platforms": platforms, "files": files, "cores": found},
    )


def scan(root: Path) -> tuple[Tree, list[Match]]:
    if not root.is_dir():
        raise NotADirectoryError(root)
    t = walk(root)
    out = [m for rec in registry.recipes().values() if (m := _score_recipe(rec, t))]

    # A specific recipe always outranks a family catch-all that also fired.
    specific = [m for m in out if not m.recipe.is_family]
    if specific:
        out = specific + [m for m in out if m.recipe.is_family and m.confidence != "low"]

    out.sort(key=lambda m: (-m.score, m.recipe.id))
    return t, out
