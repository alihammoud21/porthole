"""Loads the runtime registry, recipes, and touch layouts off disk."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path


def repo_root() -> Path:
    """Walk up from this file until we find the data directories."""
    here = Path(__file__).resolve()
    for parent in [here.parent.parent, *here.parents]:
        if (parent / "recipes").is_dir() and (parent / "runtimes").is_dir():
            return parent
    raise FileNotFoundError(
        "could not locate the Porthole repository root (expected recipes/ and runtimes/)"
    )


def _load(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path.name}: {e}") from e


@dataclass
class Recipe:
    id: str
    title: str
    runtime: str
    tier: int
    status: str
    path: Path
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def is_family(self) -> bool:
        return bool(self.raw.get("family"))

    @property
    def year(self):
        return self.raw.get("year")

    @property
    def layout(self) -> str:
        return self.raw.get("layout", "unset")

    @property
    def detect(self) -> dict:
        return self.raw.get("detect", {})

    @property
    def expect(self) -> dict:
        return self.raw.get("expect", {})

    @property
    def caveats(self) -> list[str]:
        return self.raw.get("notes", {}).get("caveats", [])

    @property
    def vendored(self) -> bool:
        return self.raw.get("vendor", True)


@cache
def recipes() -> dict[str, Recipe]:
    out: dict[str, Recipe] = {}
    for p in sorted((repo_root() / "recipes").glob("*.toml")):
        if p.name.startswith("_"):
            continue
        d = _load(p)
        rid = d.get("id") or p.stem
        out[rid] = Recipe(
            id=rid,
            title=d.get("title", rid),
            runtime=d.get("runtime", "?"),
            tier=int(d.get("tier", 0)),
            status=d.get("status", "planned"),
            path=p,
            raw=d,
        )
    return out


@cache
def runtimes() -> dict[str, dict]:
    d = _load(repo_root() / "runtimes" / "registry.toml")
    out = {}
    for key, val in d.items():
        if not isinstance(val, dict):
            continue
        if key == "core":                      # nested [core.xxx] tables
            for ck, cv in val.items():
                out[f"core.{ck}"] = cv
        else:
            out[key] = val
    return out


@cache
def layouts() -> dict[str, dict]:
    out = {}
    for p in sorted((repo_root() / "layouts").glob("*.toml")):
        if p.name.startswith("_"):
            continue
        d = _load(p)
        out[d.get("id", p.stem)] = d
    return out
