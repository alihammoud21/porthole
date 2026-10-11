# Roadmap

Honest about what exists. Today that's detection, planning, and a lot of design.

## Done — detection, data model, and the pipeline

- [x] Recipe schema and loader
- [x] Runtime registry
- [x] Touch layout schema, 11 layouts
- [x] `scan` — name, path-suffix, glob, directory, and extension-table detection
- [x] `plan` — resolve runtime + layout, report expectations and blockers
- [x] `validate` — CI gate on dangling references and dishonest metadata
- [x] `doctor` — toolchain and signing-identity check
- [x] 28 recipes covering ~24 games plus 5 whole families
- [x] `RuntimeHost` C ABI — seven symbols, dlopen-loaded, ABI-versioned
- [x] `selftest` reference runtime in C, exercising every part of the ABI
- [x] Cross-compile toolchain with artifact caching — no Xcode project involved
- [x] `build` — assembles a real `arm64-apple-ios` app bundle, verified in CI
- [x] `sign` — identity and provisioning-profile discovery, inside-out codesigning
- [x] `install` — device discovery and deploy via `devicectl`
- [x] iOS shell written and typechecking: Metal renderer (4 pixel formats incl.
      palettised), touch overlay, input router, lock-free audio ring buffer
- [x] Layouts compile TOML → JSON and decode with the production Swift model, checked
      in CI on real hardware-targeted builds

## Next — first frame on real hardware

Everything above is verified by compilation and by inspecting the artifacts. None of
it has drawn a pixel on a phone. That is the next milestone, and it is deliberately
the self-test runtime rather than a game:

- [x] `porthole bootstrap` — registers the app id and fetches a profile by generating
      a throwaway Xcode project, the one place a `.pbxproj` turned out to be
      unavoidable. Verified offline; the live run changes an Apple account, so it is
      opt-in rather than implicit.
- [ ] Run `selftest` on a device: test pattern visible, input lamps lighting, tone
      audible, save state round-tripping
- [ ] Seed-to-Documents copy on first launch
- [ ] `refresh` for the 7-day re-sign
- [x] `porthole serve` — LAN asset handoff, token-gated and read-only, with a
      fingerprint manifest so a truncated transfer is caught at import

Then the same pipeline with a real engine: **Diablo, start to finish.** DevilutionX
already builds for iOS, is permissively licensed, has a tiny dependency tree, needs no
JIT, and runs on an A13 without complaint.

- [x] Fetch-and-patch for runtimes with an upstream, with strict commit pinning
- [x] ~~SDL2 for iOS as a vendored dependency build~~ — not needed. DevilutionX
      builds all twenty of its dependencies itself; `porthole probe` found this
- [ ] DevilutionX adapter against `RuntimeHost`
- [ ] Asset verification against the recipe's declared layout at import time

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
