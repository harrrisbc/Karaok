from __future__ import annotations

import json
import os
import re
import threading
import traceback
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from typing import Iterator

from engine.pack import SongPack

# User-facing langs → Whisper kwargs.
# Cantonese uses zh (not yue): yue often collapses on stock Whisper checkpoints.
# No initial_prompt — prompts leak into lyrics and make Whisper invent text.
LANG_PRESETS: dict[str, dict] = {
    "cantonese": {
        "label": "Cantonese / 粵語",
        "whisper_language": "zh",
        "min_model": "small",
    },
    "chinese": {
        "label": "Chinese / 普通話中文",
        "whisper_language": "zh",
        "min_model": "small",
    },
    "english": {
        "label": "English",
        "whisper_language": "en",
        "min_model": "base",
    },
}

DEFAULT_LANG = "cantonese"
DEFAULT_MODEL = "small"
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "turbo")
_MODEL_RANK = WHISPER_MODELS

# Leftover prompt fragments if an older run leaked into decode.
_PROMPT_LEAK = re.compile(
    r"^(以下係粵語歌詞[，,]?|用繁體中文[：:]?|以下是中文歌词[：:]?|詞[，,]?用繁體中文[：:]?)\s*"
)

# Intro cards / YouTube metadata Whisper invents during instrumental.
_CREDIT_LINE = re.compile(
    r"("
    r"\bunknown\b|"
    r"songwriter|lyricist|composer|"
    r"written\s+by|lyrics\s+by|music\s+by|produced\s+by|performed\s+by|"
    r"official\s+(music\s+)?video|"
    r"作詞|作曲|編曲|编曲|填詞|填词|監製|监制|"
    r"詞\s*[／/]\s*曲|词\s*[／/]\s*曲|"
    r"请不吝|不吝点赞|點贊|点赞|订阅|明镜|點點"
    r")",
    re.IGNORECASE,
)
_TITLE_CARD = re.compile(r"^《[^》]{2,80}》$")
_MAX_INTRO_CREDIT_SEC = 28.0
_MAX_REPEAT_RUN = 2


def normalize_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    key = lang.strip().lower()
    aliases = {
        "yue": "cantonese",
        "zh-yue": "cantonese",
        "hk": "cantonese",
        "粵語": "cantonese",
        "zh": "chinese",
        "cmn": "chinese",
        "mandarin": "chinese",
        "中文": "chinese",
        "en": "english",
        "eng": "english",
    }
    key = aliases.get(key, key)
    if key not in LANG_PRESETS:
        raise ValueError(f"unsupported lang: {lang}. use cantonese|chinese|english")
    return key


def lyrics_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("whisper") is not None
    except Exception:
        return False


def _device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def normalize_whisper_model(name: str | None) -> str | None:
    if name is None:
        return None
    key = name.strip()
    if not key:
        return None
    if key not in WHISPER_MODELS:
        raise ValueError(
            f"unsupported whisper model: {name}. use {'|'.join(WHISPER_MODELS)}"
        )
    return key


def _pick_model(requested: str | None, min_model: str) -> str:
    raw = requested if requested is not None else os.environ.get("KARAOK_WHISPER_MODEL")
    name = (raw or DEFAULT_MODEL).strip()
    try:
        if _MODEL_RANK.index(name) < _MODEL_RANK.index(min_model):
            return min_model
    except ValueError:
        return name
    return name


def is_large_whisper(model_name: str) -> bool:
    return model_name in {"large", "large-v2", "large-v3"}


def decode_options(model_name: str, device: str) -> dict:
    """Greedy decode on large checkpoints — beam search OOMs an 8GB laptop GPU.

    Quiet intros are skipped via clip_timestamps (vocal onset), not by lowering
    no_speech — that made large-v3 invent song-title / Unknown / 作詞 cards.
    """
    large = is_large_whisper(model_name)
    opts = {
        "verbose": None,
        "fp16": device == "cuda",
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "beam_size": 1 if large else 5,
        "compression_ratio_threshold": 2.4,
        "logprob_threshold": -0.8 if large else -1.0,
        "no_speech_threshold": 0.55 if large else 0.6,
    }
    if large:
        opts["hallucination_silence_threshold"] = 2.0
    return opts


def release_cuda() -> None:
    """Drop any cached Whisper/stable-ts model, then free CUDA blocks for Demucs."""
    drop_model_cache()


_model_lock = threading.Lock()
_cached_model = None
_cached_key: tuple[str, str, str] | None = None


def drop_model_cache() -> None:
    """Drop the cached model reference and empty the CUDA cache."""
    global _cached_model, _cached_key
    with _model_lock:
        _cached_model = None
        _cached_key = None
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def get_cached_model(name: str, device: str, kind: str = "whisper"):
    """Return a loaded model; reuse if (kind, name, device) matches."""
    global _cached_model, _cached_key
    key = (kind, name, device)
    with _model_lock:
        if _cached_key == key and _cached_model is not None:
            return _cached_model
        _cached_model = None
        _cached_key = None
    # Free VRAM before loading a different checkpoint (or after a miss).
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

    if kind == "stable":
        import stable_whisper

        model = stable_whisper.load_model(name, device=device)
    elif kind == "whisper":
        import whisper

        model = whisper.load_model(name, device=device)
    else:
        raise ValueError(f"unsupported model kind: {kind}")

    with _model_lock:
        _cached_model = model
        _cached_key = key
        return _cached_model


def _clean_text(text: str) -> str:
    text = text.strip()
    text = _PROMPT_LEAK.sub("", text).strip()
    return text


def is_credit_hallucination(text: str, t: float = 0.0, title: str = "") -> bool:
    """True for YouTube credit cards / title overlays Whisper invents."""
    raw = (text or "").strip()
    if not raw:
        return True
    if _CREDIT_LINE.search(raw):
        return True
    if t <= _MAX_INTRO_CREDIT_SEC and _TITLE_CARD.match(raw):
        return True
    if title:
        compact = re.sub(r"[\s《》\[\]【】\-—_|]+", "", raw).lower()
        tcompact = re.sub(r"[\s《》\[\]【】\-—_|]+", "", title).lower()
        if t <= _MAX_INTRO_CREDIT_SEC and tcompact and compact == tcompact:
            return True
    return False


def filter_lyric_segments(segments: list[dict], title: str = "") -> list[dict]:
    """Drop intro credits, low-confidence silence text, and loop spam."""
    kept: list[dict] = []
    run_text = ""
    run_n = 0
    for seg in segments:
        text = _clean_text(seg.get("text") or "")
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        nsp = float(seg.get("no_speech_prob") or 0.0)
        lp = float(seg.get("avg_logprob") or 0.0)
        if is_credit_hallucination(text, t=start, title=title):
            continue
        if nsp > 0.75 and lp < -0.6:
            continue
        if text == run_text:
            run_n += 1
            if run_n > _MAX_REPEAT_RUN:
                continue
        else:
            run_text = text
            run_n = 1
        kept.append({**seg, "text": text})
    return kept


def vocal_onset_sec(y, sr: int = 16000, pad: float = 0.35) -> float:
    """First sustained vocal energy, minus a small pad so the first syllable stays."""
    import librosa
    import numpy as np

    hop = 512
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    if len(rms) == 0:
        return 0.0
    p20 = float(np.percentile(rms, 20))
    p80 = float(np.percentile(rms, 80))
    thr = p20 + 0.35 * max(p80 - p20, 1e-9)
    need = max(1, int(0.18 * sr / hop))
    run = 0
    for i, v in enumerate(rms):
        if float(v) >= thr:
            run += 1
            if run >= need:
                t = (i - need + 1) * hop / sr - pad
                return round(max(0.0, t), 3)
        else:
            run = 0
    return 0.0


@contextmanager
def _silence_tqdm() -> Iterator[None]:
    """tqdm on a Windows uvicorn job thread raises OSError Errno 22."""
    import tqdm as tqdm_mod

    orig = tqdm_mod.tqdm

    def quiet(*args, **kwargs):
        kwargs["disable"] = True
        return orig(*args, **kwargs)

    tqdm_mod.tqdm = quiet
    whisper_mod = None
    orig_whisper = None
    try:
        import whisper as whisper_mod

        orig_whisper = whisper_mod.tqdm
        whisper_mod.tqdm = quiet
    except Exception:
        pass
    try:
        yield
    finally:
        tqdm_mod.tqdm = orig
        if whisper_mod is not None and orig_whisper is not None:
            whisper_mod.tqdm = orig_whisper


@contextmanager
def _quiet_stdio() -> Iterator[None]:
    """Windows job threads crash on tqdm / warnings / Unicode console writes (Errno 22)."""
    buf = StringIO()
    with _silence_tqdm(), redirect_stdout(buf), redirect_stderr(buf), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _load_vocals_16k(path) -> object:
    import librosa
    import numpy as np

    y, _ = librosa.load(str(path), sr=16000, mono=True)
    return np.asarray(y, dtype=np.float32)


def extract_lyrics(
    pack: SongPack,
    *,
    model_name: str | None = None,
    language: str | None = None,
) -> dict:
    """Transcribe vocals with OpenAI Whisper (word timestamps when available)."""
    if not pack.vocals.exists():
        raise FileNotFoundError(f"missing vocals: {pack.vocals}")
    if not lyrics_available():
        raise RuntimeError("openai-whisper 未安裝。pip install openai-whisper")

    meta = pack.load_meta()
    lang_key = normalize_lang(language or getattr(meta, "lyrics_lang", None) or DEFAULT_LANG)
    preset = LANG_PRESETS[lang_key]
    if meta.lyrics_lang != lang_key:
        meta.lyrics_lang = lang_key
        pack.save_meta(meta)

    model_name = _pick_model(normalize_whisper_model(model_name), preset["min_model"])
    device = _device()
    audio = _load_vocals_16k(pack.vocals)
    decode = decode_options(model_name, device)
    decode["language"] = preset["whisper_language"]
    onset = vocal_onset_sec(audio)
    if onset > 0.4:
        decode["clip_timestamps"] = [onset]

    try:
        with _silence_tqdm():
            model = get_cached_model(model_name, device, kind="whisper")
        with _quiet_stdio():
            try:
                result = model.transcribe(audio, word_timestamps=True, **decode)
            except (OSError, RuntimeError, TypeError):
                decode.pop("hallucination_silence_threshold", None)
                result = model.transcribe(audio, word_timestamps=False, **decode)
    except Exception:
        (pack.root / "lyrics.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    else:
        err_path = pack.root / "lyrics.error.txt"
        if err_path.exists():
            err_path.unlink()

    lines: list[dict] = []
    words: list[dict] = []
    kept = filter_lyric_segments(list(result.get("segments") or []), title=meta.title or "")
    for seg in kept:
        text = seg.get("text") or ""
        lines.append(
            {
                "t": round(float(seg["start"]), 3),
                "end": round(float(seg["end"]), 3),
                "text": text,
            }
        )
        for w in seg.get("words") or []:
            wtext = _clean_text(w.get("word") or "")
            if not wtext:
                continue
            words.append(
                {
                    "t": round(float(w["start"]), 3),
                    "end": round(float(w["end"]), 3),
                    "text": wtext,
                }
            )

    full_text = " ".join(ln["text"] for ln in lines)
    payload = {
        "schema_version": 1,
        "method": "openai-whisper",
        "model": model_name,
        "device": device,
        "lang_preset": lang_key,
        "whisper_language": preset["whisper_language"],
        "language": result.get("language"),
        "vocal_onset": onset,
        "text": full_text,
        "lines": lines,
        "words": words,
        "source": "whisper",
        "locked": False,
    }
    pack.lyrics.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload
