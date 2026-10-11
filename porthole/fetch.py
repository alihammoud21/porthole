"""Fetch and patch an upstream runtime's source.

Everything built so far lives in this repository. A real engine does not: it lives
upstream, and Porthole fetches it rather than vendoring it. That is partly disk
hygiene and partly policy — docs/LEGAL.md commits to never mirroring contested
decompilation source, and the cleanest way to honour that is to have no mechanism for
vendoring anything.

Sources land in `.cache/sources/<id>/`, which is gitignored, and a CI invariant
rejects any attempt to commit them.

Pinning is strict. A runtime declares a tag *and* the commit that tag pointed at, and
the fetch fails if they disagree. Tags are mutable; the thing being built is somebody's
ability to play a game they own, and silently building different code than last week
is worse than refusing to build.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import registry


class FetchError(RuntimeError):
    pass


@dataclass
class Dependency:
    name: str
    git: str | None = None
    tag: str | None = None
    commit: str | None = None
    note: str = ""


@dataclass
class BuildManifest:
    """`runtimes/<id>/build.toml` — how to fetch and build one upstream runtime."""

    runtime: str
    git: str
    tag: str
    commit: str | None = None
    submodules: bool = False
    system: str = "cmake"
    cmake_args: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    patches: list[str] = field(default_factory=list)
    adapter: str | None = None
    notes: str = ""

    @classmethod
    def load(cls, runtime_id: str) -> "BuildManifest":
        path = registry.repo_root() / "runtimes" / runtime_id / "build.toml"
        if not path.is_file():
            raise FetchError(
                f"runtime '{runtime_id}' has no build.toml.\n"
                f"  Expected at {path.relative_to(registry.repo_root())}\n"
                "  See docs/RUNTIMES.md for the schema."
            )
        d = tomllib.loads(path.read_text(encoding="utf-8"))

        source = d.get("source", {})
        build = d.get("build", {})
        if not source.get("git"):
            raise FetchError(f"{path.name}: [source] needs a git url")
        if not source.get("tag"):
            raise FetchError(f"{path.name}: [source] needs a tag — branches are not pinnable")

        return cls(
            runtime=d.get("runtime", runtime_id),
            git=source["git"],
            tag=source["tag"],
            commit=source.get("commit"),
            submodules=bool(source.get("submodules")),
            system=build.get("system", "cmake"),
            cmake_args=list(build.get("cmake_args", [])),
            targets=list(build.get("targets", [])),
            dependencies=[
                Dependency(
                    name=x.get("name", "?"),
                    git=x.get("git"),
                    tag=x.get("tag"),
                    commit=x.get("commit"),
                    note=x.get("note", ""),
                )
                for x in d.get("dependencies", [])
            ],
            patches=list(d.get("patches", {}).get("series", [])),
            adapter=d.get("adapter", {}).get("source"),
            notes=d.get("notes", {}).get("text", ""),
        )


def source_dir(runtime_id: str) -> Path:
    return registry.repo_root() / ".cache" / "sources" / runtime_id


# ───────────────────────────────── fetching ─────────────────────────────────

def _git(args: list[str], cwd: Path | None = None, what: str = "git") -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FetchError(f"{what} failed:\n{(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip()


@dataclass
class FetchResult:
    runtime: str
    path: Path
    commit: str
    tag: str
    reused: bool
    patches_applied: list[str]
    size_bytes: int


def fetch(runtime_id: str, force: bool = False,
          shallow: bool = True) -> FetchResult:
    """Clone (or reuse) the upstream at its pinned tag, then apply the patch series."""
    manifest = BuildManifest.load(runtime_id)
    dest = source_dir(runtime_id)

    reused = False
    if dest.is_dir() and not force:
        # Reuse only if it is actually at the pinned revision.
        try:
            head = _git(["rev-parse", "HEAD"], cwd=dest)
        except FetchError:
            head = ""
        if manifest.commit and head == manifest.commit:
            reused = True
        elif not manifest.commit and head:
            reused = True
        else:
            shutil.rmtree(dest)
    elif dest.is_dir():
        shutil.rmtree(dest)

    if not reused:
        dest.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--branch", manifest.tag]
        if shallow and not manifest.submodules:
            # Submodules plus shallow is a reliable way to get a broken checkout.
            args += ["--depth", "1"]
        if manifest.submodules:
            args += ["--recurse-submodules"]
        args += [manifest.git, str(dest)]
        _git(args, what=f"cloning {manifest.git} at {manifest.tag}")

    head = _git(["rev-parse", "HEAD"], cwd=dest)

    # Strict pinning. A tag can be moved; a commit cannot.
    if manifest.commit and head != manifest.commit:
        raise FetchError(
            f"pin mismatch for '{runtime_id}'.\n"
            f"  build.toml pins   {manifest.commit}\n"
            f"  tag {manifest.tag} is now {head}\n\n"
            "  The upstream tag moved. Verify the change is intended, then update\n"
            "  `commit` in build.toml. Porthole will not silently build different\n"
            "  code than it did last week."
        )

    applied = _apply_patches(runtime_id, manifest, dest) if not reused else []

    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    return FetchResult(
        runtime=runtime_id, path=dest, commit=head, tag=manifest.tag,
        reused=reused, patches_applied=applied, size_bytes=size,
    )


def _apply_patches(runtime_id: str, manifest: BuildManifest, dest: Path) -> list[str]:
    if not manifest.patches:
        return []
    patch_dir = registry.repo_root() / "runtimes" / runtime_id / "patches"
    applied = []
    for name in manifest.patches:
        path = patch_dir / name
        if not path.is_file():
            raise FetchError(f"patch '{name}' not found in {patch_dir}")
        proc = subprocess.run(
            ["git", "apply", "--check", str(path)],
            cwd=dest, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FetchError(
                f"patch '{name}' does not apply to {manifest.tag}:\n"
                f"{(proc.stderr or proc.stdout).strip()}\n\n"
                "  The upstream moved under the patch. Rebase it, or drop it if\n"
                "  upstream has taken the change."
            )
        _git(["apply", str(path)], cwd=dest, what=f"applying {name}")
        applied.append(name)
    return applied


# ───────────────────────────────── inspection ─────────────────────────────────

@dataclass
class ProbeResult:
    """What a fetched source needs before it can be cross-compiled."""

    runtime: str
    has_cmake: bool
    declared_deps: list[Dependency]
    missing_tools: list[str]
    notes: list[str]


def probe(runtime_id: str) -> ProbeResult:
    """Report what stands between a fetched source and an iOS build.

    Deliberately not a build. Running CMake's configure step against a large engine
    needs its whole dependency tree present, and finding out *which* pieces are
    missing is more useful than a wall of configure errors.
    """
    manifest = BuildManifest.load(runtime_id)
    dest = source_dir(runtime_id)
    if not dest.is_dir():
        raise FetchError(f"'{runtime_id}' is not fetched. Run: porthole fetch {runtime_id}")

    notes: list[str] = []
    has_cmake = (dest / "CMakeLists.txt").is_file()
    if not has_cmake and manifest.system == "cmake":
        notes.append("build.toml says cmake, but there is no CMakeLists.txt at the root")

    missing = [t for t in ("cmake", "ninja") if shutil.which(t) is None]

    if manifest.adapter:
        adapter = registry.repo_root() / "runtimes" / runtime_id / manifest.adapter
        if not adapter.is_file():
            notes.append(
                f"the RuntimeHost adapter ({manifest.adapter}) has not been written yet"
            )

    # An upstream iOS platform file is the single most useful thing to know: it
    # usually means the dependency tree is already solved and the only real work is
    # the RuntimeHost adapter. Checking this first would have saved writing a wrong
    # dependency list for DevilutionX.
    ios_files = [
        p for p in dest.rglob("*ios*")
        if p.is_file() and p.suffix in {".cmake", ".txt"} and ".git" not in p.parts
    ]
    for f in ios_files[:4]:
        notes.append(f"upstream already has {f.relative_to(dest)} — read it first")

    vendored = dest / "3rdParty"
    if vendored.is_dir():
        count = len([p for p in vendored.iterdir() if p.is_dir()])
        notes.append(
            f"{count} dependencies are vendored under 3rdParty/ and built by the "
            "project itself — probably no separate cross-compiles needed")

    if (dest / "CMakeLists.txt").is_file():
        text = (dest / "CMakeLists.txt").read_text(errors="replace")
        if "FetchContent" in text:
            notes.append("fetches some dependencies at configure time (FetchContent)")

    return ProbeResult(
        runtime=runtime_id,
        has_cmake=has_cmake,
        declared_deps=manifest.dependencies,
        missing_tools=missing,
        notes=notes,
    )
