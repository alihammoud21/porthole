"""Detection tests.

Fixtures are sparse files: real names, real sizes as far as the filesystem is
concerned, zero bytes actually written. Never commit game data, not even for tests.
"""

import pytest

from porthole import plan as plan_mod, registry, scan as scan_mod


def make(tmp_path, spec):
    """spec: {relative/path: size_in_bytes}. Directories are created for size None."""
    for rel, size in spec.items():
        p = tmp_path / rel
        if size is None:
            p.mkdir(parents=True, exist_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            f.truncate(size)
    return tmp_path


def ids(matches):
    return [m.recipe.id for m in matches]


# ───────────────────────────── the three match modes ─────────────────────────────

def test_basename_match(tmp_path):
    root = make(tmp_path, {
        "Data Files/Morrowind.esm": 800_000_000,
        "Data Files/Morrowind.bsa": 500_000_000,
    })
    _, m = scan_mod.scan(root)
    assert "morrowind" in ids(m)
    assert m[0].confidence == "high"


def test_path_suffix_match(tmp_path):
    """`data/g1.dat` must match a nested Data/ directory but not a bare g1.dat."""
    root = make(tmp_path, {"RCT2/Data/g1.dat": 8_000_000})
    _, m = scan_mod.scan(root)
    assert "rct2" in ids(m)

    other = make(tmp_path / "flat", {"g1.dat": 8_000_000})
    _, m2 = scan_mod.scan(other)
    assert "rct2" not in ids(m2)


def test_glob_with_slash(tmp_path):
    root = make(tmp_path, {"data/LEVEL1.PHD": 2_000_000})
    _, m = scan_mod.scan(root)
    assert "tomb-raider" in ids(m)


def test_directory_names_count(tmp_path):
    """Theme Hospital has no single distinctive file — only a set of directories."""
    root = make(tmp_path, {"DATA": None, "LEVELS": None, "ANIMS": None})
    _, m = scan_mod.scan(root)
    assert "theme-hospital" in ids(m)


def test_extension_table(tmp_path):
    root = make(tmp_path, {
        "Zelda.sfc": 4_000_000,
        "Metroid.nes": 1_000_000,
        "Pokemon.gba": 8_000_000,
    })
    _, m = scan_mod.scan(root)
    assert "rom-family" in ids(m)
    detail = next(x for x in m if x.recipe.id == "rom-family").detail
    assert {"SNES", "NES", "Game Boy Advance"} <= set(detail["platforms"])


# ─────────────────────────────── negative cases ───────────────────────────────

def test_min_bytes_rejects_demo(tmp_path):
    """Same filenames as the real game, far too small — Morrowind's demo."""
    root = make(tmp_path, {
        "Data Files/Morrowind.esm": 1_000_000,
        "Data Files/Morrowind.bsa": 1_000_000,
    })
    _, m = scan_mod.scan(root)
    assert "morrowind" not in ids(m)


def test_partial_require_does_not_match(tmp_path):
    """Every `require` entry must be present, not just one."""
    root = make(tmp_path, {"Data Files/Morrowind.esm": 900_000_000})
    _, m = scan_mod.scan(root)
    assert "morrowind" not in ids(m)


def test_nothing_recognizable(tmp_path):
    root = make(tmp_path, {"notes.txt": 100, "photo.jpg": 2_000})
    _, m = scan_mod.scan(root)
    assert m == []


def test_missing_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        scan_mod.scan(tmp_path / "nope")


# ─────────────────────────────── ranking ───────────────────────────────

def test_specific_beats_family(tmp_path):
    """A DOS directory that is also recognizably Duke Nukem must rank Duke first."""
    root = make(tmp_path, {
        "DUKE3D.GRP": 40_000_000,
        "DUKE3D.EXE": 500_000,
        "SETUP.EXE": 100_000,
        "DUKE.BAT": 100,
    })
    _, m = scan_mod.scan(root)
    assert m[0].recipe.id == "duke3d"
    assert not m[0].recipe.is_family


def test_low_confidence_family_is_dropped_when_specific_matches(tmp_path):
    root = make(tmp_path, {"BLOOD.RFF": 10_000_000, "BLOOD.INI": 400, "RUN.BAT": 60})
    _, m = scan_mod.scan(root)
    assert "blood" in ids(m)
    assert "dos-family" not in ids(m)      # declared confidence = "low"


# ─────────────────────────── registry integrity ───────────────────────────

def test_every_recipe_resolves(tmp_path):
    rts, lays = registry.runtimes(), registry.layouts()
    for rid, rec in registry.recipes().items():
        assert rec.runtime in rts, f"{rid}: unknown runtime {rec.runtime}"
        assert rec.layout in lays or rec.layout == "passthrough", \
            f"{rid}: unknown layout {rec.layout}"
        assert rec.tier in (1, 2, 3, 4), f"{rid}: bad tier"
        assert rec.detect, f"{rid}: no detect block"


def test_every_runtime_declares_a_license():
    for rid, rt in registry.runtimes().items():
        assert rt.get("license"), f"{rid}: no license"


def test_plan_reports_blockers_not_exceptions():
    """A recipe whose runtime has no iOS port must plan cleanly and say why."""
    p = plan_mod.build_plan("quake")
    assert not p.buildable
    assert any("no iOS port" in x for x in p.problems)


def test_plan_unknown_game_raises():
    with pytest.raises(KeyError):
        plan_mod.build_plan("halo-infinite")
