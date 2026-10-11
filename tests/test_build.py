"""Build pipeline tests.

The layout compiler and the plan gating are pure and tested here. The actual
cross-compile is covered by `tools/verify-layouts.py` and by building `selftest` in
CI on macOS, because it needs an iOS SDK that Linux runners do not have.
"""

import shutil

import pytest

from porthole import build, registry


# ───────────────────────────── layout compilation ─────────────────────────────

def test_every_layout_compiles():
    for layout_id in registry.layouts():
        data = build.compile_layout(layout_id)
        assert data["id"] == layout_id
        # TOML spells it [[control]]; the Swift model expects `controls`.
        assert "controls" in data
        assert "control" not in data


def test_unknown_layout_raises():
    with pytest.raises(build.BuildError, match="no layout named"):
        build.compile_layout("not-a-real-layout")


def test_tuning_values_are_stringified():
    """The Swift model types `tuning` as [String: String], but TOML gives it bools."""
    data = build.compile_layout("pointer-trackpad")
    assert data["tuning"]["drag_lock"] == "true"
    assert all(isinstance(v, str) for v in data["tuning"].values())


def test_single_and_map_binds_both_survive():
    """`bind = "attack"` and `bind = { up = ... }` must both round-trip."""
    data = build.compile_layout("fps-twin-stick")
    binds = [c.get("bind") for c in data["controls"] if "bind" in c]
    assert any(isinstance(b, str) for b in binds), "no single-action bind found"
    assert any(isinstance(b, dict) for b in binds), "no direction-map bind found"


def test_offsets_stay_numeric_pairs():
    for layout_id in registry.layouts():
        for c in build.compile_layout(layout_id)["controls"]:
            if "offset" in c:
                assert len(c["offset"]) == 2, f"{layout_id}: bad offset {c['offset']}"
                assert all(isinstance(v, (int, float)) for v in c["offset"])


def router_actions() -> set[str]:
    """Parse the action names out of InputRouter.Action.

    Derived from the Swift source rather than duplicated here, because a hardcoded
    copy would drift and then quietly stop catching the bug it exists to catch.
    """
    src = (registry.repo_root() / "shell" / "Sources" / "Input"
           / "InputRouter.swift").read_text()

    body = src[src.index("enum Action: String {"):]
    body = body[: body.index("\n    }")]

    names: set[str] = set()
    for line in body.splitlines():
        line = line.split("//")[0].strip()
        if not line.startswith("case "):
            continue
        for part in line[len("case "):].split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                # case strafeLeft = "strafe_left"
                names.add(part.split("=", 1)[1].strip().strip('"'))
            else:
                # Without an explicit raw value, the raw value is the case name.
                names.add(part)
    return names


def test_router_action_list_parses():
    actions = router_actions()
    assert len(actions) > 30, f"only parsed {len(actions)} actions — parser broken?"
    assert "strafe_left" in actions
    assert "attack" in actions


def test_every_bound_action_is_known_to_the_router():
    """A layout binding an action the router cannot map is silently dead input."""
    known = router_actions()
    unknown = set()

    for layout_id in registry.layouts():
        for c in build.compile_layout(layout_id)["controls"]:
            bind = c.get("bind")
            if isinstance(bind, str):
                if not bind.startswith("mode:") and bind not in known:
                    unknown.add(f"{layout_id}: {bind}")
            elif isinstance(bind, dict):
                for action in bind.values():
                    if action not in known:
                        unknown.add(f"{layout_id}: {action}")

    assert not unknown, (
        "layouts bind actions InputRouter does not map (dead input): "
        f"{sorted(unknown)}")


def test_build_refuses_unbuildable_recipe():
    """A recipe whose runtime has no iOS port must fail with an explanation."""
    with pytest.raises(build.BuildError, match="not buildable"):
        build.build("quake")


def test_build_unknown_recipe_raises_keyerror():
    with pytest.raises(KeyError):
        build.build("halo-infinite")


def test_selftest_is_buildable_on_paper():
    """The reference runtime must always be plannable, or the pipeline has no target."""
    from porthole import plan as plan_mod
    p = plan_mod.build_plan("selftest")
    assert p.buildable, f"selftest should be buildable: {p.problems}"


# ───────────────────────────────── toolchain ─────────────────────────────────

@pytest.mark.skipif(shutil.which("xcrun") is None, reason="needs Xcode command line tools")
def test_toolchain_detects_ios_sdk():
    tc = build.Toolchain.detect()
    assert tc.sdk_path
    assert "iPhoneOS" in tc.sdk_path
    assert tc.target.startswith("arm64-apple-ios")


def test_ios_floor_covers_trollstore():
    """TrollStore covers iOS 14.0-17.0 and is the only path to the JIT entitlement.

    Raising the floor past 15 would exclude the users who benefit most, so this is
    pinned deliberately rather than by accident.
    """
    major = int(build.IOS_MIN.split(".")[0])
    assert major <= 15, "deployment floor must stay low enough for TrollStore users"
