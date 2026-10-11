## What this changes

<!-- One or two sentences. -->

## Type

- [ ] Recipe (new or updated game support)
- [ ] Touch layout
- [ ] Runtime port or registry change
- [ ] CLI / tooling
- [ ] Shell (iOS app)
- [ ] Documentation

## Checks

- [ ] `python3 -m porthole validate` passes
- [ ] `python3 -m pytest tests/ -q` passes
- [ ] `python3 tools/gen-compat.py` run, if recipes changed

## The hard rule

- [ ] **This diff contains no game assets, ROMs, or copyrighted game data**
- [ ] No code that downloads game assets from third parties
- [ ] No DRM circumvention, key extraction, or bundled BIOS/firmware
- [ ] No vendored copies of contested decompilation source

<!-- These aren't close calls — see docs/LEGAL.md. A PR carrying game data gets
     closed rather than amended. -->

## For recipes and layouts

- [ ] `status` reflects what I personally verified on hardware, not what I hope
- [ ] `[expect]` numbers were measured, not guessed
- [ ] `[notes] caveats` records the thing I wish I'd known

Device tested on: <!-- e.g. iPhone 13, iOS 26.1 — or "none, status is `planned`" -->
