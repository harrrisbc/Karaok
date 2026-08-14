from engine.ingest import VIDEO_SUFFIXES, YT_MV_FORMAT, attach_mv, download_youtube_mv, youtube_mv_flags
from engine.pack import create_pack


def test_youtube_mv_flags_target_mp4():
    flags = youtube_mv_flags(r"C:\songs\x\mv.%(ext)s")
    assert "-f" in flags
    assert YT_MV_FORMAT in flags
    assert "--merge-output-format" in flags
    assert "mp4" in flags
    assert any("mv.%(ext)s" in part for part in flags)


def test_attach_mv_copies_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Clip", source="file")
    src = tmp_path / "in.mp4"
    src.write_bytes(b"video-bytes")
    dest = attach_mv(pack, src)
    assert dest == pack.mv
    assert pack.mv.read_bytes() == b"video-bytes"
    assert pack.public_dict()["has_mv"] is True


def test_attach_mv_rejects_non_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Clip", source="file")
    src = tmp_path / "in.mov"
    src.write_bytes(b"x")
    try:
        attach_mv(pack, src)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert ".mp4" in VIDEO_SUFFIXES


def test_download_youtube_mv_swallows_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Clip", source="youtube")

    def boom(cmd):
        raise RuntimeError("network")

    monkeypatch.setattr("engine.ingest.run", boom)
    monkeypatch.setattr("engine.ingest._yt_dlp", lambda: ["yt-dlp"])
    assert download_youtube_mv(pack, "https://youtu.be/x") is False
    assert pack.mv.exists() is False
