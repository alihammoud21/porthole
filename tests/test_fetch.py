"""Fetch and pin tests.

The network is only touched by the one test marked `network`; everything else works
against a local git repository created in a temp directory, so the suite stays fast
and offline.
"""

import subprocess

import pytest

from porthole import fetch, registry


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def fake_upstream(tmp_path):
    """A real git repo with one commit and a tag, standing in for an upstream."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    git(["init", "-q", "-b", "main"], repo)
    git(["config", "user.email", "t@example.com"], repo)
    git(["config", "user.name", "Test"], repo)
    (repo / "CMakeLists.txt").write_text("project(fake)\nFetchContent_Declare(x)\n")
    # Git does not track empty directories, so the vendored-dependency marker needs
    # an actual file or it will not survive the clone.
    (repo / "3rdParty" / "SDL2").mkdir(parents=True)
    (repo / "3rdParty" / "SDL2" / "CMakeLists.txt").write_text("# vendored\n")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "initial"], repo)
    git(["tag", "v1.0"], repo)
    return repo, git(["rev-parse", "HEAD"], repo)


# ───────────────────────────── manifest parsing ─────────────────────────────

def test_manifest_loads_for_devilutionx():
    m = fetch.BuildManifest.load("devilutionx")
    assert m.runtime == "devilutionx"
    assert m.tag == "1.5.4"
    assert m.commit and len(m.commit) == 40, "upstream must be pinned to a commit"
    assert m.submodules
    assert any("CMAKE_SYSTEM_NAME=iOS" in a for a in m.cmake_args)


def test_manifest_requires_a_tag_not_a_branch(tmp_path, monkeypatch):
    """Branches move. A pin that can drift is not a pin."""
    root = tmp_path
    (root / "runtimes" / "faux").mkdir(parents=True)
    (root / "recipes").mkdir()
    (root / "runtimes" / "faux" / "build.toml").write_text(
        '[source]\ngit = "https://example.com/x"\n')
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    with pytest.raises(fetch.FetchError, match="needs a tag"):
        fetch.BuildManifest.load("faux")


def test_missing_manifest_is_explained(tmp_path, monkeypatch):
    (tmp_path / "runtimes").mkdir()
    (tmp_path / "recipes").mkdir()
    monkeypatch.setattr(registry, "repo_root", lambda: tmp_path)
    with pytest.raises(fetch.FetchError, match="has no build.toml"):
        fetch.BuildManifest.load("nope")


# ───────────────────────────── pinning ─────────────────────────────

def _manifest(root, name, git_url, tag, commit=None):
    d = root / "runtimes" / name
    d.mkdir(parents=True, exist_ok=True)
    (root / "recipes").mkdir(exist_ok=True)
    body = f'[source]\ngit = "{git_url}"\ntag = "{tag}"\n'
    if commit:
        body += f'commit = "{commit}"\n'
    (d / "build.toml").write_text(body)


def test_fetch_clones_at_the_pinned_commit(tmp_path, monkeypatch, fake_upstream):
    repo, head = fake_upstream
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=head)
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    result = fetch.fetch("faux")
    assert result.commit == head
    assert result.path.is_dir()
    assert (result.path / "CMakeLists.txt").is_file()


def test_fetch_rejects_a_moved_tag(tmp_path, monkeypatch, fake_upstream):
    """The whole point of the pin: refuse rather than silently build other code."""
    repo, head = fake_upstream
    wrong = "0" * 40
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=wrong)
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    with pytest.raises(fetch.FetchError, match="pin mismatch"):
        fetch.fetch("faux")


def test_fetch_reuses_a_correct_checkout(tmp_path, monkeypatch, fake_upstream):
    repo, head = fake_upstream
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=head)
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    assert not fetch.fetch("faux").reused
    assert fetch.fetch("faux").reused


# ───────────────────────────── patches ─────────────────────────────

def test_a_patch_that_does_not_apply_is_an_error(tmp_path, monkeypatch, fake_upstream):
    repo, head = fake_upstream
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=head)
    (root / "runtimes" / "faux" / "build.toml").write_text(
        (root / "runtimes" / "faux" / "build.toml").read_text()
        + '\n[patches]\nseries = ["01-nope.patch"]\n')
    patches = root / "runtimes" / "faux" / "patches"
    patches.mkdir()
    (patches / "01-nope.patch").write_text(
        "--- a/does-not-exist\n+++ b/does-not-exist\n@@ -1 +1 @@\n-a\n+b\n")
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    with pytest.raises(fetch.FetchError, match="does not apply"):
        fetch.fetch("faux")


# ───────────────────────────── probing ─────────────────────────────

def test_probe_reports_vendored_dependencies(tmp_path, monkeypatch, fake_upstream):
    """Spotting vendored deps is what stops someone cross-compiling SDL2 by hand."""
    repo, head = fake_upstream
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=head)
    monkeypatch.setattr(registry, "repo_root", lambda: root)

    fetch.fetch("faux")
    result = fetch.probe("faux")
    assert result.has_cmake
    assert any("3rdParty" in n for n in result.notes)
    assert any("FetchContent" in n for n in result.notes)


def test_probe_requires_a_fetch_first(tmp_path, monkeypatch, fake_upstream):
    repo, head = fake_upstream
    root = tmp_path / "repo"
    _manifest(root, "faux", str(repo), "v1.0", commit=head)
    monkeypatch.setattr(registry, "repo_root", lambda: root)
    with pytest.raises(fetch.FetchError, match="not fetched"):
        fetch.probe("faux")


def test_sources_are_never_committed():
    """docs/LEGAL.md promises upstream source is never vendored; enforce it."""
    import subprocess as sp
    root = registry.repo_root()
    tracked = sp.run(["git", "ls-files"], cwd=root, capture_output=True,
                     text=True).stdout.split()
    assert not [f for f in tracked if f.startswith(".cache/")], \
        "fetched upstream source must not be committed"
