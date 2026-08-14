from engine.pack import SongMeta, create_pack, get_pack, list_packs, slugify


def test_slugify_strips_non_ascii():
    assert slugify("Pandora — 醴լiwz Safety Distance") == "pandora-iwz-safety-distance"
    assert slugify("你好世界") == "song"
    assert slugify("R7!!!") == "r7"


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
