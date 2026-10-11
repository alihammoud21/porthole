"""Shared test fixtures and platform guards.

Most of this project is pure Python that runs anywhere, but the signing and device
code shells out to macOS-only tools (`security`, `xcrun`, `codesign`). CI runs the
suite on both Linux and macOS, so those tests need to skip rather than fail — and a
shared marker is harder to forget than a per-test `skipif`.
"""

import shutil

import pytest

# Tools whose absence means a whole class of test cannot run.
MACOS_TOOLS = ("security", "xcrun", "codesign")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "macos: requires macOS developer tooling (security/xcrun/codesign)")


def pytest_collection_modifyitems(config, items):
    missing = [t for t in MACOS_TOOLS if shutil.which(t) is None]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"needs macOS tooling (missing: {', '.join(missing)})")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip)
