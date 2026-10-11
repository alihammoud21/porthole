#!/usr/bin/env python3
"""Run the native Swift verification harnesses.

These cover what Python tests cannot: that the shell's own types behave correctly.
Both run natively on macOS, so no device or simulator is involved.

  layoutcheck  every layout compiles from TOML, decodes with the production Swift
               model, and places every visible control on screen
  seedcheck    re-signing the app refreshes build output while preserving the user's
               imported assets and saves

    python3 tools/verify-swift.py [layouts|seed]

Exits 0 with a note where there is no Swift toolchain, so Linux CI still passes.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from porthole import build, registry  # noqa: E402

SHELL = pathlib.Path("shell/Sources")

HARNESSES = {
    "layouts": {
        "harness": "tools/layoutcheck/main.swift",
        "sources": [SHELL / "Layout/Layout.swift"],
        "needs_layouts": True,
    },
    "seed": {
        "harness": "tools/seedcheck/main.swift",
        "sources": [
            SHELL / "Layout/Layout.swift",
            SHELL / "App/InstalledGame.swift",
            SHELL / "App/LibrarySeeder.swift",
        ],
        "needs_layouts": False,
    },
}


def run_one(name: str, spec: dict, root: pathlib.Path) -> int:
    harness = root / spec["harness"]
    sources = [root / s for s in spec["sources"]]

    for f in [harness, *sources]:
        if not f.is_file():
            print(f"  missing {f.relative_to(root)}")
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)

        if spec["needs_layouts"]:
            layouts = tmpdir / "layouts"
            layouts.mkdir()
            for lid in sorted(registry.layouts()):
                try:
                    data = build.compile_layout(lid)
                except build.BuildError as e:
                    print(f"  fail  {lid}: {e}")
                    return 1
                (layouts / f"{lid}.json").write_text(json.dumps(data, indent=2))

        # Not `name`: the layouts harness also creates a "layouts" directory here.
        binary = tmpdir / f"_verify-{name}"
        compile_proc = subprocess.run(
            ["swiftc", "-swift-version", "5", "-O",
             *[str(s) for s in sources], str(harness), "-o", str(binary)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            print(f"  could not compile the {name} verifier:")
            print(compile_proc.stderr.strip())
            return 1

        proc = subprocess.run([str(binary)], capture_output=True, text=True, cwd=tmp)
        print(proc.stdout.rstrip())
        if proc.stderr.strip():
            print(proc.stderr.rstrip())
        return proc.returncode


def main() -> int:
    if shutil.which("swiftc") is None:
        print("no swiftc on this machine — skipping the Swift verification harnesses")
        return 0

    root = registry.repo_root()
    wanted = sys.argv[1:] or list(HARNESSES)

    failed = 0
    for name in wanted:
        if name not in HARNESSES:
            print(f"unknown harness '{name}'; choose from: {', '.join(HARNESSES)}")
            return 2
        print(f"\n{name}:")
        failed += 1 if run_one(name, HARNESSES[name], root) else 0

    print()
    if failed:
        print(f"{failed} harness(es) failed")
        return 1
    print(f"{len(wanted)} harness(es) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
