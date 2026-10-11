#!/usr/bin/env bash
#
# Run the test suite the way the Linux CI job sees it.
#
# The suite skips anything needing macOS developer tooling (security, codesign,
# xcrun), but a test that forgets the `macos` marker fails on Linux and passes here --
# which has now caught me out once. This builds a PATH containing the ordinary
# cross-platform tools and *not* /usr/bin, since on macOS /usr/bin is where security,
# codesign and xcrun live.
#
#   ./tools/linux-sim.sh
#
set -uo pipefail
cd "$(dirname "$0")/.."

PY="$(command -v python3)"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT

for tool in git openssl cmake sh bash env; do
  src="$(command -v "$tool" 2>/dev/null)" && ln -sf "$src" "$SIM/$tool"
done

echo "simulating the Linux job (no security/codesign/xcrun on PATH)"
env PATH="$SIM" "$PY" -m pytest tests/ -q -rs
