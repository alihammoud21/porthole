"""Hand game files to the phone over the local network.

Getting multi-gigabyte game directories onto an iPhone is the unglamorous half of
this project. The Files app works and needs no tooling, but it is slow and fiddly for
anything large. This serves the directory over HTTP on the LAN instead, so the phone
pulls it at wire speed.

Two deliberate constraints:

  - **Token-gated.** The URL carries a random token and requests without it get 404.
    This is somebody's game directory on a network they may not control, and an
    unauthenticated open directory listing is not a reasonable default.
  - **Read-only, and scoped to one directory.** No uploads, no traversal above the
    root, no symlink following out of it.

It also serves a manifest of every file with its size and a hash, so the app can
verify a transfer completed rather than discovering a truncated asset at launch.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

# Hashing whole multi-gigabyte files to verify a copy would double the transfer cost.
# A head+tail+size fingerprint catches truncation and corruption, which is what
# actually goes wrong, without reading the middle of a 2 GB archive twice.
FINGERPRINT_EDGE = 1 << 20  # 1 MiB from each end


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(FINGERPRINT_EDGE))
        if size > FINGERPRINT_EDGE * 2:
            f.seek(-FINGERPRINT_EDGE, os.SEEK_END)
            h.update(f.read(FINGERPRINT_EDGE))
    return h.hexdigest()[:32]


def lan_address() -> str:
    """The address this machine is reachable at from the phone.

    Opening a UDP socket to a public address makes the OS pick the interface it would
    actually route through, which is more reliable than guessing from the hostname.
    No packet is sent.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("198.51.100.1", 1))  # TEST-NET-2, guaranteed unroutable
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@dataclass
class Manifest:
    root: str
    files: list[dict]
    total_bytes: int

    def to_json(self) -> bytes:
        return json.dumps({
            "root": self.root,
            "total_bytes": self.total_bytes,
            "file_count": len(self.files),
            "files": self.files,
        }, indent=2).encode()


def build_manifest(root: Path, hash_files: bool = True) -> Manifest:
    files = []
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        entry = {"path": p.relative_to(root).as_posix(), "size": size}
        if hash_files:
            try:
                entry["fingerprint"] = fingerprint(p)
            except OSError:
                pass
        files.append(entry)
        total += size
    return Manifest(root=root.name, files=files, total_bytes=total)


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Token-gated, read-only, confined to one directory."""

    token: str = ""
    root: Path = Path(".")
    manifest_bytes: bytes = b"{}"
    server_version = "porthole-serve"
    sys_version = ""

    def log_message(self, fmt, *args):
        # The CLI prints its own progress; SimpleHTTPRequestHandler's stderr noise
        # would bury it.
        pass

    def _deny(self):
        # 404 rather than 403: a wrong token should not confirm that something is here.
        self.send_error(404)

    def translate_path(self, path: str) -> str:
        """Resolve inside the served root, or nowhere."""
        rel = unquote(path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        candidate = (self.root / rel).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            return ""  # escapes the root
        return str(candidate)

    def do_GET(self):  # noqa: N802
        parts = self.path.lstrip("/").split("/", 1)
        if not parts or not secrets.compare_digest(parts[0], self.token):
            return self._deny()

        rest = parts[1] if len(parts) > 1 else ""

        if rest in ("", "manifest.json"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.manifest_bytes)))
            self.end_headers()
            self.wfile.write(self.manifest_bytes)
            return

        target = self.translate_path("/" + rest)
        if not target or not os.path.isfile(target):
            return self._deny()

        try:
            with open(target, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                # Stream in chunks: these files are routinely larger than memory.
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)
        except (OSError, BrokenPipeError, ConnectionResetError):
            pass

    # Read-only by construction.
    def do_POST(self):  # noqa: N802
        self.send_error(405)

    def do_PUT(self):  # noqa: N802
        self.send_error(405)


@dataclass
class Server:
    url: str
    port: int
    token: str
    manifest: Manifest
    httpd: http.server.ThreadingHTTPServer
    thread: threading.Thread

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def serve(root: Path, port: int = 0, hash_files: bool = True,
          bind: str = "0.0.0.0") -> Server:
    """Start the handoff server. Returns immediately; call `.stop()` when done."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    manifest = build_manifest(root, hash_files=hash_files)
    token = secrets.token_urlsafe(12)

    handler = type("_BoundHandler", (_Handler,), {
        "token": token,
        "root": root,
        "manifest_bytes": manifest.to_json(),
    })

    httpd = http.server.ThreadingHTTPServer((bind, port), handler)
    actual_port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    return Server(
        url=f"http://{lan_address()}:{actual_port}/{token}",
        port=actual_port,
        token=token,
        manifest=manifest,
        httpd=httpd,
        thread=thread,
    )
