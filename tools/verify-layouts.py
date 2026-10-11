#!/usr/bin/env python3
"""Compile every layout to JSON and decode it with the production Swift model.

This catches the class of bug that unit tests in Python cannot: a layout that parses
as TOML, serialises as JSON, and then fails to decode into the Swift struct the shell
actually uses -- or decodes fine and places a control off the edge of the screen.

Runs the check natively on macOS, so no device or simulator is needed.

    python3 tools/verify-layouts.py

Skips cleanly with exit 0 where there is no Swift toolchain, so Linux CI still passes.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from porthole import build, registry  # noqa: E402


def main() -> int:
    if shutil.which("swiftc") is None:
        print("no swiftc on this machine — skipping the Swift decode check")
        return 0

    root = registry.repo_root()
    model = root / "shell" / "Sources" / "Layout" / "Layout.swift"
    harness = root / "tools" / "layoutcheck" / "main.swift"
    for f in (model, harness):
        if not f.is_file():
            print(f"missing {f}")
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        layouts = tmpdir / "layouts"
        layouts.mkdir()

        for lid in sorted(registry.layouts()):
            try:
                data = build.compile_layout(lid)
            except build.BuildError as e:
                print(f"  fail  {lid}: {e}")
                return 1
            (layouts / f"{lid}.json").write_text(json.dumps(data, indent=2))

        binary = tmpdir / "layoutcheck"
        compile_proc = subprocess.run(
            ["swiftc", "-swift-version", "5", "-O",
             str(model), str(harness), "-o", str(binary)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            print("could not compile the verifier:")
            print(compile_proc.stderr.strip())
            return 1

        run = subprocess.run([str(binary)], capture_output=True, text=True, cwd=tmp)
        print(run.stdout.rstrip())
        if run.stderr.strip():
            print(run.stderr.rstrip())
        return run.returncode


if __name__ == "__main__":
    sys.exit(main())
