"""Launcher helpers for Mac Preview .app (runs on any OS)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.paths import detect_root
from scripts.mac.app_main import (
    count_packs,
    find_free_port,
    is_valid_library,
    load_prefs,
    prefs_path,
    save_prefs,
)


def test_detect_root_points_at_repo():
    root = detect_root()
    assert (root / "web" / "live.html").is_file()
    assert (root / "server" / "preview_app.py").is_file()


def test_count_packs_and_valid_library(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert count_packs(empty) == 0
    assert not is_valid_library(empty)

    pack = tmp_path / "song-a"
    pack.mkdir()
    (pack / "meta.json").write_text("{}", encoding="utf-8")
    assert count_packs(tmp_path) == 1
    assert is_valid_library(tmp_path)


def test_prefs_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Force support_dir under tmp by patching Path.home via HOME on Unix;
    # on Windows app_main uses ~/.karaok — patch prefs_path instead.
    pref = tmp_path / "prefs.json"
    monkeypatch.setattr("scripts.mac.app_main.prefs_path", lambda: pref)

    assert load_prefs() == {}
    save_prefs({"songs_dir": str(tmp_path / "songs")})
    assert json.loads(pref.read_text(encoding="utf-8"))["songs_dir"].endswith("songs")
    assert load_prefs()["songs_dir"].endswith("songs")


def test_find_free_port_binds_localhost():
    port = find_free_port("127.0.0.1", 18700)
    assert 18700 <= port < 18740
