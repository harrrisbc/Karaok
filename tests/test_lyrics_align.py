from engine.lyrics_align import parse_lyric_txt, remap_lines_to_timing


def test_parse_lyric_txt_skips_blank_and_comments():
    text = """
# title
第一句

第二句
第三句
"""
    assert parse_lyric_txt(text) == ["第一句", "第二句", "第三句"]


def test_parse_lyric_txt_empty_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_lyric_txt("\n# only comment\n")


def test_remap_lines_to_timing_preserves_span_and_text():
    timing = [
        {"t": 10.0, "end": 12.0, "text": "wrong"},
        {"t": 12.0, "end": 20.0, "text": "also wrong"},
    ]
    lines = remap_lines_to_timing(["短", "這一句比較長一些"], timing)
    assert len(lines) == 2
    assert lines[0]["text"] == "短"
    assert lines[1]["text"] == "這一句比較長一些"
    assert lines[0]["t"] == 10.0
    assert lines[-1]["end"] == 20.0
    assert lines[0]["end"] < lines[1]["end"]
    # longer line gets more duration
    assert (lines[1]["end"] - lines[1]["t"]) > (lines[0]["end"] - lines[0]["t"])
