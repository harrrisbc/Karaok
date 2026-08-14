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
    old = pack.load_meta().to_json()
    del old["singer"]
    restored = SongMeta.from_json(old)
    assert restored.singer == ""
