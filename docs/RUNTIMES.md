# Porting a runtime

The hard, valuable work. One runtime port unlocks every game that runs on it — porting
ScummVM brings several hundred titles at once.

## The registry

`runtimes/registry.toml` is the source of truth. Each entry declares upstream, a pinned
version, license, iOS readiness, JIT needs, and graphics API.

```toml
[devilutionx]
name = "DevilutionX"
tier = 1
upstream = "https://github.com/diasurgical/DevilutionX"
version = "1.5.4"
license = "Unlicense"
ios = "ready"        # ready | wip | planned
jit = "none"         # none | helps | required
gfx = "metal"        # metal | gles | vulkan | software
plays = ["Diablo", "Diablo: Hellfire"]
```

**Pin to a tag, never a branch.** `version = "main"` is acceptable only while a port is
`planned` or `wip`; CI flags it once a runtime claims `ios = "ready"`. Reproducible
builds matter more here than freshness, because the thing being built is someone's
ability to play a game they own.

## The RuntimeHost interface

Every runtime is adapted to one C ABI so the shell doesn't care what it's driving:

```c
typedef struct ph_runtime ph_runtime;

ph_runtime *ph_open(const ph_config *cfg);
void        ph_frame(ph_runtime *, const ph_input *, ph_video *, ph_audio *);
bool        ph_save_state(ph_runtime *, ph_blob *out);
bool        ph_load_state(ph_runtime *, const ph_blob *);
void        ph_close(ph_runtime *);
```

`ph_config` carries the asset root, the save directory, and recipe-declared options.

### libretro cores

Nearly free. libretro already *is* approximately this interface, so the shim is a thin
translation layer and adding a core is mostly registry work plus a cross-compile.

### Native engines

Where the real effort lives. Engines written for desktop expect to own `main()`, the
event loop, and the window, and have to be persuaded otherwise. Typical work:

1. **Cross-compile for `arm64-apple-ios`** — usually a CMake toolchain file, plus
   hunting down dependencies that assume a desktop (SDL, zlib, Lua, Boost, OSG).
2. **Invert control of the main loop.** Either drive the engine one frame at a time, or
   run it on its own thread and marshal input and framebuffers across. Per-engine.
3. **Replace file I/O roots** with the app container's sandboxed paths. iOS has no
   `/usr/share`, and the bundle is read-only.
4. **Route input** from `ph_input` to whatever the engine expects — SDL events, raw
   scancodes, engine-specific action enums.
5. **Graphics.** Nothing here speaks Metal: SDL3's Metal renderer for 2D, MoltenVK for
   Vulkan, ANGLE for GL ES and for conservative desktop GL.
6. **Audio** through the SDL3 or CoreAudio backend. Watch buffer sizes; iOS is stricter
   about underruns than any desktop.
7. **Lifecycle.** Backgrounding must suspend cleanly, and iOS will kill you for
   memory. Plan for both.

Keep patches in `runtimes/<id>/patches/` as numbered series. Upstream them where they
make sense — a patch carried forever is a maintenance debt, and most of these projects
welcome platform support.

## Memory

The constraint people underestimate. iOS kills apps that use too much, with no warning
and no recoverable error. A 3 GB asset set must stream, not load — and an engine written
in 2002 for a machine with 256 MB often loads everything up front, which ironically
helps.

## JIT

Declare it honestly in the registry:

- `none` — interpreter or native code only. Works everywhere.
- `helps` — runs without, materially faster with. Ship both paths.
- `required` — unplayable without. Say so loudly; `porthole plan` surfaces it before
  anyone wastes a build.

Always ship the interpreter fallback. "Slow" is a worse outcome than "fast" but a far
better one than "doesn't run on your phone."

## Licensing

Declare the license. If a runtime is GPL, the shell linking it is GPL — that's already
true of this project, but a new runtime with an unexpected license (non-commercial
clauses on Snes9x, Genesis Plus GX, FBNeo; the BUILD engine's own terms) changes what
can be redistributed and must be recorded.

`porthole build` prints every license it pulls in and writes an attribution manifest
into the bundle.

## Contested upstreams

Some reimplementations were produced by decompiling shipped binaries and are legally
contested. Set `vendor = false`: Porthole references them by URL and the user fetches
them. We do not mirror, fork-for-safekeeping, or route around takedowns. See
[LEGAL.md](LEGAL.md#contested-upstreams).

## Good first ports

Ordered by value-per-effort:

1. **ScummVM** — already has upstream iOS support. Hundreds of games. Start here.
2. **VCMI** — upstream iOS target exists; Heroes III is an ideal phone game.
3. **DevilutionX** — upstream iOS support, tiny dependency tree.
4. **GZDoom** — unlocks Doom plus thirty years of mods.
5. **Godot export template** — `.pck` plus the stock template is already an app.
6. **libretro host + the 2D cores** — one shim, a dozen consoles.
