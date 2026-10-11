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
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

PROFILE_DIR = Path.home() / "Library/MobileDevice/Provisioning Profiles"


class SignError(RuntimeError):
    pass


# ───────────────────────────────── identities ─────────────────────────────────

@dataclass
class Identity:
    sha1: str
    name: str

    @property
    def is_free_account(self) -> bool:
        # Paid accounts get "Apple Distribution" / "iPhone Distribution"; free Apple
        # IDs only ever get a development certificate.
        return "Development" in self.name


def identities() -> list[Identity]:
    try:
        out = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise SignError("could not read the keychain") from e

    found = []
    for line in out.splitlines():
        m = re.search(r"\)\s+([0-9A-F]{40})\s+\"(.+)\"", line)
        if m and ("Apple Develop" in m.group(2) or "Apple Distribution" in m.group(2)):
            found.append(Identity(sha1=m.group(1), name=m.group(2)))
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
    if not PROFILE_DIR.is_dir():
        return []
    found = []
    for p in sorted(PROFILE_DIR.glob("*.mobileprovision")):
        if (plist := _decode_profile(p)) is not None:
            found.append(Profile(path=p, plist=plist))
    return found


def find_profile(bundle_id: str) -> Profile:
    """Prefer an exact match over a wildcard, and a later expiry over an earlier one."""
    candidates = [p for p in profiles() if p.matches(bundle_id)]
    if not candidates:
        raise SignError(
            f"no provisioning profile matches '{bundle_id}'.\n\n"
            "  Porthole cannot create one -- only Apple can, and only through Xcode.\n"
            "  The one-time fix:\n"
            "    1. Open Xcode, Settings -> Accounts, and sign in with your Apple ID\n"
            "    2. Create any iOS project with this exact bundle identifier\n"
            f"       ({bundle_id})\n"
            "    3. Select your device and press Run once\n\n"
            "  Xcode registers the app id and writes a profile to\n"
            f"    {PROFILE_DIR}\n"
            "  After that `porthole sign` finds it on its own, including after it\n"
            "  expires and Xcode renews it.\n\n"
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

    days = None
    if profile.expires is not None:
        from datetime import datetime, timezone
        try:
            delta = profile.expires - datetime.now(timezone.utc)
            days = delta.days
        except TypeError:
            days = None

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
        if hw.get("platform") != "iOS":
            continue
        found.append(Device(
            identifier=d.get("identifier", "?"),
            name=props.get("name", "iPhone"),
            os_version=props.get("osVersionNumber", "?"),
        ))
    return found


def install(app: Path, device: Device | None = None) -> str:
    targets = devices()
    if not targets:
        raise SignError(
            "no iPhone connected.\n\n"
            "  Connect by USB, unlock the phone, and trust this computer.\n"
            "  Without a cable, install the .ipa through SideStore or AltStore\n"
            "  instead -- see docs/INSTALLING.md."
        )
    device = device or targets[0]

    proc = subprocess.run(
        ["xcrun", "devicectl", "device", "install", "app",
         "--device", device.identifier, str(app)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SignError(
            f"install failed on {device.name}:\n{(proc.stderr or proc.stdout).strip()}"
        )
    return f"{device.name} (iOS {device.os_version})"
