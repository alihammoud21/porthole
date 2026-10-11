# The iOS shell

Not written yet. This directory is where the Swift app will live, and this file is the
design it will be built against so the design can be reviewed before the code exists.

Architecture context: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
Licensed GPL-3.0-or-later, because it links GPL engines — see
[../COPYING.md](../COPYING.md).

## What it is

A Swift app whose only job is to be a good host for a C or C++ game engine. It renders
touch controls, routes input, imports game files, manages saves, and gets out of the
way.

It is deliberately *not* where game-specific logic lives. Everything game-specific is
data: a recipe and a layout, both loaded at runtime.

## Planned structure

```
shell/
├── PortholeShell.xcodeproj
├── Sources/
│   ├── App/              entry point, library view, settings
│   ├── Session/          GameSession — one running game
│   ├── Runtime/          RuntimeHost C ABI bridge
│   ├── Input/            TouchControls, InputRouter, GameController
│   ├── Importer/         Files, AirDrop, iCloud, LAN handoff
│   ├── Saves/            iCloud sync, export, desktop import
│   └── Layout/           layout TOML parsing and the in-app editor
├── Runtimes/             static libs produced by `porthole build`
└── Resources/
```

## Design commitments

**Thin app.** Game assets live in the app's Documents directory, never in the signed
bundle. This keeps re-signing fast, keeps saves alive across re-signs, and sidesteps
bundle size limits. It's the single most consequential decision in the design — see
[ARCHITECTURE](../docs/ARCHITECTURE.md#thin-app-assets-on-device).

**Library mode by default.** One app hosting many games, because a free Apple developer
account allows only three app IDs. `--mode standalone` exists for people with a paid
account who want a real icon per game.

**Layouts are data.** The shell parses layout TOML at runtime and renders from it. No
recompile to move a button, and the in-app editor can write a layout back out as TOML
for a pull request.

**One runtime interface.** The shell talks to every engine through the same C ABI, so
it never knows whether it's driving a SNES core or OpenMW.

**No third-party dependencies** without discussion. SDL3, MoltenVK, and ANGLE come in
as part of runtime builds, not as shell dependencies.

**Graceful degradation.** Detect JIT at launch and pick the fast path when it exists;
always ship the interpreter fallback. Slow beats absent.

## Order of work

Tracked in [../docs/ROADMAP.md](../docs/ROADMAP.md). The first milestone is narrow on
purpose — **Diablo, end to end, on a real phone** — because DevilutionX already builds
for iOS, needs no JIT, is permissively licensed, and has a small dependency tree.
Nothing in that path is load-bearing on an unsolved problem.

1. Xcode project skeleton + Metal surface via SDL3
2. `RuntimeHost` ABI, with the DevilutionX adapter as the reference implementation
3. Touch control renderer reading layout TOML
4. Asset importer (Files app first, LAN handoff second)
5. Library view and game session lifecycle
6. Save management
7. The in-app layout editor

## Open questions

Genuinely unresolved, and good things to argue about in an issue:

- **Dual-screen DS layouts.** Stacked wastes space, side-by-side is tiny, picture-in-
  picture is fiddly. No good answer yet.
- **Background suspension.** iOS will kill the app for memory; engines from 2002 don't
  expect to be suspended mid-frame. How much state to snapshot, and when?
- **Save-state compatibility** across runtime version bumps. Pin per-game, or migrate?
- **Audio latency** versus underrun safety on a device that aggressively throttles.
- **Whether the layout editor belongs in the shipping app** or in a companion tool.
