"""Resolve a recipe to a concrete runtime, layout, and honest expectation."""

from __future__ import annotations

from dataclasses import dataclass

from . import registry


@dataclass
class Plan:
    recipe: registry.Recipe
    runtime_id: str
    runtime: dict
    layout_id: str
    layout: dict | None
    problems: list[str]
    warnings: list[str]

    @property
    def buildable(self) -> bool:
        return not self.problems


def build_plan(recipe_id: str) -> Plan:
    recs = registry.recipes()
    if recipe_id not in recs:
        raise KeyError(recipe_id)
    rec = recs[recipe_id]

    rts = registry.runtimes()
    rt = rts.get(rec.runtime, {})
    lays = registry.layouts()
    lay = lays.get(rec.layout)

    problems: list[str] = []
    warnings: list[str] = []

    if not rt:
        problems.append(f"runtime '{rec.runtime}' is not in runtimes/registry.toml")
    else:
        ios = rt.get("ios", "planned")
        if ios == "planned":
            problems.append(f"runtime '{rec.runtime}' has no iOS port yet")
        elif ios == "wip":
            warnings.append(f"runtime '{rec.runtime}' iOS port is in progress")

        if rt.get("jit") == "required":
            warnings.append(
                "this runtime needs JIT to be playable — requires TrollStore, a "
                "jailbreak, or an iOS version where the ptrace trick works"
            )
        elif rt.get("jit") == "helps":
            warnings.append("runs without JIT, but noticeably faster with it")

    if lay is None:
        problems.append(f"touch layout '{rec.layout}' does not exist in layouts/")

    if rec.status == "blocked":
        problems.append("recipe is marked blocked — see its notes")
    if not rec.vendored:
        warnings.append(
            "upstream is not vendored by Porthole; you must fetch it yourself "
            "(see docs/LEGAL.md#contested-upstreams)"
        )
    if rec.tier == 4:
        warnings.append("tier 4 is a research track, not a working feature")

    return Plan(
        recipe=rec,
        runtime_id=rec.runtime,
        runtime=rt,
        layout_id=rec.layout,
        layout=lay,
        problems=problems,
        warnings=warnings,
    )
