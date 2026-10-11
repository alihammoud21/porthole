"""Porthole command line."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from . import (__version__, bootstrap as bootstrap_mod, build as build_mod,
               plan as plan_mod, registry, scan as scan_mod, sign as sign_mod, ui)


# ───────────────────────────────── scan ─────────────────────────────────

def cmd_scan(args) -> int:
    root = Path(args.path).expanduser()
    try:
        tree, matches = scan_mod.scan(root)
    except NotADirectoryError:
        ui.error(f"not a directory: {root}")
        return 2

    if tree.truncated:
        ui.warn(f"stopped after {scan_mod.MAX_ENTRIES:,} files; results may be partial")

    if not matches:
        print(f"\nNo recognized game in {ui.bold(str(root))}")
        print(ui.dim(f"  scanned {len(tree.paths):,} entries, {ui.human_bytes(tree.total_bytes)}\n"))
        print("That means Porthole has no recipe for it yet, not that it can't work.")
        print("If you know what this game is, a recipe is ~30 lines of TOML:")
        print(ui.cyan("  docs/RECIPES.md"))
        return 1

    print(f"\nScanned {ui.bold(str(root))}  "
          f"{ui.dim(f'{len(tree.paths):,} entries · {ui.human_bytes(tree.total_bytes)}')}")

    for m in matches:
        rec = m.recipe
        year = f" ({rec.year})" if rec.year else ""
        print(ui.heading(f"  {rec.title}{year}"))

        rt = registry.runtimes().get(rec.runtime, {})
        rt_name = rt.get("name", rec.runtime)
        rt_ver = rt.get("version", "")
        print(ui.field("runtime", f"{rt_name} {rt_ver}".strip()
                       + f"   {ui.dim(ui.tier(rec.tier))}"))
        print(ui.field("status", f"{ui.status(rec.status)}   "
                       f"{ui.dim('confidence ' + m.confidence)}"))
        print(ui.field("matched", ", ".join(m.matched[:6])
                       + (ui.dim(f" +{len(m.matched) - 6} more") if len(m.matched) > 6 else "")))

        if plats := m.detail.get("platforms"):
            print(ui.field("platforms", ", ".join(plats)))
            print(ui.field("roms", f"{len(m.detail['files'])} file(s)"))

        print(ui.field("controls", rec.layout))
        if exp := rec.expect:
            best = exp.get("a17") or exp.get("a15") or exp.get("a13")
            if best:
                print(ui.field("expect", best))

    print()
    first = matches[0].recipe.id
    print(ui.dim(f"  next:  porthole plan {first}"))
    print()
    return 0


# ───────────────────────────────── plan ─────────────────────────────────

def cmd_plan(args) -> int:
    try:
        p = plan_mod.build_plan(args.game)
    except KeyError:
        ui.error(f"no recipe with id '{args.game}'")
        print(ui.dim("  porthole list games"), file=sys.stderr)
        return 2

    rec = p.recipe
    year = f" ({rec.year})" if rec.year else ""
    print(ui.heading(f"{rec.title}{year}"))
    print(ui.field("recipe", str(rec.path.name), 12))
    print(ui.field("tier", ui.tier(rec.tier), 12))
    print(ui.field("status", ui.status(rec.status), 12))

    rt = p.runtime
    print(ui.field("runtime", f"{rt.get('name', p.runtime_id)} {rt.get('version', '')}".strip(), 12))
    if rt:
        print(ui.field("license", rt.get("license", "?"), 12))
        print(ui.field("upstream", ui.dim(rt.get("upstream", "?")), 12))
        print(ui.field("ios port", rt.get("ios", "?"), 12))
        print(ui.field("graphics", rt.get("gfx", "?"), 12))
    print(ui.field("controls", p.layout_id + ("" if p.layout else ui.red("  (missing)")), 12))

    if exp := rec.expect:
        print(ui.heading("Expected performance"))
        for k in ("a17", "a15", "a13"):
            if k in exp:
                label = {"a17": "A17 / M-series", "a15": "A15–A16", "a13": "A13–A14"}[k]
                print(ui.field(label, exp[k], 16))
        if "jit" in exp:
            print(ui.field("JIT", exp["jit"], 16))

    if assets := rec.raw.get("assets"):
        print(ui.heading("Assets"))
        print(ui.field("target", assets.get("target", "."), 16))
        if inc := assets.get("include"):
            print(ui.field("include", ", ".join(inc[:5])
                           + (ui.dim(f" +{len(inc) - 5} more") if len(inc) > 5 else ""), 16))

    if rec.caveats:
        print(ui.heading("Notes"))
        for c in rec.caveats:
            print(f"  {ui.dim('·')} {c}")

    if p.warnings:
        print(ui.heading("Warnings"))
        for w in p.warnings:
            print(f"  {ui.yellow('!')} {w}")

    if p.problems:
        print(ui.heading("Blocking"))
        for b in p.problems:
            print(f"  {ui.red('✗')} {b}")
        print(f"\n{ui.dim('  Not buildable yet. These are tracked as issues — help welcome.')}\n")
        return 1

    print(f"\n{ui.green('  Ready to build')} "
          f"{ui.dim('(once the build backend lands — see docs/ROADMAP.md)')}\n")
    return 0


# ───────────────────────────────── list ─────────────────────────────────

def cmd_list(args) -> int:
    what = args.what

    if what == "games":
        recs = sorted(registry.recipes().values(), key=lambda r: (r.tier, r.id))
        print(ui.heading(f"{len(recs)} recipes"))
        for r in recs:
            fam = ui.dim(" [family]") if r.is_family else ""
            print(f"  {r.id:<18} {ui.dim(f'T{r.tier}'):<6} {ui.status(r.status):<22} "
                  f"{r.title}{fam}")

    elif what == "runtimes":
        rts = registry.runtimes()
        print(ui.heading(f"{len(rts)} runtimes"))
        for rid, rt in sorted(rts.items(), key=lambda kv: (kv[1].get("tier", 9), kv[0])):
            ios = rt.get("ios", "?")
            color = {"ready": ui.green, "wip": ui.yellow}.get(ios, ui.dim)
            print(f"  {rid:<26} {ui.dim('T' + str(rt.get('tier', '?'))):<6} "
                  f"{color(ios):<18} {rt.get('license', '?')}")

    elif what == "layouts":
        lays = registry.layouts()
        print(ui.heading(f"{len(lays)} layouts"))
        for lid, lay in sorted(lays.items()):
            n = len(lay.get("control", []))
            print(f"  {lid:<22} {ui.dim(f'{n} controls')}  {lay.get('name', '')}")

    print()
    return 0


# ─────────────────────────────── validate ───────────────────────────────

def cmd_validate(args) -> int:
    """CI gate: every reference resolves, every recipe is honest."""
    errors: list[str] = []
    todo: list[str] = []

    rts, lays, recs = registry.runtimes(), registry.layouts(), registry.recipes()

    for rid, rec in sorted(recs.items()):
        where = rec.path.name
        if rec.runtime not in rts:
            errors.append(f"{where}: unknown runtime '{rec.runtime}'")
        if rec.layout == "unset":
            errors.append(f"{where}: no layout declared")
        elif rec.layout not in lays and rec.layout != "passthrough":
            todo.append(f"{where}: layout '{rec.layout}' not written yet")
        if rec.status not in ("supported", "partial", "experimental", "planned", "blocked"):
            errors.append(f"{where}: invalid status '{rec.status}'")
        if rec.tier not in (1, 2, 3, 4):
            errors.append(f"{where}: invalid tier {rec.tier}")
        if not rec.detect:
            errors.append(f"{where}: no [detect] block")

    for rid, rt in sorted(rts.items()):
        if "license" not in rt:
            errors.append(f"registry.toml [{rid}]: no license declared")
        if rt.get("version") in ("main", "nightly") and rt.get("ios") == "ready":
            todo.append(f"registry.toml [{rid}]: pin a tag instead of a moving branch")

    for line in todo:
        print(f"  {ui.yellow('todo')}  {line}")
    for line in errors:
        print(f"  {ui.red('fail')}  {line}")

    print()
    if errors:
        print(f"{ui.red('✗')} {len(errors)} error(s), {len(todo)} todo\n")
        return 1
    print(f"{ui.green('✓')} {len(recs)} recipes, {len(rts)} runtimes, {len(lays)} layouts "
          f"— all references resolve ({len(todo)} todo)\n")
    return 0


# ──────────────────────────────── doctor ────────────────────────────────

_TOOLS = [
    ("git", "required", "clone runtime sources"),
    ("cmake", "required to build", "most runtimes build with cmake"),
    ("xcodebuild", "required to build", "part of Xcode, not just the CLI tools"),
    ("ios-deploy", "optional", "install over USB: npm i -g ios-deploy"),
    ("ideviceinstaller", "optional", "alternative USB install: brew install libimobiledevice"),
    ("ldid", "optional", "entitlement editing for TrollStore builds"),
]


def cmd_doctor(args) -> int:
    print(ui.heading("Porthole doctor"))
    print(ui.field("version", __version__, 14))
    print(ui.field("python", sys.version.split()[0], 14))
    print(ui.field("repo", str(registry.repo_root()), 14))

    print(ui.heading("Toolchain"))
    missing_required = 0
    for tool, need, why in _TOOLS:
        path = shutil.which(tool)
        if path:
            print(f"  {ui.green('✓')} {tool:<18} {ui.dim(path)}")
        else:
            mark = ui.red("✗") if need.startswith("required") else ui.yellow("–")
            if need.startswith("required"):
                missing_required += 1
            print(f"  {mark} {tool:<18} {ui.dim(f'{need} — {why}')}")

    print(ui.heading("Signing identities"))
    try:
        out = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        ids = [l.strip() for l in out.splitlines() if "Apple Develop" in l]
        if ids:
            for line in ids:
                print(f"  {ui.green('✓')} {line.split(') ', 1)[-1]}")
        else:
            print(f"  {ui.yellow('–')} none found — open Xcode and sign in with your "
                  f"Apple ID\n    {ui.dim('see docs/INSTALLING.md')}")
    except (OSError, subprocess.SubprocessError):
        print(f"  {ui.dim('– could not query the keychain')}")

    print(ui.heading("Data"))
    print(ui.field("recipes", str(len(registry.recipes())), 14))
    print(ui.field("runtimes", str(len(registry.runtimes())), 14))
    print(ui.field("layouts", str(len(registry.layouts())), 14))
    print()
    return 1 if missing_required else 0


# ───────────────────────────────── build ─────────────────────────────────

def cmd_build(args) -> int:
    try:
        result = build_mod.build(args.game, mode=args.mode, verbose=args.verbose)
    except KeyError:
        ui.error(f"no recipe with id '{args.game}'")
        print(ui.dim("  porthole list games"), file=sys.stderr)
        return 2
    except build_mod.BuildError as e:
        ui.error(str(e))
        return 1

    print(ui.heading("Built"))
    print(ui.field("app", str(result.app), 14))
    print(ui.field("bundle id", result.bundle_id, 14))
    print(ui.field("mode", args.mode, 14))
    print(ui.field("runtime", result.runtime, 14))
    print(ui.field("controls", result.layout, 14))
    print(ui.field("size", ui.human_bytes(result.size_bytes), 14))
    print(ui.field("shaders", "precompiled" if result.precompiled_shaders
                   else "compiled at launch (no Metal toolchain)", 14))

    print(ui.heading("Licenses in this build"))
    for item in result.attribution:
        version = f" {item['version']}" if item.get("version") else ""
        print(f"  {item['component']}{version} — {ui.bold(item['license'])}")
    print(ui.dim("  recorded in ATTRIBUTION.json inside the bundle"))

    print(f"\n{ui.dim('  next:  porthole sign')}\n")
    return 0


# ───────────────────────────── sign / install ─────────────────────────────

def _resolve_app(path_arg: str | None, mode: str) -> Path:
    if path_arg:
        return Path(path_arg).expanduser()
    root = registry.repo_root() / "build" / mode
    apps = sorted(root.glob("*.app")) if root.is_dir() else []
    if not apps:
        raise sign_mod.SignError(
            f"nothing built in {root}.\n  Run: porthole build <game> --mode {mode}")
    return apps[0]


def cmd_sign(args) -> int:
    try:
        app = _resolve_app(args.app, args.mode)
        result = sign_mod.sign(app)
        sign_mod.verify(result.app)
    except sign_mod.SignError as e:
        ui.error(str(e))
        return 1

    print(ui.heading("Signed"))
    print(ui.field("app", str(result.app), 14))
    print(ui.field("bundle id", result.bundle_id, 14))
    print(ui.field("identity", result.identity.name, 14))
    print(ui.field("team", result.profile.team_id, 14))
    print(ui.field("profile", result.profile.path.name, 14))

    if result.days_left is not None:
        if result.days_left <= 0:
            print(ui.field("expires", ui.red("already expired"), 14))
        elif result.days_left <= 8:
            # Free Apple IDs get 7 days. This is the single most common surprise.
            print(ui.field("expires", ui.yellow(
                f"in {result.days_left} day(s) — free account"), 14))
            print(f"\n  {ui.dim('Re-sign with `porthole sign` again; saves and')}")
            print(f"  {ui.dim('imported games are untouched by re-signing.')}")
        else:
            print(ui.field("expires", f"in {result.days_left} days", 14))

    if args.ipa:
        ipa = sign_mod.make_ipa(result.app)
        print(ui.field("ipa", f"{ipa}  {ui.dim(ui.human_bytes(ipa.stat().st_size))}", 14))

    print(f"\n{ui.dim('  next:  porthole install')}\n")
    return 0


def cmd_install(args) -> int:
    try:
        app = _resolve_app(args.app, args.mode)
        where = sign_mod.install(app)
    except sign_mod.SignError as e:
        ui.error(str(e))
        return 1
    print(f"\n{ui.green('  Installed')} to {ui.bold(where)}\n")
    return 0


# ───────────────────────────── bootstrap ─────────────────────────────

def cmd_bootstrap(args) -> int:
    """Register an app id with Apple so a provisioning profile exists."""
    mode = args.mode
    bundle_id = args.bundle_id or (
        f"{build_mod.BUNDLE_ID_PREFIX}.shell" if mode == "library"
        else f"{build_mod.BUNDLE_ID_PREFIX}.game.{args.game}")

    if not args.dry_run:
        print(ui.heading("This contacts Apple"))
        print(f"  Registers {ui.bold(bundle_id)} on your developer account and")
        print("  downloads a provisioning profile.")
        print(ui.yellow("  A free Apple ID may only register 10 app ids per 7 days."))
        print(ui.dim("  Your Apple ID must already be signed in to Xcode."))
        print()

    try:
        result = bootstrap_mod.bootstrap(
            bundle_id, team_id=args.team, dry_run=args.dry_run)
    except sign_mod.SignError as e:
        ui.error(str(e))
        return 1

    if args.dry_run:
        print(ui.heading("Dry run"))
        print(ui.field("bundle id", result.bundle_id, 14))
        print(ui.field("team", result.team_id, 14))
        print(ui.field("project", str(result.project_dir), 14))
        print(f"\n  {ui.green('Project generated and parsed by xcodebuild.')}")
        print(f"  {ui.dim('Apple was not contacted. Drop --dry-run to register.')}\n")
        return 0

    print(ui.heading("Registered"))
    print(ui.field("bundle id", result.bundle_id, 14))
    print(ui.field("team", result.team_id, 14))
    print(f"\n{ui.green('  Provisioning profile created.')} "
          f"{ui.dim('porthole sign will find it from now on.')}\n")
    return 0


# ───────────────────────────── stubs ─────────────────────────────

def cmd_unimplemented(args) -> int:
    name = args._name
    ui.error(f"'{name}' is not implemented yet")
    print(f"\n  The {ui.bold(name)} stage is the current focus. See:")
    print(f"    {ui.cyan('docs/ROADMAP.md')}")
    print(f"    {ui.cyan('docs/ARCHITECTURE.md')}  for the intended design")
    print(f"\n  {ui.dim('scan, plan, list, validate and doctor all work today.')}\n")
    return 3


# ───────────────────────────── entry point ─────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="porthole",
        description="Turn game files you own into an iPhone app.",
        epilog="Bring your own game files. See docs/LEGAL.md.",
    )
    ap.add_argument("--version", action="version", version=f"porthole {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="identify a game in a directory")
    p.add_argument("path", help="directory containing your game files")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("plan", help="show runtime, controls and expectations")
    p.add_argument("game", help="recipe id (see: porthole list games)")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("list", help="list recipes, runtimes or layouts")
    p.add_argument("what", choices=["games", "runtimes", "layouts"])
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("validate", help="check that all references resolve (CI gate)")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("doctor", help="check the local toolchain")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("build", help="cross-compile the runtime and assemble an app")
    p.add_argument("game", help="recipe id (see: porthole list games)")
    p.add_argument("--mode", choices=["library", "standalone"], default="library",
                   help="one app for many games (default), or one app per game")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("sign", help="sign with your own certificate")
    p.add_argument("app", nargs="?", help="path to a .app (default: the last build)")
    p.add_argument("--mode", choices=["library", "standalone"], default="library")
    p.add_argument("--ipa", action="store_true",
                   help="also package an .ipa for SideStore / AltStore")
    p.set_defaults(fn=cmd_sign)

    p = sub.add_parser(
        "bootstrap",
        help="register an app id with Apple so a profile exists (contacts Apple)")
    p.add_argument("game", nargs="?", default="selftest",
                   help="recipe id, for --mode standalone")
    p.add_argument("--mode", choices=["library", "standalone"], default="library")
    p.add_argument("--bundle-id", help="override the bundle identifier")
    p.add_argument("--team", help="team id (default: from your keychain)")
    p.add_argument("--dry-run", action="store_true",
                   help="generate and validate the project without contacting Apple")
    p.set_defaults(fn=cmd_bootstrap)

    p = sub.add_parser("install", help="deploy to a connected iPhone over USB")
    p.add_argument("app", nargs="?", help="path to a .app (default: the last build)")
    p.add_argument("--mode", choices=["library", "standalone"], default="library")
    p.set_defaults(fn=cmd_install)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130
    except (ValueError, FileNotFoundError) as e:
        ui.error(str(e))
        return 2
