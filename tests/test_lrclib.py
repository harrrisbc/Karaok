from engine.lrclib import line_count_sane, lyrics_locked, search_lrclib, split_artist_title, clean_track_query


def _rec(**kwargs):
    base = {
        "id": 1,
        "trackName": "囍帖街",
        "artistName": "謝安琪",
        "albumName": "Binary",
        "duration": 247,
        "instrumental": False,
        "plainLyrics": "x",
        "syncedLyrics": "[00:12.00]忘掉种过的花",
    }
    base.update(kwargs)
    return base


def test_clean_and_split_title():
    assert "囍帖街" in clean_track_query("謝安琪 - 囍帖街 (Official Music Video)")
    artist, track = split_artist_title("陳奕迅 – 富士山下")
    assert artist == "陳奕迅"
    assert track == "富士山下"


def test_exact_get_auto_applies(monkeypatch):
    hit = _rec(id=11, duration=180)

    def http(url: str):
        if "/api/get?" in url:
            return 200, hit
        raise AssertionError(url)

    result = search_lrclib(title="囍帖街", artist="謝安琪", duration=180.4, http=http)
    assert result["auto"] is not None
    assert result["auto"]["id"] == 11
    assert result["auto"]["auto_apply"] is True
    assert result["auto"]["matched_by"] == "get"


def test_instrumental_rejected_then_search_candidate():
    inst = _rec(id=1, instrumental=True, syncedLyrics="[00:01.00]x")
    # Far from query duration so it stays candidate-only (no auto).
    good = _rec(id=2, duration=200)

    def http(url: str):
        if "/api/get?" in url:
            return 200, inst
        if "/api/search?" in url:
            return 200, [inst, good]
        raise AssertionError(url)

    result = search_lrclib(title="囍帖街", artist="謝安琪", duration=247.0, http=http)
    assert result["auto"] is None
    ids = [c["id"] for c in result["candidates"]]
    assert 1 not in ids
    assert 2 in ids
    assert all(c["auto_apply"] is False for c in result["candidates"])


def test_title_only_auto_applies_when_duration_near():
    near = _rec(id=44, trackName="1874", artistName="陳奕迅", duration=242.0)
    far = _rec(id=45, trackName="1874", artistName="Other", duration=200.0)

    def http(url: str):
        # No artist → /api/get is skipped
        if "/api/search?" in url:
            return 200, [far, near]
        raise AssertionError(url)

    result = search_lrclib(title="1874", artist="", duration=241.92, http=http)
    assert result["auto"] is not None
    assert result["auto"]["id"] == 44
    assert result["auto"]["auto_apply"] is True
    assert "auto-duration" in result["attempts"][-1]


def test_out_of_tolerance_is_candidate_not_auto():
    far = _rec(id=9, duration=90)

    def http(url: str):
        if "/api/get?" in url:
            return 404, None
        if "/api/search?" in url:
            return 200, [far]
        raise AssertionError(url)

    result = search_lrclib(title="囍帖街", artist="謝安琪", duration=247.0, http=http)
    assert result["auto"] is None
    assert result["candidates"][0]["id"] == 9
    assert result["candidates"][0]["duration_delta"] == 157.0


def test_network_error_returns_empty_not_raise():
    def http(url: str):
        raise TimeoutError("timed out")

    result = search_lrclib(title="x", artist="y", duration=100, http=http)
    assert result["auto"] is None
    assert result["candidates"] == []
    assert "network" in result["attempts"][-1]


def test_shift_lines_moves_lines_and_words():
    from engine.lrc import shift_lines

    lines = [{"t": 1.0, "end": 3.0, "text": "a", "words": [{"t": 1.0, "end": 2.0, "text": "a"}]}]
    later = shift_lines(lines, 5.0)
    assert later[0]["t"] == 6.0
    assert later[0]["end"] == 8.0
    assert later[0]["words"][0]["t"] == 6.0
    # Never go negative when the LRC needs pulling earlier than zero.
    earlier = shift_lines(lines, -9.0)
    assert earlier[0]["t"] == 0.0
    assert earlier[0]["end"] >= 0.0


def test_lrc_offset_ignores_tiny_and_absurd_deltas(tmp_path, monkeypatch):
    from engine.pack import SongPack
    import engine.lyrics_align as la

    pack = SongPack(tmp_path / "p")
    pack.root.mkdir()
    pack.vocals.write_bytes(b"x")
    lines = [{"t": 10.0, "end": 12.0, "text": "a", "words": []}]

    monkeypatch.setattr(la, "_device", lambda: "cpu", raising=False)
    import engine.lyrics as lyr

    monkeypatch.setattr(lyr, "_load_vocals_16k", lambda p: [0.0])

    monkeypatch.setattr(lyr, "vocal_onset_sec", lambda y: 10.2)
    assert la.lrc_offset_for_pack(pack, lines) == 0.0

    monkeypatch.setattr(lyr, "vocal_onset_sec", lambda y: 200.0)
    assert la.lrc_offset_for_pack(pack, lines) == 0.0

    monkeypatch.setattr(lyr, "vocal_onset_sec", lambda y: 17.5)
    assert la.lrc_offset_for_pack(pack, lines) == 7.5


def test_line_count_sane_and_lock(tmp_path, monkeypatch):
    from engine.pack import SongPack

    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    pack = SongPack(tmp_path / "p")
    pack.root.mkdir()
    assert lyrics_locked(pack) is False
    (pack.root / "lyrics.json").write_text(
        '{"source":"user-txt","lines":[]}', encoding="utf-8"
    )
    assert lyrics_locked(pack) is True
    assert line_count_sane(4, 2) is True
    assert line_count_sane(20, 3) is False
    assert line_count_sane(20, 18) is True
