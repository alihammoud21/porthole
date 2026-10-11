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

## Fetching an upstream

Runtimes with an upstream are **fetched, never vendored**. Sources land in
`.cache/sources/<id>/`, which is gitignored, and a CI invariant rejects any attempt to
commit them. That is partly disk hygiene and partly policy — the project promises never
to mirror contested decompilation source, and the cleanest way to keep that promise is
to have no mechanism for vendoring anything.

Each upstream runtime gets a `runtimes/<id>/build.toml`:

```toml
schema = 1
runtime = "devilutionx"

[source]
git = "https://github.com/diasurgical/DevilutionX"
tag = "1.5.4"
# Verified against the remote. A tag can be moved; a commit cannot.
commit = "9f30593b4c2e706d6d6a66edfbc3aa6ada8861b4"
submodules = true

[build]
system = "cmake"
targets = ["libdevilutionx"]
cmake_args = ["-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_ARCHITECTURES=arm64"]

[adapter]
source = "src/adapter.cpp"

[patches]
series = ["01-expose-framebuffer.patch"]
```

```bash
porthole fetch devilutionx    # clone at the pin, apply the patch series
porthole probe devilutionx    # report what still stands between it and a build
```

**Pinning is strict.** The fetch fails if the tag no longer resolves to the recorded
commit. Tags get moved; the thing being built is somebody's ability to play a game
they own, and refusing to build beats silently building different code than last week.

### Probe before you plan

`porthole probe` reads a fetched source and reports what it actually needs. Run it
before estimating anything.

It exists because of a mistake worth repeating as a warning. DevilutionX's manifest
originally declared SDL2, libsodium, bzip2 and zlib as dependencies Porthole would
have to cross-compile and make findable — a week of work. Reading the fetched source
showed that upstream already ships `CMake/platforms/ios.cmake`, which turns off every
`DEVILUTIONX_SYSTEM_*` flag and builds all twenty vendored dependencies itself. The
real remaining work is one adapter file.

Probe now reports upstream iOS platform files and vendored dependency directories
first, because those two signals collapse most of the apparent work.

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
