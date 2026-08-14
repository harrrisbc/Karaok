from engine.pack import SongMeta, clean_youtube_title, create_pack, get_pack, list_packs, slugify
from engine.paths import ROOT, configure_songs_dir, resolve_songs_dir


def test_clean_youtube_title_strips_mv_noise():
    cleaned = clean_youtube_title(
        "Pandora 潘朵拉樂隊【安全距離 Safety Distance】Official Music Video"
    )
    assert "Official" not in cleaned
    assert "安全距離" in cleaned
    assert "Safety Distance" in cleaned
    assert "Pandora" in cleaned


def test_slugify_keeps_cjk_and_ascii():
    slug = slugify("Pandora 潘朵拉樂隊【安全距離 Safety Distance】Official Music Video")
    assert "pandora" in slug
    assert "安全距離" in slug
    assert "safety-distance" in slug
    assert "official" not in slug
    assert slugify("最佳損友") == "最佳損友"
    assert slugify("R7!!!") == "r7"
    assert ":" not in slugify('a:b/c|d?e*"f')


def test_create_and_list_pack(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Test Song", source="mp3", singer="Haris")
    meta = pack.load_meta()
    assert meta.title == "Test Song"
    assert meta.singer == "Haris"
    assert meta.status == "queued"
    assert get_pack(meta.id).root == pack.root
    assert any(p.root == pack.root for p in list_packs())
    loaded = pack.public_dict()
    assert loaded["has_vocals"] is False
    assert loaded["schema_version"] == 1
    assert loaded["singer"] == "Haris"
    assert loaded["lyrics_source"] is None
    assert loaded["lyrics_method"] is None
    old = pack.load_meta().to_json()
    del old["singer"]
    restored = SongMeta.from_json(old)
    assert restored.singer == ""


def test_public_dict_lyrics_provenance_lrclib(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("LRCLIB Song", source="youtube")
    pack.lyrics.write_text(
        json.dumps(
            {
                "method": "lrclib-align",
                "source": "lrclib",
                "locked": False,
                "lrclib": {"id": 12345, "track_name": "x"},
                "lines": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    data = pack.public_dict()
    assert data["has_lyrics"] is True
    assert data["lyrics_source"] == "lrclib"
    assert data["lyrics_method"] == "lrclib-align"
    assert data["lrclib_id"] == 12345
    assert data["lyrics_locked"] is False


def test_list_packs_newest_first(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    older = create_pack("Older", source="mp3")
    time.sleep(0.02)
    newer = create_pack("Newer", source="mp3")
    ids = [p.load_meta().id for p in list_packs()]
    assert ids[0] == newer.load_meta().id
    assert older.load_meta().id in ids


def test_resolve_songs_dir_defaults_to_repo_songs(monkeypatch):
    monkeypatch.delenv("KARAOK_SONGS_DIR", raising=False)
    assert resolve_songs_dir() == (ROOT / "songs").resolve()


def test_resolve_songs_dir_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOK_SONGS_DIR", str(tmp_path / "library"))
    assert resolve_songs_dir() == (tmp_path / "library").resolve()


def test_resolve_songs_dir_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("KARAOK_SONGS_DIR", "~/karaok-songs")
    assert resolve_songs_dir() == (tmp_path / "karaok-songs").resolve()


def test_configure_songs_dir_lists_packs_from_custom_root(tmp_path):
    import engine.pack as pack_mod
    import engine.paths as paths_mod

    original = paths_mod.SONGS_DIR
    try:
        root = configure_songs_dir(str(tmp_path / "mac-songs"))
        assert root == (tmp_path / "mac-songs").resolve()
        assert paths_mod.SONGS_DIR == root
        assert pack_mod.SONGS_DIR == root
        pack = create_pack("Preview Song", source="copy")
        assert pack.root.parent == root
        assert any(p.root == pack.root for p in list_packs())
        assert get_pack(pack.load_meta().id).root == pack.root
    finally:
        configure_songs_dir(str(original))
