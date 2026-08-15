import json

from fastapi.testclient import TestClient

from engine.pack import create_pack
from engine.paths import SONGS_DIR


def test_lrclib_search_and_apply_api(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    monkeypatch.setattr("server.app.SONGS_DIR", tmp_path)

    pack = create_pack("陳健安 - 戀愛腦之死", source="youtube")
    pack.vocals.write_bytes(b"RIFF....")  # existence only for apply gate
    (pack.root / "melody.json").write_text(
        json.dumps({"duration": 305.0, "notes": []}),
        encoding="utf-8",
    )

    fake = {
        "auto": None,
        "candidates": [
            {
                "id": 4242,
                "track_name": "戀愛腦之死",
                "artist_name": "陳健安",
                "album_name": "X",
                "duration": 305,
                "instrumental": False,
                "has_synced": True,
                "matched_by": "search-title",
                "duration_delta": 0.2,
                "auto_apply": False,
                "record": {
                    "id": 4242,
                    "trackName": "戀愛腦之死",
                    "artistName": "陳健安",
                    "syncedLyrics": "[00:10.00]萬千種批判",
                },
            }
        ],
        "attempts": ["search-title"],
    }

    monkeypatch.setattr("server.app.search_lrclib", lambda **kwargs: fake)

    started = {}

    class FakeJob:
        def public_dict(self):
            return {"id": "job-1", "kind": "lyrics-lrclib", "status": "queued", "step": "queued"}

    def fake_start(pack_id, **kwargs):
        started.update({"pack_id": pack_id, **kwargs})
        return FakeJob()

    monkeypatch.setattr("server.app.start_lyrics_lrclib", fake_start)
    monkeypatch.setattr("server.app.runner", type("R", (), {"active": lambda self: None})())

    from server.app import app

    client = TestClient(app)
    searched = client.get(
        f"/api/lyrics/lrclib/search/{pack.load_meta().id}",
        params={"title": "戀愛腦之死", "artist": "陳健安"},
    )
    assert searched.status_code == 200
    body = searched.json()
    assert body["candidates"][0]["id"] == 4242
    assert "record" not in body["candidates"][0]
    assert (pack.root / "lrclib.raw.json").exists()

    applied = client.post(
        f"/api/lyrics/lrclib/apply/{pack.load_meta().id}",
        json={"id": 4242, "mode": "trust-lrc", "force": True},
    )
    assert applied.status_code == 200
    assert started["pack_id"] == pack.load_meta().id
    assert started["lrclib_id"] == 4242
    assert started["mode"] == "trust-lrc"
    assert started["force"] is True
    assert started["whisper_model"] == "small"

    aligned = client.post(
        f"/api/lyrics/lrclib/apply/{pack.load_meta().id}",
        json={"id": 4242, "mode": "align", "force": True, "whisper_model": "small"},
    )
    assert aligned.status_code == 200
    assert started["mode"] == "align"
    assert started["whisper_model"] == "small"
