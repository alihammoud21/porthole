# Getting a build onto your iPhone

Building the app is the easy half. Apple's code signing is the part that defeats
people, so this document is blunt about each path's real cost.

Every option below signs with **your own** certificate. Porthole has no signing
identity, ships no provisioning profiles, and will never use an enterprise
certificate — that violates Apple's terms and gets certificates revoked for everyone
sharing them.

Run `porthole doctor` first; it reports which of these are available on your machine.

## Decision guide

```
Do you have $99/yr for a developer account?
├── yes ──► Paid account. One year per signature. Stop reading.
└── no
    └── Is your iPhone on an iOS version TrollStore supports?
        ├── yes ──► TrollStore. Permanent signatures, and you get JIT.
        └── no
            └── Are you in the EU?
                ├── yes ──► AltStore PAL. €1.50/yr, fully sanctioned.
                └── no  ──► SideStore. Free, self-renewing, needs a one-time setup.
```

## First: register the app id

Signing needs a provisioning profile, and only Apple issues them — there is no public
API, and the only supported route is Xcode's automatic signing.

`porthole bootstrap` drives that for you. It generates a throwaway Xcode project whose
sole purpose is to make Xcode register the bundle id and fetch a profile, builds it
once, and discards it.

```bash
porthole bootstrap --dry-run   # generate and validate the project; Apple not contacted
porthole bootstrap             # register the app id and fetch a profile
```

This is the one command in Porthole that **changes your Apple developer account**, so
it is never run implicitly — `porthole sign` prints instructions and stops instead.

- Your Apple ID must already be signed in to Xcode (Settings → Accounts).
- A **free** Apple ID may register only **10 app ids per 7 days**, so don't spend them
  experimenting. Library mode needs exactly one.
- Profiles land in `~/Library/MobileDevice/Provisioning Profiles`, and `porthole sign`
  finds them from then on — including after Xcode renews an expired one.

If you would rather do it by hand: create any iOS project in Xcode with the same
bundle identifier (`app.porthole.shell` for library mode) and press Run once. The
effect is identical.

## Then: trust the certificate on the device

A first install signed with a development certificate installs fine and then refuses
to launch:

```
Unable to launch app.porthole.shell because it has an invalid code signature,
inadequate entitlements or its profile has not been explicitly trusted by the user
```

Almost always the last of those three. On the iPhone:

**Settings → General → VPN & Device Management → Developer App → your Apple ID → Trust**

Once per certificate, not once per install. `porthole install` detects this case and
prints the same instructions rather than reporting a failure.

## Free Apple ID + Xcode

What everyone starts with, and the most annoying long-term.

- **Cost** nothing
- **Expires** 7 days
- **Limits** 3 app IDs at a time, 10 app IDs per week
- **Needs** a Mac with Xcode, a USB cable

```bash
porthole bootstrap              # once, to register the app id
porthole build diablo --mode library
porthole sign                   # uses the identity in your keychain
porthole install                # over USB
```

Every 7 days the app stops launching and you run `porthole refresh`. Because Porthole
keeps game data outside the signed bundle and reuses the same bundle ID, **re-signing
never touches your saves** and takes seconds rather than minutes.

The 3-app-ID limit is exactly why `--mode library` is the default: one app holding
twenty games costs one app ID.

## Paid Apple Developer Program

- **Cost** $99/yr
- **Expires** 1 year
- **Limits** 100 devices
- **Needs** a Mac with Xcode

No weekly ritual, and `--mode standalone` becomes practical — a real icon and name per
game on your home screen. If you're going to use this regularly, this is the path.

## SideStore

Re-signs apps **on the device itself**, using a local WireGuard tunnel to talk to
Apple's servers, so you never need the Mac again after setup.

- **Cost** free
- **Expires** self-renewing (still 7-day certificates underneath; SideStore handles it)
- **Needs** one-time pairing-file setup from a computer

The pragmatic choice for most people without a paid account.
→ [sidestore.io](https://sidestore.io)

## AltStore PAL

The EU's Digital Markets Act forced Apple to permit alternative app marketplaces.
AltStore PAL is a properly notarized one — not a workaround.

- **Cost** €1.50/yr (Apple's Core Technology Fee, charged to the marketplace)
- **Expires** doesn't
- **Limits** EU residency, verified by Apple
- **Needs** nothing but an iPhone

If you're in the EU this is the least friction available.
→ [altstore.io](https://altstore.io)

## TrollStore

Exploits a flaw in signature validation to install apps with **permanent** signatures
and full entitlements — including the one that enables JIT.

- **Cost** free
- **Expires** never
- **Limits** only works on specific iOS versions; newer devices are patched
- **Side effect** JIT works, so N64, PSP, and Dreamcast cores become viable

Check whether your exact iOS version is supported before getting your hopes up.

## Jailbreak

Full control: permanent signing, JIT, and filesystem access so you can drop a 40 GB
game library straight into place. You already know whether this is you.

## The JIT entitlement, specifically

iOS refuses to map memory as writable *and* executable without
`com.apple.private.security.no-sandbox` or the dynamic-codesigning entitlement. Apple
grants neither to normal apps. This is a security design, not an oversight.

Consequences for Porthole:

| Install path | JIT | What it unlocks |
|---|---|---|
| Free / paid signing | no | Tier 1 native ports, Tier 3 interpreters, 8/16-bit cores, PSX interpreter |
| `ptrace` trick (some iOS versions) | sometimes | PSX dynarec, DOSBox dynamic core |
| TrollStore | yes | N64, PSP, Dreamcast, MAME at speed |
| Jailbreak | yes | everything |

Porthole detects which situation it's in at launch and chooses the fast path when it
exists. Interpreter fallbacks always ship, so nothing is *unavailable* — some things
are just slow. `porthole plan <game>` tells you which before you build.

## Getting your game files onto the phone

The app arrives nearly empty and pulls assets afterwards. Four ways in:

1. **Files app** — drag the folder into `On My iPhone → Porthole`. Simplest.
2. **AirDrop** — send an archive; the app registers as a handler.
3. **Local handoff** — `porthole serve ~/Morrowind` serves the directory over HTTP on
   your LAN at wire speed. Fastest by a wide margin for multi-gigabyte games.

   ```console
   $ porthole serve ~/GOG/Diablo
   Serving
     directory     /Users/you/GOG/Diablo
     files         2
     size          517.0 MB

     http://192.168.2.133:52831/syhkfmmtgX0UogDp
   ```

   The URL carries a random token and requests without it get a 404 — this is your
   game directory on a network you may not control, so an open directory listing is
   not a reasonable default. It is read-only, confined to that one directory, and
   refuses writes. A QR code is shown if `qrencode` is installed.

   It also serves `manifest.json` listing every file with its size and a fingerprint,
   so the app can verify a transfer finished rather than discovering a truncated
   asset at launch.
4. **iCloud Drive** — put it in the Porthole folder and import on device.

Imported assets are verified against the recipe's expected layout, so a half-finished
transfer is caught at import rather than at launch.

## What will not happen

- Porthole will not appear on the App Store. GPL engines are incompatible with App
  Store terms, independent of Apple's content rules. See [LEGAL.md](LEGAL.md).
- Porthole will not sign with a certificate it owns. There isn't one.
- Porthole will not use enterprise distribution. That's a terms violation.
