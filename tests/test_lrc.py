from engine.lrc import filter_lrc_lines, normalize_lrc, parse_lrc


SAMPLE_XITIE = """[ti:囍帖街]
[ar:謝安琪]
[al:]
[offset:0]
[00:12.40]忘掉种过的花重新的出发
[00:18.10]完全无牵挂
"""

SAMPLE_1874 = """[00:09.10]1874
[00:15.17]作詞：黃偉文 作曲：王雙駿
[00:21.00]仍然沒有遇到
[01:02.10][02:10.20]同一句兩次
"""

SAMPLE_ENHANCED = """[00:10.00]hello <00:10.40>world <00:10.90>again
"""

SAMPLE_CRLF = "[00:01.00]one\r\n[00:02.50]two\r\n"


def test_parse_multi_timestamp_and_offset_and_crlf():
    parsed = parse_lrc(SAMPLE_1874)
    texts = [ln["text"] for ln in parsed["lines"]]
    assert "仍然沒有遇到" in texts
    dual = [ln for ln in parsed["lines"] if ln["text"] == "同一句兩次"]
    assert len(dual) == 2
    assert dual[0]["t"] == 62.1
    assert dual[1]["t"] == 130.2

    crlf = parse_lrc(SAMPLE_CRLF)
    assert [ln["text"] for ln in crlf["lines"]] == ["one", "two"]

    shifted = parse_lrc("[offset:500]\n[00:01.00]hi\n")
    assert abs(shifted["lines"][0]["t"] - 1.5) < 1e-6
    assert shifted["offset_ms"] == 500.0


def test_parse_enhanced_word_tags():
    parsed = parse_lrc(SAMPLE_ENHANCED)
    assert len(parsed["lines"]) == 1
    words = parsed["lines"][0]["words"]
    assert [w["text"] for w in words] == ["hello", "world", "again"]
    assert abs(words[0]["t"] - 10.0) < 1e-6
    assert abs(words[1]["t"] - 10.4) < 1e-6


def test_parse_malformed_timestamp_skipped():
    parsed = parse_lrc("[99:aa.xx]nope\n[00:03.00]ok\n")
    assert [ln["text"] for ln in parsed["lines"]] == ["ok"]


def test_filter_1874_credits():
    parsed = parse_lrc(SAMPLE_1874)
    kept = filter_lrc_lines(parsed["lines"], title="1874")
    assert [ln["text"] for ln in kept] == ["仍然沒有遇到", "同一句兩次", "同一句兩次"]


def test_s2hk_xitie_sample():
    opencc = pytest_import_opencc()
    if not opencc:
        import pytest

        pytest.skip("opencc-python-reimplemented not installed")
    norm = normalize_lrc(SAMPLE_XITIE, lang="cantonese", title="囍帖街")
    assert norm["converted"] == "s2hk"
    assert "忘掉種過的花重新的出發" in [ln["text"] for ln in norm["lines"]]
    assert "完全無牽掛" in [ln["text"] for ln in norm["lines"]]


def pytest_import_opencc():
    try:
        import opencc  # noqa: F401

        return True
    except ImportError:
        return False
