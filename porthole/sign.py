"""Code signing and device install.

Porthole has no signing identity and never will. Everything here uses the user's own
certificate from their own keychain, and their own provisioning profile created by
Xcode. Enterprise distribution certificates are deliberately unsupported: using one
violates Apple's terms and gets certificates revoked for everyone sharing them.

The hard part of signing is not `codesign` -- it is finding a provisioning profile
that matches the bundle id, and extracting entitlements from it. That is what most of
this module does.
"""

from __future__ import annotations

import plistlib
import re
from datetime import datetime, timezone
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Xcode 16 moved managed provisioning profiles out of the legacy location that every
# older guide still cites. Both are searched, newest first, because a machine can have
# profiles in either depending on how long Xcode has been installed.
PROFILE_DIRS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]

# Kept for messages that tell the user where to look.
PROFILE_DIR = PROFILE_DIRS[0]


class SignError(RuntimeError):
    pass


# ───────────────────────────────── identities ─────────────────────────────────

@dataclass
class Identity:
    sha1: str
    name: str
    team_id: str = ""

    @property
    def is_free_account(self) -> bool:
        # Paid accounts get "Apple Distribution" / "iPhone Distribution"; free Apple
        # IDs only ever get a development certificate.
        return "Development" in self.name


def _team_ids_by_cn() -> dict[str, str]:
    """Map certificate common name to Team ID, read from the certificate itself.

    The Team ID lives in the subject's **OU** field. It is tempting to parse it out of
    the common name instead -- `Apple Development: you@example.com (XXXXXXXXXX)` looks
    exactly like it contains one -- but for `Apple Development` certificates that
    parenthetical is the *certificate* id, not the team. Reading it from there yields
    a plausible-looking wrong value and xcodebuild then fails with
    "No Account for Team ...", which sends you looking in entirely the wrong place.
    """
    try:
        pem = subprocess.run(
            ["security", "find-certificate", "-a", "-p"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}

    mapping: dict[str, str] = {}
    blocks = re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    for block in blocks:
        try:
            subject = subprocess.run(
                ["openssl", "x509", "-noout", "-subject"],
                input=block, capture_output=True, text=True, check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        cn = re.search(r"CN\s*=\s*([^,/]+)", subject)
        ou = re.search(r"OU\s*=\s*([A-Z0-9]{10})", subject)
        if cn and ou:
            mapping[cn.group(1).strip()] = ou.group(1)
    return mapping


def identities() -> list[Identity]:
    try:
        out = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise SignError("could not read the keychain") from e

    teams = _team_ids_by_cn()
    found = []
    for line in out.splitlines():
        m = re.search(r"\)\s+([0-9A-F]{40})\s+\"(.+)\"", line)
        if m and ("Apple Develop" in m.group(2) or "Apple Distribution" in m.group(2)):
            name = m.group(2)
            found.append(Identity(
                sha1=m.group(1), name=name, team_id=teams.get(name, "")))
    return found


# ──────────────────────────── provisioning profiles ────────────────────────────

@dataclass
class Profile:
    path: Path
    plist: dict

    @property
    def app_id(self) -> str:
        ent = self.plist.get("Entitlements", {})
        full = ent.get("application-identifier", "")
        # Strip the team prefix: "ABCD1234.app.porthole.shell" -> "app.porthole.shell"
        return full.split(".", 1)[1] if "." in full else full

    @property
    def team_id(self) -> str:
        teams = self.plist.get("TeamIdentifier") or []
        return teams[0] if teams else ""

    @property
    def is_wildcard(self) -> bool:
        return self.app_id.endswith("*")

    @property
    def expires(self):
        return self.plist.get("ExpirationDate")

    def matches(self, bundle_id: str) -> bool:
        if self.is_wildcard:
            return bundle_id.startswith(self.app_id[:-1])
        return self.app_id == bundle_id


def _decode_profile(path: Path) -> dict | None:
    """A .mobileprovision is CMS-wrapped; `security cms -D` unwraps it."""
    try:
        out = subprocess.run(
            ["security", "cms", "-D", "-i", str(path)],
            capture_output=True, check=True,
        ).stdout
        return plistlib.loads(out)
    except (OSError, subprocess.CalledProcessError, plistlib.InvalidFileException):
        return None


def profiles() -> list[Profile]:
    found = []
    for directory in PROFILE_DIRS:
        if not directory.is_dir():
            continue
        for p in sorted(directory.glob("*.mobileprovision")):
            if (plist := _decode_profile(p)) is not None:
                found.append(Profile(path=p, plist=plist))
    return found


def find_profile(bundle_id: str) -> Profile:
    """Prefer an exact match over a wildcard, and a later expiry over an earlier one."""
    candidates = [p for p in profiles() if p.matches(bundle_id)]
    if not candidates:
        raise SignError(
            f"no provisioning profile matches '{bundle_id}'.\n\n"
            "  Only Apple issues these. To register the app id and fetch one:\n\n"
            "    porthole bootstrap\n\n"
            "  That generates a throwaway Xcode project, lets Xcode register the id,\n"
            "  and discards it. Add --dry-run first to see what it would do without\n"
            "  contacting Apple.\n\n"
            "  Requires your Apple ID signed in to Xcode (Settings -> Accounts).\n"
            "  A free Apple ID works but is limited to 10 app ids per 7 days.\n"
            f"  Profiles land in {PROFILE_DIR}\n"
            "  and `porthole sign` finds them from then on, including after Xcode\n"
            "  renews an expired one.\n\n"
            "  See docs/INSTALLING.md for the other install paths."
        )
    candidates.sort(key=lambda p: (not p.is_wildcard, p.expires or 0), reverse=True)
    return candidates[0]


# ───────────────────────────────── signing ─────────────────────────────────

@dataclass
class SignResult:
    app: Path
    identity: Identity
    profile: Profile
    bundle_id: str
    expires: object
    days_left: int | None


def sign(app: Path, identity: Identity | None = None,
         profile: Profile | None = None) -> SignResult:
    if not app.is_dir():
        raise SignError(f"not an app bundle: {app}")

    info_path = app / "Info.plist"
    if not info_path.is_file():
        raise SignError(f"{app.name} has no Info.plist")
    bundle_id = plistlib.loads(info_path.read_bytes())["CFBundleIdentifier"]

    if identity is None:
        available = identities()
        if not available:
            raise SignError(
                "no code signing identity in your keychain.\n\n"
                "  Open Xcode, Settings -> Accounts, add your Apple ID, then\n"
                "  'Manage Certificates' -> + -> Apple Development.\n"
                "  A free Apple ID is enough; see docs/INSTALLING.md."
            )
        # Development certificates first: that is what a free account has, and what
        # the overwhelming majority of users will be signing with.
        available.sort(key=lambda i: not i.is_free_account)
        identity = available[0]

    if profile is None:
        profile = find_profile(bundle_id)

    # 1. Embed the profile. Without this iOS refuses to install, with an error that
    #    tells you nothing.
    shutil.copy2(profile.path, app / "embedded.mobileprovision")

    # 2. Entitlements come from the profile, narrowed to what an app may actually
    #    claim. Taking them wholesale includes profile metadata that codesign rejects.
    ent = profile.plist.get("Entitlements", {})
    entitlements = {
        k: v for k, v in ent.items()
        if k in {
            "application-identifier",
            "com.apple.developer.team-identifier",
            "get-task-allow",
            "keychain-access-groups",
            "com.apple.security.application-groups",
        }
    }
    ent_path = app.parent / f"{app.stem}.entitlements.plist"
    ent_path.write_bytes(plistlib.dumps(entitlements))

    # 3. Sign inside out: frameworks before the app that loads them, or the outer
    #    signature is invalidated by the inner ones.
    frameworks = app / "Frameworks"
    if frameworks.is_dir():
        for fw in sorted(frameworks.iterdir()):
            if fw.suffix == ".framework":
                _codesign(identity, fw, entitlements=None)

    _codesign(identity, app, entitlements=ent_path)
    ent_path.unlink(missing_ok=True)

    # plistlib returns naive datetimes, and plist dates are UTC. Subtracting an
    # aware `now()` from one raises TypeError -- which, when swallowed, silently
    # disabled the 7-day expiry warning that free-account users most need to see.
    days = None
    if isinstance(profile.expires, datetime):
        expires = profile.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        days = (expires - datetime.now(timezone.utc)).days

    return SignResult(
        app=app, identity=identity, profile=profile,
        bundle_id=bundle_id, expires=profile.expires, days_left=days,
    )


def _codesign(identity: Identity, target: Path, entitlements: Path | None) -> None:
    args = [
        "codesign", "--force", "--sign", identity.sha1,
        "--timestamp=none",
        # Required for anything that will be loaded by a hardened runtime, and
        # harmless otherwise.
        "--generate-entitlement-der",
    ]
    if entitlements is not None:
        args += ["--entitlements", str(entitlements)]
    args.append(str(target))

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SignError(
            f"codesign failed on {target.name}:\n{(proc.stderr or proc.stdout).strip()}"
        )


def verify(app: Path) -> str:
    proc = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SignError((proc.stderr or proc.stdout).strip())
    return (proc.stderr or proc.stdout).strip()


# ───────────────────────────────── packaging ─────────────────────────────────

def make_ipa(app: Path, out: Path | None = None) -> Path:
    """Wrap a signed .app as an .ipa, which is what SideStore and AltStore take."""
    out = out or app.parent / f"{app.stem}.ipa"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file() or f.is_symlink():
                z.write(f, Path("Payload") / app.name / f.relative_to(app))
    return out


# ───────────────────────────────── install ─────────────────────────────────

@dataclass
class Device:
    identifier: str
    name: str
    os_version: str
    model: str = ""
    is_hardware: bool = False
    is_connected: bool = False

    @property
    def label(self) -> str:
        kind = self.model or ("device" if self.is_hardware else "simulator")
        return f"{self.name} ({kind}, iOS {self.os_version})"


def devices() -> list[Device]:
    """Connected devices via devicectl, which ships with Xcode 15 and later."""
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        proc = subprocess.run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", tmp.name],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return []
        try:
            data = json.loads(Path(tmp.name).read_text())
        except (OSError, json.JSONDecodeError):
            return []

    found = []
    for d in data.get("result", {}).get("devices", []):
        props = d.get("deviceProperties", {})
        hw = d.get("hardwareProperties", {})
        conn = d.get("connectionProperties", {})
        if hw.get("platform") != "iOS":
            continue

        # `isProductionFused` is the reliable tell for real hardware. A Simulator
        # appears here with transportType "sameMachine" and no fuse property, and is
        # otherwise indistinguishable from a phone.
        is_hardware = bool(hw.get("isProductionFused")) and \
            conn.get("transportType") != "sameMachine"

        found.append(Device(
            identifier=d.get("identifier", "?"),
            name=props.get("name", "iPhone"),
            os_version=props.get("osVersionNumber", "?"),
            model=hw.get("productType", ""),
            is_hardware=is_hardware,
            is_connected=conn.get("tunnelState") == "connected",
        ))

    # Real connected hardware first; a Simulator is a last resort, never a default.
    found.sort(key=lambda d: (not (d.is_hardware and d.is_connected),
                              not d.is_hardware, not d.is_connected))
    return found


def install(app: Path, device: Device | None = None,
            allow_simulator: bool = False) -> str:
    targets = devices()
    usable = [d for d in targets
              if d.is_connected and (d.is_hardware or allow_simulator)]

    if not usable:
        detail = ""
        if targets:
            detail = "\n\n  Seen but not usable:\n" + "\n".join(
                f"    {d.label} — "
                + ("not connected" if not d.is_connected else "simulator")
                for d in targets)
        raise SignError(
            "no connected iPhone.\n\n"
            "  Connect by USB, unlock the phone, and trust this computer.\n"
            "  Without a cable, install the .ipa through SideStore or AltStore\n"
            "  instead -- see docs/INSTALLING.md." + detail
        )
    device = device or usable[0]

    proc = subprocess.run(
        ["xcrun", "devicectl", "device", "install", "app",
         "--device", device.identifier, str(app)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SignError(
            f"install failed on {device.name}:\n{(proc.stderr or proc.stdout).strip()}"
        )
    return device.label


def launch(app_bundle_id: str, device: Device) -> tuple[bool, str]:
    """Try to launch the installed app. Returns (launched, message).

    A first install signed with a development certificate will not launch until the
    certificate is trusted *on the device*. Apple requires that to happen physically
    in Settings and there is no way to do it remotely, so this reports the situation
    rather than treating it as an error.
    """
    proc = subprocess.run(
        ["xcrun", "devicectl", "device", "process", "launch",
         "--device", device.identifier, app_bundle_id],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return True, "launched"

    output = proc.stderr or proc.stdout
    if "has not been explicitly trusted" in output or "RequestDenied" in output:
        return False, "untrusted"
    return False, output.strip().splitlines()[-1] if output.strip() else "unknown error"


TRUST_INSTRUCTIONS = """\
  The app is installed but iOS will not run it yet: a development certificate has to
  be trusted on the device itself, and Apple requires that to be done physically.

  On the iPhone:
    Settings -> General -> VPN & Device Management
    -> Developer App -> your Apple ID -> Trust

  This is once per certificate, not once per install. After trusting it, launch the
  app from the home screen."""
