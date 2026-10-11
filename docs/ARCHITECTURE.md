# Architecture

## The shape of the problem

"Put any game on an iPhone" is not one problem. It's four, and they share almost no
implementation:

1. A game whose engine has been reimplemented as open source → compile the engine, feed
   it your assets.
2. A game that ran on console hardware → emulate the hardware, feed it your ROM.
3. A game that was always data for an interpreter → ship the interpreter.
4. An arbitrary x86 Windows binary → translate instructions and syscalls at runtime.

A single monolithic converter would be the wrong shape. Porthole is instead a **thin
pipeline over a registry of runtimes**, where each runtime knows how to play one class
of game, and recipes map a specific game onto a runtime.

Adding support for a new game should mean writing a TOML file. Adding support for a new
*class* of game means porting one runtime. That ratio is the whole architecture.

## Pipeline

```
scan ──► plan ──► build ──► sign ──► install
 │        │         │         │         │
 │        │         │         │         └─ ios-deploy / SideStore / TrollStore
 │        │         │         └─ codesign with the user's own certificate
 │        │         └─ cross-compile runtime, generate shell, stage assets
 │        └─ resolve runtime + layout, report honest expectations
 └─ walk a directory, match against recipes
```

### scan

Walks a directory, builds a set of relative paths, and evaluates every recipe's
`[detect]` block against it. Detection is deliberately boring: case-insensitive glob
matching on filenames, plus optional size floors and content hashes.

It does **not** hash whole multi-gigabyte files by default — matching on
`morrowind.esm` + `morrowind.bsa` is already decisive. Hashes exist in recipes to
distinguish *versions* (CD vs. GOG vs. Steam) when a recipe cares, and are checked
only when cheap or explicitly requested.

Multiple matches are possible and fine — a Steam directory might contain three
recognizable games. `scan` reports all of them, ranked by match confidence.

### plan

Resolves the recipe to a concrete runtime version and touch layout, then reports what
the user is actually in for: expected frame rate by device generation, whether JIT is
required, known caveats, and asset size. The goal is that nobody spends 40 minutes
building something that was never going to be playable on their phone.

`plan` is a pure function of (recipe, runtime registry, target device). No side effects.

### build

1. Resolve the runtime from `runtimes/registry.toml` — pinned to a specific upstream
   commit, never a moving branch.
2. Fetch and cross-compile for `arm64-apple-ios`, with the runtime's declared patch set
   applied. Artifacts are cached by `(runtime, version, patchset)` hash so the second
   build is fast.
3. Generate the shell: an Xcode project embedding the runtime as a static library,
   the recipe, and the resolved touch layout.
4. Stage assets. In the default thin-app mode this writes an *import manifest*, not the
   assets themselves — the app pulls them on-device.
5. Emit either an `.xcodeproj` (for people who want to open it in Xcode) or an unsigned
   `.ipa`.

### sign / install

Porthole does not have a signing identity and never will. It shells out to the user's
own: `codesign` with a certificate from their Apple ID, or hands the unsigned `.ipa`
to SideStore/AltStore/TrollStore. The signing path is a user choice, documented in
[INSTALLING.md](INSTALLING.md), and `porthole doctor` reports which ones are available
on the current machine.

## The shell

A Swift app whose job is to be a good host for a C/C++ game engine.

```
┌─────────────────────────────────────────────┐
│ PortholeShell (Swift / SwiftUI)             │
│                                             │
│  Library        Importer      Settings      │
│  ───────        ────────      ────────      │
│  installed      Files,        per-game      │
│  games,         AirDrop,      runtime       │
│  per-game       iCloud,       options       │
│  launch         local HTTP                  │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ GameSession                           │  │
│  │                                       │  │
│  │  TouchControls ──┐                    │  │
│  │  GameController ─┼─► InputRouter      │  │
│  │  Keyboard ───────┘        │           │  │
│  │                           ▼           │  │
│  │              ┌────────────────────┐   │  │
│  │              │ RuntimeHost (C API)│   │  │
│  │              └────────┬───────────┘   │  │
│  │                       ▼               │  │
│  │       libretro core │ OpenMW │ ...    │  │
│  │                       │               │  │
│  │              Metal via SDL3/MoltenVK  │  │
│  └───────────────────────────────────────┘  │
│  SaveManager ──► iCloud / Files             │
└─────────────────────────────────────────────┘
```

### RuntimeHost

One C ABI that every runtime is adapted to, so the shell doesn't know or care whether
it's driving a SNES core or OpenMW:

```c
typedef struct ph_runtime ph_runtime;

ph_runtime *ph_open(const ph_config *cfg);   // asset root, options, save dir
void        ph_frame(ph_runtime *, const ph_input *, ph_video *, ph_audio *);
bool        ph_save_state(ph_runtime *, ph_blob *out);   // optional
bool        ph_load_state(ph_runtime *, const ph_blob *);
void        ph_close(ph_runtime *);
```

libretro cores get a thin shim (libretro already *is* approximately this interface).
Native engines get a per-engine adapter, which is where most of the per-runtime work
actually lives — engines expect to own `main()`, the event loop, and the window, and
have to be convinced otherwise.

### Rendering

Nothing here speaks Metal natively. The translation stack:

- **SDL3** for window, input plumbing, and audio, with its Metal renderer for 2D.
- **MoltenVK** for anything Vulkan (OpenMW's new renderer, vkQuake).
- **ANGLE** for OpenGL ES, and for desktop GL where the engine's usage is conservative
  enough to survive translation.

Runtimes declare their graphics requirement in the registry, because it determines
device floor more than CPU does.

### Input routing

`InputRouter` merges touch overlay, MFi controller, and hardware keyboard into one
abstract input state, then maps it through the recipe's layout to whatever the runtime
expects (libretro button IDs, SDL scancodes, engine-specific actions).

The indirection matters: it means a touch layout is portable across runtimes, and a
controller works on a game that predates controllers.

## Why not these alternatives

**One mega-app with everything compiled in.** A single 800 MB binary containing every
engine. Rejected: absurd build times, pulls incompatible licenses into one object, and
one broken runtime breaks every game.

**Fat bundles with assets inside the `.ipa`.** Simpler, and genuinely nicer for small
games — so it's available as `--mode fat` for anything under ~500 MB. But it cannot be
the default: it makes the 7-day re-signing ritual unbearable and destroys saves on
reinstall.

**A GUI app instead of a CLI.** A GUI is coming, but the CLI is the engine and ships
first — it's scriptable, diffable, testable in CI, and doesn't need a Mac app to exist
before anything works.

**Web-based, run games in Safari via WASM.** Real option for Tier 3, genuinely clever,
and completely blocked for Tier 1/2 by performance and by iOS Safari's storage limits.

## Repository invariants

These are enforced in CI, not merely requested:

1. No game assets, ROMs, or copyrighted data in the repository. Ever.
2. No code that downloads game assets from third parties.
3. No DRM circumvention.
4. Every runtime in the registry is pinned to a commit hash and declares its license.
5. Every recipe declares its tier and status honestly. "Works" means someone ran it.
