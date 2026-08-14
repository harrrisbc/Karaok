import pytest

from engine.lyrics import LANG_PRESETS, normalize_lang


def test_normalize_lang_presets():
    assert normalize_lang("cantonese") == "cantonese"
    assert normalize_lang("chinese") == "chinese"
    assert normalize_lang("english") == "english"
    assert normalize_lang(None) == "cantonese"
    assert normalize_lang("yue") == "cantonese"
    assert normalize_lang("en") == "english"
    assert normalize_lang("zh") == "chinese"


def test_cantonese_uses_zh_not_yue():
    assert LANG_PRESETS["cantonese"]["whisper_language"] == "zh"
    assert LANG_PRESETS["chinese"]["whisper_language"] == "zh"
    assert LANG_PRESETS["english"]["whisper_language"] == "en"
    assert "initial_prompt" not in LANG_PRESETS["cantonese"]
    assert "initial_prompt" not in LANG_PRESETS["chinese"]


def test_pick_model_upgrades_tiny_for_cantonese():
    from engine.lyrics import _pick_model

    assert _pick_model("tiny", "small") == "small"
    assert _pick_model("medium", "small") == "medium"
    assert _pick_model("large-v3", "small") == "large-v3"


def test_default_model_is_small(monkeypatch):
    from engine.lyrics import _pick_model

    monkeypatch.delenv("KARAOK_WHISPER_MODEL", raising=False)
    assert _pick_model(None, "small") == "small"


def test_normalize_whisper_model():
    from engine.lyrics import normalize_whisper_model

    assert normalize_whisper_model(None) is None
    assert normalize_whisper_model("  ") is None
    assert normalize_whisper_model("large-v3") == "large-v3"
    with pytest.raises(ValueError):
        normalize_whisper_model("huge")


def test_silence_tqdm_disables_bar():
    from engine.lyrics import _silence_tqdm
    import tqdm

    with _silence_tqdm():
        bar = tqdm.tqdm(total=3)
        assert bar.disable is True
        bar.update(3)
        bar.close()


def test_large_whisper_uses_greedy_beam():
    from engine.lyrics import decode_options, is_large_whisper

    assert is_large_whisper("large-v3")
    assert not is_large_whisper("small")
    assert decode_options("large-v3", "cuda")["beam_size"] == 1
    assert decode_options("small", "cuda")["beam_size"] == 5
    assert decode_options("large-v3", "cuda")["no_speech_threshold"] == 0.55
    assert decode_options("small", "cuda")["no_speech_threshold"] == 0.6
    assert decode_options("large-v3", "cuda")["hallucination_silence_threshold"] == 2.0
    assert "hallucination_silence_threshold" not in decode_options("small", "cuda")
    assert decode_options("medium", "cuda")["fp16"] is True
    assert decode_options("small", "cpu")["fp16"] is False


def test_credit_hallucination_lines():
    from engine.lyrics import is_credit_hallucination

    assert is_credit_hallucination("Unknown", t=3.0)
    assert is_credit_hallucination("Songwriter: Lee", t=1.0)
    assert is_credit_hallucination("作詞：林夕 作曲：雷頌德", t=2.0)
    assert is_credit_hallucination("《仍然沒有遇到那位跟我絕配的戀人》", t=16.0)
    assert is_credit_hallucination("请不吝点赞 订阅 转发", t=200.0)
    assert not is_credit_hallucination("我靠近 能否允許我跟隨", t=18.0)
    assert not is_credit_hallucination("從來未相識 已不再", t=58.0)


def test_drop_intro_credits_keeps_sung_lines():
    from engine.lyrics import filter_lyric_segments

    segs = [
        {"start": 1.0, "end": 3.0, "text": "Unknown", "no_speech_prob": 0.9, "avg_logprob": -1.2},
        {"start": 3.0, "end": 6.0, "text": "作詞 林夕", "no_speech_prob": 0.4, "avg_logprob": -0.4},
        {"start": 6.0, "end": 8.0, "text": "Official Music Video", "no_speech_prob": 0.3, "avg_logprob": -0.3},
        {"start": 18.0, "end": 21.0, "text": "望背面已觸電", "no_speech_prob": 0.1, "avg_logprob": -0.2, "words": [{"start": 18.0, "end": 21.0, "word": "望背面已觸電"}]},
    ]
    kept = filter_lyric_segments(segs, title="Safety Distance")
    assert [s["text"] for s in kept] == ["望背面已觸電"]


def test_collapse_repeated_loop_lines():
    from engine.lyrics import filter_lyric_segments

    segs = [{"start": i * 1.2, "end": i * 1.2 + 1.0, "text": "祝你生日快樂", "no_speech_prob": 0.1, "avg_logprob": -0.2} for i in range(8)]
    segs.append({"start": 32.0, "end": 35.0, "text": "做策劃之男", "no_speech_prob": 0.1, "avg_logprob": -0.2})
    kept = filter_lyric_segments(segs)
    texts = [s["text"] for s in kept]
    assert texts.count("祝你生日快樂") <= 2
    assert texts[-1] == "做策劃之男"


def test_release_cuda_does_not_raise():
    from engine.lyrics import release_cuda

    release_cuda()


def test_bad_lang():
    with pytest.raises(ValueError):
        normalize_lang("japanese")
