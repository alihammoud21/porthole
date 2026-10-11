# Writing a recipe

A recipe is one TOML file that teaches Porthole about one game. It needs no Swift, no
C++, no Apple developer account, and no Mac — and it's the highest-leverage
contribution to this project.

If you own a game and know what its files look like, you can write one in about twenty
minutes.

## The minimum

```toml
schema = 1
id = "diablo"                    # stable slug, matches the filename
title = "Diablo"                 # as printed on the box
year = 1996
runtime = "devilutionx"          # must exist in runtimes/registry.toml
tier = 1                         # 1 native · 2 emulated · 3 interpreted · 4 translation
status = "supported"             # see below
layout = "isometric-touch"       # must exist in layouts/

[detect]
require = ["diabdat.mpq"]        # ALL of these must be present
any = ["hellfire.mpq"]           # optional; raises confidence

[assets]
target = "."                     # where files land in the app container
include = ["*.mpq"]
```

Validate it:

```bash
python3 -m porthole validate
python3 -m porthole scan ~/path/to/your/copy
```

## Detection

Three matching modes, all case-insensitive:

**Basename** — a pattern with no slash matches any file or directory *name* at any
depth. `"diabdat.mpq"` finds it wherever it lives.

**Path suffix** — a pattern containing a slash matches the end of a relative path.
`"data/g1.dat"` matches `RCT2/Data/g1.dat` but not `Data/other/g1.dat`.

**Glob** — `*` and `?` work in either mode. `"data/*.phd"` is how Tomb Raider is found.

Directories count as names, which is how Theme Hospital is detected — it has no single
distinctive file, but `DATA` + `LEVELS` + `ANIMS` together are decisive.

### Fields

| Field | Effect |
|---|---|
| `require` | every pattern must match, or the recipe doesn't fire |
| `any` | optional patterns; each one found adds confidence |
| `require_count` | require at least N matches from `any` |
| `min_bytes` | total directory size floor — rejects demos and empty shells |
| `root_hint` | subdirectory users commonly point at, shown in error messages |

### Getting it right

**Pick signature files that are distinctive and mandatory.** `morrowind.esm` is perfect:
nothing else is named that, and Morrowind cannot run without it. `data.pak` is poor on
its own — a dozen games ship one — which is why Arx Fatalis pairs it with `loc.pak`.

**Two `require` entries is the sweet spot.** One is often ambiguous; five fails on
legitimate variant releases.

**Set `min_bytes` when demos exist.** Morrowind's floor of 700 MB rejects the demo,
which has the same filenames.

**Don't hash.** Hashes are only for distinguishing *versions* when a recipe genuinely
needs to, and whole-file hashing of a 2 GB archive to learn what the filename already
told us is wasteful. Scanning stays fast because it never does this.

## Status, honestly

`status` is a promise to the next person. Please don't inflate it.

| Status | Means |
|---|---|
| `supported` | someone built it, ran it on a real iPhone, and played it |
| `partial` | runs, with caveats that are written down in `[notes]` |
| `experimental` | boots; may be unplayable |
| `planned` | recipe written, runtime not ported yet. **The honest default.** |
| `blocked` | can't proceed — upstream gone, DRM, legal. Say why in `[notes]`. |

A recipe at `planned` is still valuable: `scan` identifies the game and tells the user
what's missing, which is far better than silence.

## Performance expectations

```toml
[expect]
a17 = "60fps, high settings"
a15 = "60fps, medium view distance"
a13 = "40-50fps, reduced view distance"
jit = "none"                     # none | helps | required
```

Write what you measured, not what you hope. `porthole plan` shows these before anyone
spends an hour on a build, and that's the whole point of the field.

## Notes and caveats

The most-read part of any recipe. Put the thing you wish you'd known here.

```toml
[notes]
caveats = [
  "Hellfire expansion is detected automatically if its MPQs are present.",
  "Shadows are the first thing to turn off on A13/A14.",
  "Mods work — drop them in Data Files and they are picked up as on desktop.",
]
```

## Family recipes

For a runtime that handles a whole class of game rather than one title — ScummVM, DOS,
Godot, console ROMs:

```toml
family = true
confidence = "low"               # optional: never outranks a specific recipe
```

Console ROMs use an extension table instead of patterns:

```toml
[detect.ext]
".sfc" = { core = "core.snes9x", platform = "SNES" }
".iso" = { core = "core.pcsx_rearmed", platform = "PlayStation", ambiguous = true }
```

Mark `ambiguous = true` where an extension is weak evidence. `.iso` could be anything,
so Porthole asks instead of guessing.

## The hard rule

**Never commit game assets.** Not a ROM, not a WAD, not "just a small test file."
Recipes describe files by name; they never contain them. CI rejects binaries in
`recipes/`, and a PR that adds game data will be closed rather than amended.

If you need a fixture for testing, generate an empty sparse file with the right name —
that's how this repo's own test fixtures work.

## Checklist

- [ ] `python3 -m porthole validate` passes
- [ ] `python3 -m porthole scan` finds your actual copy
- [ ] `status` reflects what you personally verified
- [ ] `[notes] caveats` has at least one useful entry
- [ ] no game data in the diff
