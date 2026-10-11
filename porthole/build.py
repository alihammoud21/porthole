"""Cross-compile a runtime, compile the shell, and assemble an iOS app bundle.

No Xcode project is generated. The app is assembled directly with `swiftc`, `clang`,
and `plutil`, which means:

  - no .pbxproj to hand-generate or keep in sync (they are miserable to template)
  - the whole pipeline is scriptable and testable in CI
  - `porthole build` works the same on any machine with the command line tools

Build artifacts are cached by a hash of (sources, flags, toolchain), so the second
build of the same thing is close to free.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import registry

IOS_MIN = "15.0"
"""Deployment floor.

iOS 15 rather than something newer because TrollStore -- the install path that grants
the JIT entitlement, and therefore the only way N64/PSP/Dreamcast cores are playable
-- covers iOS 14.0 through 17.0. Requiring iOS 16 for `NavigationStack` would exclude
exactly the users who get the most out of this.
"""

BUNDLE_ID_PREFIX = "app.porthole"


class BuildError(RuntimeError):
    pass


# ───────────────────────────────── toolchain ─────────────────────────────────

@dataclass
class Toolchain:
    sdk_path: str
    sdk_version: str
    swiftc: str = "swiftc"
    clang: str = "clang"
    has_metal: bool = False

    @classmethod
    def detect(cls) -> "Toolchain":
        def xcrun(*args: str) -> str:
            try:
                return subprocess.run(
                    ["xcrun", *args], capture_output=True, text=True, check=True
                ).stdout.strip()
            except (OSError, subprocess.CalledProcessError) as e:
                raise BuildError(
                    "Xcode command line tools are required to build for iOS.\n"
                    "  Install Xcode, then: xcode-select --install"
                ) from e

        sdk_path = xcrun("--sdk", "iphoneos", "--show-sdk-path")
        sdk_version = xcrun("--sdk", "iphoneos", "--show-sdk-version")

        # The Metal compiler is a separately downloaded Xcode component now. Its
        # absence is not fatal: the shell compiles its shaders at runtime instead.
        has_metal = (
            subprocess.run(
                ["xcrun", "--sdk", "iphoneos", "--find", "metal"],
                capture_output=True,
            ).returncode
            == 0
        )

        return cls(sdk_path=sdk_path, sdk_version=sdk_version, has_metal=has_metal)

    @property
    def target(self) -> str:
        return f"arm64-apple-ios{IOS_MIN}"

    def run(self, args: list[str], what: str) -> None:
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise BuildError(f"{what} failed:\n{detail}")


# ───────────────────────────────── caching ─────────────────────────────────

def _hash_files(paths: list[Path], extra: str = "") -> str:
    h = hashlib.sha256()
    h.update(extra.encode())
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ───────────────────────────── layout compilation ─────────────────────────────

def compile_layout(layout_id: str) -> dict:
    """TOML layout to the JSON the shell decodes.

    The shell has no TOML parser on purpose -- it commits to zero third-party
    dependencies, and Codable handles JSON for free. Translating here also lets the
    build catch a malformed layout rather than the phone discovering it at launch.
    """
    path = registry.repo_root() / "layouts" / f"{layout_id}.toml"
    if not path.is_file():
        raise BuildError(f"no layout named '{layout_id}' in layouts/")

    data = tomllib.loads(path.read_text(encoding="utf-8"))

    # TOML spells it [[control]]; the Swift model calls the array `controls`.
    data["controls"] = data.pop("control", [])

    # `tuning` is free-form documentation of intent, and TOML gives it mixed types.
    # The shell models it as [String: String], so flatten here.
    if "tuning" in data:
        data["tuning"] = {
            k: (str(v).lower() if isinstance(v, bool) else str(v))
            for k, v in data["tuning"].items()
        }

    return data


# ───────────────────────────── runtime framework ─────────────────────────────

@dataclass
class RuntimeBuild:
    id: str
    framework: Path
    info: dict = field(default_factory=dict)


def build_runtime(runtime_id: str, tc: Toolchain, out_dir: Path,
                  cache_dir: Path) -> RuntimeBuild:
    """Compile a runtime to `<id>.framework`.

    Runtimes are frameworks loaded with dlopen rather than static libraries, because
    in library mode one app hosts many runtimes and every one of them exports the
    same seven symbols.
    """
    root = registry.repo_root()
    src_dir = root / "runtimes" / runtime_id / "src"
    if not src_dir.is_dir():
        raise BuildError(
            f"runtime '{runtime_id}' has no src/ in this repository.\n"
            f"  Runtimes with an upstream are fetched and patched instead -- that\n"
            f"  path is not implemented yet. See docs/ROADMAP.md."
        )

    sources = sorted(src_dir.glob("*.c")) + sorted(src_dir.glob("*.cpp"))
    if not sources:
        raise BuildError(f"runtime '{runtime_id}' has no sources in {src_dir}")

    include = root / "include"
    key = _hash_files(
        sources + sorted(include.glob("*.h")),
        extra=f"{tc.target}|{tc.sdk_version}|runtime|{runtime_id}",
    )
    cached = cache_dir / f"{runtime_id}-{key}.dylib"

    if not cached.is_file():
        cache_dir.mkdir(parents=True, exist_ok=True)
        objects = []
        for src in sources:
            obj = cache_dir / f"{runtime_id}-{key}-{src.stem}.o"
            is_cpp = src.suffix == ".cpp"
            tc.run(
                [
                    "xcrun", "--sdk", "iphoneos",
                    "clang++" if is_cpp else "clang",
                    "-arch", "arm64",
                    f"-mios-version-min={IOS_MIN}",
                    "-std=c++17" if is_cpp else "-std=c11",
                    "-O2", "-fvisibility=default",
                    "-Wall", "-Wextra",
                    f"-I{include}",
                    "-c", str(src), "-o", str(obj),
                ],
                f"compiling {src.name}",
            )
            objects.append(str(obj))

        # install_name must match where the framework lands in the bundle, or dlopen
        # resolves nothing at runtime.
        tc.run(
            [
                "xcrun", "--sdk", "iphoneos", "clang",
                "-arch", "arm64",
                f"-mios-version-min={IOS_MIN}",
                "-dynamiclib",
                "-install_name", f"@rpath/{runtime_id}.framework/{runtime_id}",
                *objects,
                "-o", str(cached),
            ],
            f"linking {runtime_id}",
        )

    framework = out_dir / f"{runtime_id}.framework"
    if framework.exists():
        shutil.rmtree(framework)
    framework.mkdir(parents=True)
    shutil.copy2(cached, framework / runtime_id)

    # iOS frameworks are flat -- no Versions/Current symlink farm.
    rt = registry.runtimes().get(runtime_id, {})
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": runtime_id,
        "CFBundleIdentifier": f"{BUNDLE_ID_PREFIX}.runtime.{runtime_id}",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": rt.get("name", runtime_id),
        "CFBundlePackageType": "FMWK",
        "CFBundleShortVersionString": str(rt.get("version", "1.0")),
        "CFBundleVersion": "1",
        "MinimumOSVersion": IOS_MIN,
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
    }
    (framework / "Info.plist").write_bytes(plistlib.dumps(plist))

    return RuntimeBuild(id=runtime_id, framework=framework, info=rt)


# ───────────────────────────────── shell ─────────────────────────────────

def build_shell(tc: Toolchain, out_binary: Path, cache_dir: Path) -> None:
    """Compile the Swift shell to a single executable."""
    root = registry.repo_root()
    sources = sorted((root / "shell" / "Sources").rglob("*.swift"))
    if not sources:
        raise BuildError("shell/Sources contains no Swift files")

    header = root / "shell" / "Sources" / "Runtime" / "Porthole-Bridging-Header.h"
    include = root / "include"

    key = _hash_files(
        sources + [header] + sorted(include.glob("*.h")),
        extra=f"{tc.target}|{tc.sdk_version}|shell",
    )
    cached = cache_dir / f"shell-{key}"

    if not cached.is_file():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tc.run(
            [
                "xcrun", "--sdk", "iphoneos", "swiftc",
                "-swift-version", "5",
                "-target", tc.target,
                "-sdk", tc.sdk_path,
                "-O",
                "-import-objc-header", str(header),
                f"-I{include}",
                # The shell dlopens runtimes from Frameworks/ next to the executable.
                "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks",
                *[str(s) for s in sources],
                "-o", str(cached),
            ],
            "compiling the shell",
        )

    out_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, out_binary)
    out_binary.chmod(0o755)


def build_metallib(tc: Toolchain, out_dir: Path) -> bool:
    """Precompile the shaders if a Metal toolchain exists.

    Returns whether it did. When it didn't, the shell compiles the same shader source
    at launch -- a few tens of milliseconds, and far better than making every
    contributor download a multi-gigabyte toolchain to build a 50-line shader.
    """
    if not tc.has_metal:
        return False

    shader = registry.repo_root() / "shell" / "Sources" / "Render" / "Shaders.metal"
    if not shader.is_file():
        return False

    air = out_dir / "_shaders.air"
    try:
        tc.run(
            ["xcrun", "-sdk", "iphoneos", "metal", "-c", str(shader), "-o", str(air)],
            "compiling shaders",
        )
        tc.run(
            ["xcrun", "-sdk", "iphoneos", "metallib", str(air),
             "-o", str(out_dir / "default.metallib")],
            "linking metallib",
        )
    except BuildError:
        return False
    finally:
        air.unlink(missing_ok=True)
    return True


# ───────────────────────────── bundle assembly ─────────────────────────────

def app_plist(bundle_id: str, name: str, display_name: str,
              tc: Toolchain, standalone: bool) -> dict:
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": display_name,
        "CFBundleExecutable": name,
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "MinimumOSVersion": IOS_MIN,
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "DTPlatformName": "iphoneos",
        "DTSDKName": f"iphoneos{tc.sdk_version}",
        "UIDeviceFamily": [1],  # iPhone only, for now
        "UIRequiredDeviceCapabilities": ["arm64", "metal"],
        "UILaunchScreen": {},
        # Essential to the whole asset story: without this the Files app will not
        # show the app's Documents directory, and there is no way to get a game in.
        "UIFileSharingEnabled": True,
        "LSSupportsOpeningDocumentsInPlace": True,
        "UIStatusBarHidden": True,
        "UIViewControllerBasedStatusBarAppearance": False,
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight",
            "UIInterfaceOrientationPortrait",
        ],
        "ITSAppUsesNonExemptEncryption": False,
    }


@dataclass
class BuildResult:
    app: Path
    bundle_id: str
    runtime: str
    layout: str
    precompiled_shaders: bool
    size_bytes: int
    attribution: list[dict]


def build(recipe_id: str, mode: str = "library", out_root: Path | None = None,
          verbose: bool = False) -> BuildResult:
    """Assemble an unsigned .app for one game."""
    from . import plan as plan_mod

    p = plan_mod.build_plan(recipe_id)
    rec = p.recipe

    if p.problems:
        raise BuildError(
            "this recipe is not buildable yet:\n"
            + "\n".join(f"  - {x}" for x in p.problems)
        )

    tc = Toolchain.detect()
    root = registry.repo_root()
    out_root = out_root or (root / "build")
    cache_dir = root / ".cache" / "artifacts"

    if mode == "standalone":
        app_name = "".join(c for c in rec.title if c.isalnum()) or rec.id
        bundle_id = f"{BUNDLE_ID_PREFIX}.game.{rec.id.replace('_', '-')}"
        display = rec.title
    else:
        app_name = "Porthole"
        # One stable bundle id for library mode, so re-signing never orphans the
        # Documents directory the games live in.
        bundle_id = f"{BUNDLE_ID_PREFIX}.shell"
        display = "Porthole"

    app = out_root / mode / f"{app_name}.app"
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)

    # 1. The runtime, as a dlopen-able framework.
    rt_build = build_runtime(rec.runtime, tc, app / "Frameworks", cache_dir)

    # 2. The shell executable.
    build_shell(tc, app / app_name, cache_dir)

    # 3. Shaders, if we can precompile them.
    precompiled = build_metallib(tc, app)

    # 4. Info.plist.
    (app / "Info.plist").write_bytes(
        plistlib.dumps(app_plist(bundle_id, app_name, display, tc, mode == "standalone"))
    )

    # 5. The game's manifest and compiled layout. These go in the bundle as a seed;
    #    on first launch the shell copies them into Documents/Games/<id>/ so that
    #    re-signing the app never disturbs imported assets or saves.
    seed = app / "Seed" / rec.id
    seed.mkdir(parents=True)

    manifest = {
        "id": rec.id,
        "title": rec.title,
        "year": rec.year,
        "tier": rec.tier,
        "runtime_id": rt_build.id,
        "runtime_name": rt_build.info.get("name", rt_build.id),
        "runtime_license": rt_build.info.get("license", "?"),
        "layout_id": rec.layout,
        "runtime_options": rec.raw.get("runtime_options", {}),
        "assets_imported": False,
    }
    (seed / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (seed / "layout.json").write_text(
        json.dumps(compile_layout(rec.layout), indent=2, sort_keys=True) + "\n"
    )

    # 6. Attribution. GPL compliance should be a build output, not something to
    #    remember -- so every license pulled in is recorded in the bundle.
    attribution = [
        {
            "component": "Porthole shell",
            "license": "GPL-3.0-or-later",
            "source": "https://github.com/alihammoud21/porthole",
        },
        {
            "component": rt_build.info.get("name", rt_build.id),
            "version": str(rt_build.info.get("version", "?")),
            "license": rt_build.info.get("license", "?"),
            "source": rt_build.info.get("upstream", "?"),
        },
    ]
    (app / "ATTRIBUTION.json").write_text(
        json.dumps(attribution, indent=2) + "\n"
    )

    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())

    return BuildResult(
        app=app,
        bundle_id=bundle_id,
        runtime=rt_build.id,
        layout=rec.layout,
        precompiled_shaders=precompiled,
        size_bytes=size,
        attribution=attribution,
    )
