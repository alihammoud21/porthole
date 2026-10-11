#!/usr/bin/env bash
#
# Everything CI runs, locally. Use this before pushing.
#
#   ./tools/check.sh
#
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
step() {
  echo
  echo "── $1 ──"
  shift
  "$@" || fail=1
}

step "Repository invariants" ./tools/ci-checks.sh
step "Reference integrity"   python3 -m porthole validate
step "Compatibility table"   python3 tools/gen-compat.py --check
step "Python tests"          python3 -m pytest tests/ -q
step "Linux-path tests"      ./tools/linux-sim.sh

if command -v xcrun >/dev/null 2>&1; then
  step "Swift harnesses"     python3 tools/verify-swift.py
  step "ABI header (C11)"    xcrun --sdk iphoneos clang -arch arm64 \
      -mios-version-min=15.0 -std=c11 -Wall -Wextra -Wno-unused-function -fsyntax-only \
      -x c include/porthole_runtime.h
  step "ABI header (C++17)"  xcrun --sdk iphoneos clang++ -arch arm64 \
      -mios-version-min=15.0 -std=c++17 -Wall -Wno-unused-function -fsyntax-only \
      -x c++ include/porthole_runtime.h
  echo
  echo "── Shell typecheck (arm64-apple-ios) ──"
  xcrun --sdk iphoneos swiftc -typecheck -swift-version 5 \
    -target arm64-apple-ios15.0 -sdk "$(xcrun --sdk iphoneos --show-sdk-path)" \
    -import-objc-header shell/Sources/Runtime/Porthole-Bridging-Header.h \
    -Iinclude $(find shell/Sources -name '*.swift' | sort) \
    && echo "  ok     shell typechecks" || fail=1
  step "Build selftest"      python3 -m porthole build selftest
else
  echo
  echo "── Xcode not present: skipping iOS checks ──"
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "FAILED — do not push"
  exit 1
fi
echo "all checks passed"
