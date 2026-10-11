# Contributing

Porthole is early. The architecture is settled, most of the implementation isn't, and
that means there's room to do substantial work rather than fill in gaps.

## The one rule

**Never commit game assets.** No ROMs, no WADs, no MPQs, no "small test file," no
"it's shareware so it's fine." Recipes describe files by name and hash; they never
contain them. CI rejects binaries under `recipes/`, and a PR carrying game data gets
closed rather than amended.

Need a fixture? Generate an empty sparse file with the right name — that's how this
repo's own tests work:

```python
with open("DOOM2.WAD", "wb") as f:
    f.truncate(14_000_000)      # 14 MB of nothing, zero bytes on disk
```

Also closed on sight, per [docs/LEGAL.md](docs/LEGAL.md):

- asset/ROM downloading, or links to places that host them
- DRM circumvention, key extraction, decryption of protected media
- bundled console BIOS or firmware
- vendored copies of contested decompilation source
- anything using enterprise distribution certificates

These aren't close calls, and the project's ability to exist depends on them.

## Where to start

Ranked by how useful it is versus how much it demands of you.

### Write a recipe — no Mac required

The highest-leverage contribution. Thirty lines of TOML teaching Porthole about a game
you own. No Swift, no C++, no Xcode, no Apple developer account.

→ [docs/RECIPES.md](docs/RECIPES.md)

### Add or improve a touch layout — needs taste, not a compiler

Making a mouse-driven 1998 strategy game playable with thumbs is a design problem.
Layouts are data; good ones come from someone who actually played the game.

→ [docs/TOUCH-CONTROLS.md](docs/TOUCH-CONTROLS.md)

### Port a runtime — the hard, valuable work

One port unlocks every game that runs on it. ScummVM alone is several hundred titles,
and it already has upstream iOS support.

→ [docs/RUNTIMES.md](docs/RUNTIMES.md)

### Build the pipeline

The current bottleneck. Cross-compile toolchain, the `RuntimeHost` ABI, the Swift
shell, signing and install. See [docs/ROADMAP.md](docs/ROADMAP.md) — the next milestone
is deliberately narrow: Diablo, end to end, on a real phone.

## Before you open a PR

```bash
python3 -m porthole validate       # every reference resolves, metadata is sane
python3 tools/gen-compat.py        # if you touched recipes/
python3 -m pytest tests/ -q        # if you touched porthole/
```

All three run in CI, so running them locally just saves you a round trip.

## Honest metadata

`status` on a recipe means something specific:

| Status | Means |
|---|---|
| `supported` | **you** built it, ran it on a real iPhone, and played it |
| `partial` | runs, with caveats written into `[notes] caveats` |
| `experimental` | boots; may be unplayable |
| `planned` | recipe written, runtime not ported. The correct default. |
| `blocked` | can't proceed. Say why. |

Same for `[expect]` — write what you measured on hardware you own, not what you hope.
`porthole plan` shows these numbers to someone deciding whether to spend an hour on a
build, and a cheerful guess wastes their evening.

`planned` is not a failure state. A `planned` recipe still lets `scan` identify the
game and tell the user exactly what's missing, which beats silence.

## Style

**Python** — standard library only in `porthole/`. It has to run anywhere with Python
3.11+, with no install step. Type hints on anything public. Four spaces, ~90 columns.

**TOML** — lowercase-kebab ids matching the filename. Comments explain *why* a
detection pattern was chosen, not what it does.

**Swift** (when the shell exists) — standard conventions, no third-party dependencies
in the shell without discussion.

**Prose** — the docs in this repo try to be specific and non-promotional. Say what
something costs and where it breaks. "Experimental" and "not solved" are allowed words;
it's better than discovering it yourself at 1am.

## Commits

Conventional-ish prefixes, because they make the changelog write itself:

```
recipe: add Heroes of Might and Magic III
layout: fix thumb reach on fps-twin-stick for SE-sized screens
runtime: cross-compile DevilutionX for arm64-ios
cli: handle truncated scans without lying about the result
docs: explain the JIT entitlement properly
```

## Reviews

Maintainers will push back hardest on two things: anything that risks the legal posture,
and metadata that overstates what works. Neither is personal — the first is existential
and the second is the only reason anyone can trust the compatibility table.

## Code of conduct

[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Short version: be decent, assume good faith,
and keep arguments about the work.
