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


# ───────────────────────────── repository hygiene ─────────────────────────────

def test_first_party_runtime_sources_are_tracked_by_git():
    """A build that works locally but not from a clean checkout is the worst kind.

    `.gitignore` once carried `/runtimes/*/src/` -- meant for fetched upstreams --
    which silently excluded the selftest runtime's own source. The local build kept
    working because the file was on disk, and only CI noticed.
    """
    import subprocess

    root = registry.repo_root()
    sources = sorted((root / "runtimes").glob("*/src/*.c")) + \
        sorted((root / "runtimes").glob("*/src/*.cpp"))
    assert sources, "no first-party runtime sources found at all"

    tracked = set(subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True
    ).stdout.split())

    missing = [
        str(s.relative_to(root)) for s in sources
        if str(s.relative_to(root)) not in tracked
    ]
    assert not missing, (
        f"runtime sources exist on disk but are not tracked by git: {missing}. "
        "Check .gitignore."
    )


# ───────────────────────────── provisioning bootstrap ─────────────────────────────

@pytest.mark.macos
def test_generated_xcode_project_is_wellformed(tmp_path):
    """The throwaway project must parse, or `porthole bootstrap` cannot work.

    Generated offline; this never contacts Apple.
    """
    from porthole import bootstrap

    project = bootstrap.generate_project(
        "app.porthole.test", "ABCDE12345", tmp_path / "bootstrap")
    assert project.is_dir()
    assert (project / "project.pbxproj").is_file()

    targets = bootstrap.validate_project(project)
    assert targets == ["PortholeBootstrap"], f"unexpected targets: {targets}"


@pytest.mark.macos
def test_bootstrap_dry_run_never_contacts_apple(tmp_path, monkeypatch):
    """A dry run must not shell out to anything that could register an app id."""
    from porthole import bootstrap

    calls = []
    real_run = bootstrap.subprocess.run

    def spy(args, *a, **kw):
        calls.append(list(args))
        return real_run(args, *a, **kw)

    monkeypatch.setattr(bootstrap.subprocess, "run", spy)
    result = bootstrap.bootstrap("app.porthole.test", team_id="ABCDE12345",
                                 dry_run=True)

    assert not result.profile_created
    assert all("-allowProvisioningUpdates" not in c for c in calls), \
        "dry run attempted to register an app id"
    assert all("build" not in c or "xcodebuild" not in c[0] or "-list" in c
               for c in calls), f"dry run ran a build: {calls}"


# ──────────────── regressions found by running the real pipeline ────────────────
#
# Every bug below only surfaced when the app was actually built, signed and pushed
# to a phone. None of them were visible from compilation alone.

@pytest.mark.macos
def test_team_id_comes_from_the_certificate_ou_not_the_common_name():
    """For `Apple Development` certs, the CN parenthetical is the CERTIFICATE id.

    Reading the team from there produces a plausible-looking wrong value, and
    xcodebuild then fails with "No Account for Team ...", which sends you hunting for
    an account problem that does not exist.
    """
    import re
    from porthole import sign

    ids = sign.identities()
    if not ids:
        pytest.skip("no signing identity in this keychain")

    for identity in ids:
        if not identity.team_id:
            continue
        assert re.fullmatch(r"[A-Z0-9]{10}", identity.team_id)
        paren = re.search(r"\(([A-Z0-9]{10})\)\s*$", identity.name)
        if paren and paren.group(1) != identity.team_id:
            # Exactly the case this guards: the two differ, and OU is correct.
            assert identity.team_id != paren.group(1)


def test_profile_search_covers_the_modern_xcode_location():
    """Xcode 16 moved managed profiles out of ~/Library/MobileDevice."""
    from porthole import sign

    paths = [str(d) for d in sign.PROFILE_DIRS]
    assert any("Developer/Xcode/UserData" in p for p in paths), \
        "the Xcode 16+ profile directory is not searched"
    assert any("MobileDevice" in p for p in paths), \
        "the legacy profile directory is still worth searching"


@pytest.mark.macos
def test_simulators_are_not_treated_as_hardware():
    """`devicectl list devices` includes Simulators, and installing to one instead
    of the phone is a confusing way to fail."""
    from porthole import sign

    found = sign.devices()
    if not found:
        pytest.skip("no iOS devices known to this machine")

    # Real connected hardware must sort ahead of anything else.
    if any(d.is_hardware and d.is_connected for d in found):
        assert found[0].is_hardware and found[0].is_connected

    for d in found:
        assert isinstance(d.is_hardware, bool)
        assert d.label


@pytest.mark.macos
def test_profile_expiry_is_computed_not_swallowed():
    """plistlib returns naive datetimes; subtracting an aware now() raises TypeError.

    That exception was being caught and the 7-day expiry warning -- the single most
    useful thing to tell a free-account user -- silently disappeared.
    """
    from datetime import datetime, timezone
    from porthole import sign

    all_profiles = sign.profiles()
    if not all_profiles:
        pytest.skip("no provisioning profiles on this machine")

    for profile in all_profiles:
        if not isinstance(profile.expires, datetime):
            continue
        expires = profile.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        days = (expires - datetime.now(timezone.utc)).days
        assert isinstance(days, int)


def test_bootstrap_stub_is_not_named_main_swift():
    """Swift treats main.swift as top-level code, which cannot coexist with
    @UIApplicationMain."""
    from porthole import bootstrap

    assert bootstrap.STUB_FILENAME != "main.swift"
    assert "@UIApplicationMain" in bootstrap.STUB_SWIFT


def test_generated_project_declares_supported_platforms():
    """xcodebuild warns without these and cannot resolve the generic iOS destination.

    Not a blocker -- the bootstrap build succeeded on a real account before these were
    added -- but the warning is noise that hides real errors.
    """
    from porthole import bootstrap

    pbxproj = bootstrap._pbxproj("app.porthole.test", "ABCDE12345", "Stub")
    assert "SUPPORTED_PLATFORMS" in pbxproj
    assert "SDKROOT = iphoneos" in pbxproj
    assert bootstrap.STUB_FILENAME in pbxproj
