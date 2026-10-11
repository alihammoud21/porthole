# Roadmap

Honest about what exists. Today that's detection, planning, and a lot of design.

## Now — detection and data model

- [x] Recipe schema and loader
- [x] Runtime registry
- [x] Touch layout schema, 11 layouts
- [x] `scan` — name, path-suffix, glob, directory, and extension-table detection
- [x] `plan` — resolve runtime + layout, report expectations and blockers
- [x] `validate` — CI gate on dangling references and dishonest metadata
- [x] `doctor` — toolchain and signing-identity check
- [x] 27 recipes covering ~24 games plus 5 whole families

## Next — one game, end to end

The milestone that makes this real: **Diablo on an iPhone, start to finish.**

Chosen because DevilutionX already builds for iOS, is permissively licensed, has a tiny
dependency tree, needs no JIT, and runs on an A13 without complaint. Everything the
pipeline needs is exercised and nothing is load-bearing on unsolved problems.

- [ ] Cross-compile toolchain (`arm64-apple-ios`, CMake, artifact cache)
- [ ] `RuntimeHost` C ABI, with the DevilutionX adapter as the reference
- [ ] Shell skeleton: library view, game session, Metal surface via SDL3
- [ ] Touch control renderer that reads a layout TOML
- [ ] Asset importer — Files app + `porthole serve` LAN handoff
- [ ] `build` → Xcode project
- [ ] `sign` / `install` with a free Apple ID over USB
- [ ] `refresh` for the 7-day re-sign

## Then — breadth

- [ ] libretro host shim, then the no-JIT 2D cores (NES, SNES, GB/GBA, Genesis)
- [ ] ScummVM — the single biggest unlock in the project
- [ ] GZDoom, and PWAD/mod loading
- [ ] VCMI
- [ ] `--mode standalone`, per-game icons
- [ ] In-app layout editor with TOML export
- [ ] Save sync: iCloud, and import from a desktop install
- [ ] MFi controller support end to end
- [ ] JIT detection with automatic interpreter fallback

## Later

- [ ] DOSBox Staging
- [ ] Godot `.pck` and LÖVE `.love` paths
- [ ] OpenMW — the heaviest Tier 1 port, and the one most people will ask for
- [ ] A GUI for people who don't live in a terminal
- [ ] Android, once the shell abstraction holds
- [ ] Community recipe index, so recipes ship faster than releases

## Research — no promises

- [ ] Tier 4: Wine + box64 + DXVK on MoltenVK. Documented mostly so the next person
      doesn't have to rediscover why it's hard.
- [ ] Six-degrees-of-freedom touch controls that genuinely work. `sixdof` is playable
      and unsatisfying; this is an open invitation.
- [ ] Dual-screen layouts for DS that aren't a compromise.
- [ ] Shader-based upscaling that's worth the battery.

## Non-goals

Permanently out of scope, so nobody plans around them:

- Distributing, downloading, or helping locate game assets
- DRM circumvention of any kind
- App Store distribution (GPL-incompatible, and against the content rules)
- Enterprise certificates
- Modern AAA titles, anti-cheat, or live-service games
- Windows/Linux host support for the *build* tooling — signing needs a Mac. Recipes and
  layouts can be authored anywhere.

## How to help

The bottleneck is runtime ports, and the easiest useful contribution is a recipe.

- [Write a recipe](RECIPES.md) — 30 lines of TOML, no Mac needed
- [Add a touch layout](TOUCH-CONTROLS.md) — needs taste more than code
- [Port a runtime](RUNTIMES.md) — start with ScummVM
