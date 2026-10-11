#!/usr/bin/env bash
#
# The repository invariants, in one place so CI and a developer run identical logic.
# Previously these lived inline in the workflow, which meant they could only fail
# after a push -- and they did, twice.
#
#   ./tools/ci-checks.sh
#
set -uo pipefail

fail=0
note() { printf '  %-6s %s\n' "$1" "$2"; }
err()  { note "FAIL" "$1"; fail=1; }
ok()   { note "ok" "$1"; }

cd "$(dirname "$0")/.."

echo "repository invariants:"

# ── 1. Metadata directories hold only metadata ──
BAD=$(git ls-files recipes/ layouts/ | grep -viE '\.(toml|md|json)$' || true)
if [ -n "$BAD" ]; then
  err "non-metadata files in recipes/ or layouts/:"
  echo "$BAD" | sed 's/^/         /'
else
  ok "recipes/ and layouts/ contain only metadata"
fi

# ── 2. runtimes/ holds metadata plus FIRST-PARTY source ──
# Upstream engine sources are fetched to .cache/sources/ and never vendored, so
# anything compiled here is ours. Build files and patch series are expected too.
BAD=$(git ls-files runtimes/ \
  | grep -viE '\.(toml|md|json|c|cpp|cc|h|hpp|cmake|patch|diff)$' || true)
if [ -n "$BAD" ]; then
  err "unexpected file types in runtimes/:"
  echo "$BAD" | sed 's/^/         /'
else
  ok "runtimes/ contains only metadata, source and patches"
fi

# ── 3. No vendored upstream engine source ──
# A fetched upstream must never be committed, however convenient it seems.
VENDORED=$(git ls-files 'runtimes/*/upstream/*' 'runtimes/*/_src/*' \
  '.cache/*' 2>/dev/null || true)
if [ -n "$VENDORED" ]; then
  err "vendored upstream source is committed:"
  echo "$VENDORED" | sed 's/^/         /'
else
  ok "no vendored upstream source"
fi

# ── 4. Nothing unexpectedly large ──
# This project's source is TOML, Python, Swift, C and Markdown. A big file is either
# game data or a mistake.
LARGE=$(git ls-files -z | xargs -0 -I{} \
  sh -c 'test -f "{}" && test "$(wc -c < "{}")" -gt 262144 && echo "{}"' || true)
if [ -n "$LARGE" ]; then
  err "files over 256 KB:"
  echo "$LARGE" | sed 's/^/         /'
else
  ok "no file over 256 KB"
fi

# ── 5. No game data, anywhere ──
# The project's central invariant. A violation here is more serious than any test
# failure, because it is what keeps Porthole legal to distribute.
ROMS=$(git ls-files | grep -iE \
  '\.(wad|mpq|grp|pak|pk3|rff|esm|esp|bsa|agg|lod|grf|gob|hog|rsdk|phd|res|iso|chd|cue|bin|nes|sfc|smc|gb|gbc|gba|n64|z64|nds|gdi|cso|pbp)$' \
  || true)
if [ -n "$ROMS" ]; then
  err "files with game-data extensions:"
  echo "$ROMS" | sed 's/^/         /'
else
  ok "no files with game-data extensions"
fi

# ── 6. No asset-acquisition code ──
# Closed-on-sight per docs/LEGAL.md; cheap to check mechanically.
SUSPECT=$(git grep -lniE \
  'download.*(rom|iso)|(rom|iso).*download|romsite|emuparadise|vimm|myrient' \
  -- 'porthole/*.py' 'shell/*' 'runtimes/*' 2>/dev/null || true)
if [ -n "$SUSPECT" ]; then
  err "possible asset-acquisition code (review by hand):"
  echo "$SUSPECT" | sed 's/^/         /'
else
  ok "no asset-acquisition code"
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "invariant check FAILED"
  exit 1
fi
echo "all invariants hold"
