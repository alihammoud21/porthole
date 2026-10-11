# Licensing

Deliberately split, because linking GPL engines has consequences.

| Component | Path | License |
|---|---|---|
| CLI and tooling | `porthole/`, `tools/` | [MIT](LICENSE) |
| iOS shell | `shell/` | GPL-3.0-or-later |
| Recipes, layouts | `recipes/`, `layouts/` | CC0-1.0 |
| Documentation | `docs/`, `*.md` | CC0-1.0 |
| Bundled runtimes | fetched at build time | **their own** — see below |

## Why the split

**The CLI is MIT.** It orchestrates processes and reads TOML. It doesn't link anything
copyleft, so there's no reason to encumber it.

**The shell is GPL-3.0-or-later.** It statically links game engines, and most of the
good ones are GPL — OpenMW, GZDoom, ScummVM, OpenRCT2, Arx Libertatis, and more. The
shell is a derivative work of whatever it links, so GPL-3.0 is the honest label rather
than an ideological choice.

**Recipes and layouts are CC0.** A recipe is a set of facts: this game's files are
named these things, and this control layout works well for it. Facts about file layouts
shouldn't be owned by anyone, and putting them in the public domain means other
projects can use them freely.

## Runtime licenses

Every runtime declares its license in
[`runtimes/registry.toml`](runtimes/registry.toml). `porthole build` prints the license
of everything it pulls into a build and writes an attribution manifest into the app
bundle, so GPL compliance is a build output rather than something to remember.

Licenses in play across the registry include GPL-2.0, GPL-3.0, AGPL-3.0, LGPL-2.1,
MIT, MPL-2.0, Zlib, Unlicense, Ken Silverman's BUILD engine license, and
**non-commercial** terms on several emulator cores (Snes9x, Genesis Plus GX, FinalBurn
Neo) and on the Sonic Mania decompilation.

Those non-commercial clauses are the reason Porthole can't ship prebuilt binaries of
everything even in principle. Builds happen on your machine, from sources fetched on
your machine, for your own device.

## A consequence worth stating plainly

**Porthole cannot be distributed on the App Store.** The GPL forbids adding
restrictions beyond its own terms, and App Store distribution imposes exactly that
through its signing, DRM, and redistribution rules. This has been settled since GNU Go
was pulled from the store in 2010.

That's independent of Apple's content rules. Porthole is a sideloading tool because it
has to be. See [docs/INSTALLING.md](docs/INSTALLING.md).

## Trademarks

Game titles appear in recipes and documentation as factual identification — the
nominative use that lets a compatibility list exist. Porthole uses no publisher's
logos, box art, fonts, or trade dress, and generated app icons are generic or
user-supplied.
