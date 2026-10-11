"""LAN asset handoff tests.

This server exposes somebody's game directory on a network they may not control, so
the security properties are tested as carefully as the functional ones: token gating,
path traversal, and refusal of writes.

Large files are sparse, so a 517 MB streaming test costs no disk.
"""

import json
import urllib.error
import urllib.request

import pytest

from porthole import serve as serve_mod


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "Diablo"
    (root / "nested").mkdir(parents=True)
    with open(root / "DIABDAT.MPQ", "wb") as f:
        f.truncate(517_000_000)          # sparse: no real disk used
    (root / "nested" / "readme.txt").write_text("hello")

    # A file outside the served root, to prove traversal cannot reach it.
    (tmp_path / "secret.txt").write_text("must not be reachable")

    server = serve_mod.serve(root, port=0, bind="127.0.0.1")
    yield server, root, tmp_path
    server.stop()


def fetch(server, path, token=None, method="GET", data=None):
    token = token if token is not None else server.token
    url = f"http://127.0.0.1:{server.port}/{token}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


# ───────────────────────────── functional ─────────────────────────────

def test_manifest_lists_every_file(served):
    server, _, _ = served
    status, body = fetch(server, "/manifest.json")
    assert status == 200

    manifest = json.loads(body)
    assert manifest["file_count"] == 2
    assert manifest["total_bytes"] == 517_000_000 + 5
    paths = {f["path"] for f in manifest["files"]}
    assert paths == {"DIABDAT.MPQ", "nested/readme.txt"}


def test_manifest_includes_fingerprints(served):
    """The app verifies a transfer against these rather than finding a truncated
    asset at launch."""
    server, _, _ = served
    _, body = fetch(server, "/manifest.json")
    for f in json.loads(body)["files"]:
        assert "fingerprint" in f
        assert len(f["fingerprint"]) == 32


def test_nested_file_is_served(served):
    server, _, _ = served
    status, body = fetch(server, "/nested/readme.txt")
    assert status == 200
    assert body == b"hello"


def test_large_file_streams_intact(served):
    """These files are routinely larger than memory, so the handler streams."""
    server, _, _ = served
    url = f"http://127.0.0.1:{server.port}/{server.token}/DIABDAT.MPQ"
    received = 0
    with urllib.request.urlopen(url, timeout=60) as r:
        while chunk := r.read(1 << 22):
            received += len(chunk)
    assert received == 517_000_000


def test_root_serves_the_manifest(served):
    server, _, _ = served
    status, body = fetch(server, "")
    assert status == 200
    assert json.loads(body)["file_count"] == 2


def test_fingerprint_changes_on_truncation(tmp_path):
    """Truncation is the failure that actually happens; it must be detectable."""
    f = tmp_path / "big.bin"
    with open(f, "wb") as fh:
        fh.write(b"A" * (3 << 20))
    before = serve_mod.fingerprint(f)

    with open(f, "r+b") as fh:
        fh.truncate(2 << 20)
    assert serve_mod.fingerprint(f) != before


# ───────────────────────────── security ─────────────────────────────

def test_wrong_token_is_rejected(served):
    server, _, _ = served
    status, _ = fetch(server, "/nested/readme.txt", token="not-the-token")
    assert status == 404, "a wrong token must not reveal that anything is here"


def test_empty_token_is_rejected(served):
    server, _, _ = served
    status, _ = fetch(server, "/nested/readme.txt", token="")
    assert status == 404


def test_path_traversal_is_blocked(served):
    server, _, _ = served
    for attempt in ("/../secret.txt", "/../../etc/passwd",
                    "/nested/../../secret.txt", "/%2e%2e/secret.txt"):
        status, _ = fetch(server, attempt)
        assert status == 404, f"traversal not blocked: {attempt}"


def test_writes_are_refused(served):
    server, _, _ = served
    for method in ("POST", "PUT"):
        status, _ = fetch(server, "/evil.txt", method=method, data=b"x")
        assert status == 405, f"{method} was not refused"


def test_missing_file_is_404(served):
    server, _, _ = served
    status, _ = fetch(server, "/does-not-exist.bin")
    assert status == 404


def test_tokens_are_unpredictable(tmp_path):
    """Two servers must not share a token."""
    (tmp_path / "a").mkdir()
    s1 = serve_mod.serve(tmp_path / "a", port=0, bind="127.0.0.1", hash_files=False)
    s2 = serve_mod.serve(tmp_path / "a", port=0, bind="127.0.0.1", hash_files=False)
    try:
        assert s1.token != s2.token
        assert len(s1.token) >= 16
    finally:
        s1.stop()
        s2.stop()


def test_not_a_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        serve_mod.serve(tmp_path / "nope", port=0, bind="127.0.0.1")
