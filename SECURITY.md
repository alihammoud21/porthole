# Security and contact

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository (**Security → Report a
vulnerability**). That keeps the report private until there's a fix.

Please don't open a public issue for anything exploitable.

Expect an acknowledgement within a few days. This is a volunteer project, so the honest
answer on timelines is "as fast as we can," not an SLA.

## What's in scope

Porthole runs code on your own machine and builds apps that run on your own phone, so
the interesting surface is narrower than a web service. Things worth reporting:

- **Path traversal in asset import.** A malicious archive escaping the app container,
  or a recipe's `include` patterns writing outside `target`.
- **Code execution via recipe or layout files.** These are data. If a crafted TOML can
  run commands during `scan`, `plan`, or `build`, that's a real bug.
- **Build pipeline injection.** A recipe or runtime entry causing arbitrary commands to
  run during a build.
- **Signing or entitlement mishandling** that grants a built app more privilege than
  the user chose.
- **Anything that transmits data off the machine.** Porthole has no telemetry by
  design; a code path that phones home is a bug, not a feature.

## What's not a vulnerability

- **Emulator cores crashing on malformed ROMs.** Report it upstream to the core. Cores
  are not hardened against hostile input and don't claim to be.
- **A game running slowly.** See [docs/INSTALLING.md](docs/INSTALLING.md) on JIT.
- **Sideloaded apps expiring after 7 days.** That's Apple's design, not our bug.
- **Needing game files you don't have.** Working as intended, permanently.

## Rights holders

If you represent a rights holder: Porthole contains no game assets, ROMs, or
copyrighted game data, and no code to obtain them. If a *recipe* — filenames, hashes,
directory layout — nonetheless concerns you, please open an issue or use the private
reporting link above. We'd genuinely rather talk than litigate, and recipes can be
amended or removed.

The project's full reasoning is in [docs/LEGAL.md](docs/LEGAL.md), including the
`vendor = false` policy for contested upstreams and the explicit refusal to implement
DRM circumvention.

## Privacy

No telemetry, no analytics, no crash reporting, and no server. Scanning is local; which
games you own is not information this project collects or could collect.
