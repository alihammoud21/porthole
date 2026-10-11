# Legal posture

*Not legal advice. This is the project's reasoning about its own design, written so
contributors understand where the lines are and why they're drawn there.*

## The one-sentence version

Porthole copies games you already own onto hardware you already own, using engines that
are open source, and it never possesses, distributes, or helps you obtain anyone's
copyrighted game data.

## Why bring-your-own-files isn't a loophole

It's the actual legal basis, and it's a well-trodden one. An entire category of
long-lived, publicly developed software works exactly this way:

| Project | Ships | Requires you to own |
|---|---|---|
| ScummVM | interpreter | the adventure game |
| DOSBox | DOS emulator | the DOS game |
| OpenMW | engine | Morrowind |
| DevilutionX | engine | Diablo |
| OpenRCT2 | engine | RollerCoaster Tycoon 2 |
| GZDoom | engine | a Doom IWAD |
| OpenXcom | engine | X-COM |

Some of these are 20+ years old, widely distributed in Linux distributions, and have
never been successfully challenged. The separation is clean: **the engine is new work;
the assets stay yours.**

Porthole is a packaging layer over this established pattern. It does not weaken the
separation — it's architecturally incapable of shipping assets, because there is no
asset path in the build system that originates anywhere but the user's own disk.

## What the case law actually says

**Emulation is lawful.** *Sony v. Connectix* (9th Cir. 2000) and *Sony v. Bleem* (9th
Cir. 2000) both held that writing an emulator for someone else's console is legitimate,
including the intermediate copying required to reverse-engineer it. Emulators are not a
grey area in the United States; they are a decided question.

**Clean-room reimplementation is lawful.** *Sega v. Accolade* (9th Cir. 1992) and the
API side of *Google v. Oracle* (U.S. 2021) support reimplementing an interface or engine
without copying its expression. Projects like OpenMW read data files and reproduce
behavior; they don't contain the original code.

**Format-shifting your own copy** is the most defensible act in the pipeline, and it's
the only thing Porthole actually does with your data.

**Distributing games you don't own is straightforwardly infringement.** So Porthole
doesn't, can't, and won't.

## Where the real danger is: DMCA §1201

Copyright infringement is one risk. Circumventing technical protection measures is a
*separate* and in some ways nastier one — §1201 creates liability even where the
underlying use would be fair.

So Porthole has a hard rule: **if you can't already read the files, Porthole can't help
you.**

- No DRM stripping. Not Denuvo, not SecuROM, not Steam's DRM wrapper, not disc-check
  circumvention.
- No decryption of encrypted console media or firmware.
- No bundled console BIOS or firmware images, which are copyrighted and not ours. A
  recipe may tell you a BIOS is required and how to dump it from your own hardware.
  It will never contain one.
- No key extraction, no circumvention tooling, no "just paste your keys here" field.

A game that installs to a readable directory on your disk — GOG, most Steam titles,
old CDs — is in scope. A game that only exists as an encrypted blob is not, and a PR
that changes that gets closed.

## Contested upstreams

Some engine reimplementations are legally contested, usually because they were produced
by decompiling a shipped binary rather than by clean-room reverse engineering. Nintendo
in particular has filed DMCA takedowns against decompilation projects, and a few have
been removed from public hosting.

Porthole's policy, encoded in the recipe schema as `vendor = false`:

- **Never vendor, mirror, or redistribute contested source.** No forks "just in case,"
  no copies in CI caches.
- **A recipe may reference a contested upstream by URL**, with its status marked
  honestly, so the user fetches it themselves if they choose.
- **If an upstream is taken down, the recipe is marked `status = "blocked"`** and left
  as documentation. We don't route around takedowns.

This costs the project some headline games. That's the correct trade.

## Trademarks

Game names appear in recipes and documentation as factual identification — the
nominative use that lets a compatibility list exist at all. Porthole does not use any
publisher's logos, box art, fonts, or trade dress, and does not name itself or its
builds after anyone's property. Generated app icons are generic or user-supplied.

## Licensing consequences

Most of the best engines are GPL. That has two concrete effects on this project:

1. **The shell is GPL-3.0**, because it links them. The CLI and tooling stay MIT since
   they only orchestrate processes.
2. **App Store distribution is impossible**, independent of Apple's content rules. The
   GPL's anti-DRM and anti-additional-restriction terms are incompatible with the App
   Store's signing and distribution model — a long-settled incompatibility, most
   famously when GNU Go was pulled in 2010.

This is a sideloading tool because it has to be, not merely because Apple might object.

Every runtime declares its license in `runtimes/registry.toml`. `porthole build` prints
the licenses it's pulling in and writes an attribution manifest into the bundle, so GPL
compliance is a build output rather than an afterthought.

## Privacy

Scanning happens entirely on your machine. There is no telemetry, no analytics, no
crash reporting that includes file paths or game identities, and no server for any of
it to go to. Which games you own is not information this project collects.

## Pull requests that will be closed

Stated plainly so nobody wastes an afternoon:

- Downloading game assets, ROMs, or ISOs from anywhere
- Links to, search of, or integration with ROM sites or trackers
- DRM circumvention, key extraction, or decryption of protected media
- Bundled BIOS, firmware, or copyrighted game data of any kind
- Vendoring contested decompilation source
- Anything using enterprise distribution certificates, which violates Apple's terms
  and gets certificates revoked for everyone

## If you're a rights holder

Open an issue or email the maintainers. Porthole contains no game assets, but if a
*recipe* — which is metadata: filenames, hashes, directory layout — nonetheless
concerns you, we'd genuinely rather talk than litigate. Recipes can be amended or
removed. See [SECURITY.md](../SECURITY.md) for contact.
