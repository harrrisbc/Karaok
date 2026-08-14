from __future__ import annotations

import json
import re
import traceback
from typing import Any

from engine.lyrics import (
    LANG_PRESETS,
    _device,
    _pick_model,
    _quiet_stdio,
    _silence_tqdm,
    get_cached_model,
    normalize_lang,
    normalize_whisper_model,
)
from engine.pack import SongPack

_SPACE_RE = re.compile(r"\s+")


def parse_lyric_txt(text: str) -> list[str]:
    """One lyric phrase per non-empty line. Lines starting with # are comments."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        raise ValueError("lyrics txt 係空嘅 — 每行一句歌詞")
    return lines


def _char_weight(line: str) -> int:
    return max(1, len(_SPACE_RE.sub("", line)))


def remap_lines_to_timing(
    user_lines: list[str],
    timing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep timing span from an existing timed transcript; replace text with user lines.
    Timing is split by character weight across [first.start, last.end].
    """
    if not user_lines:
        raise ValueError("no user lines")
    if not timing:
        raise ValueError("no timing segments to remap onto")

    t0 = float(timing[0]["t"])
    t1 = float(timing[-1].get("end") or timing[-1]["t"])
    if t1 <= t0:
        t1 = t0 + max(0.5, 0.4 * len(user_lines))

    weights = [_char_weight(line) for line in user_lines]
    total = float(sum(weights))
    span = t1 - t0
    cursor = t0
    out: list[dict[str, Any]] = []
    for i, (line, w) in enumerate(zip(user_lines, weights)):
        if i == len(user_lines) - 1:
            end = t1
        else:
            end = cursor + span * (w / total)
        out.append({"t": round(cursor, 3), "end": round(end, 3), "text": line})
        cursor = end
    return out


def _segments_from_stable_result(result: Any, user_lines: list[str]) -> list[dict[str, Any]]:
    segs = getattr(result, "segments", None) or []
    out: list[dict[str, Any]] = []
    for i, seg in enumerate(segs):
        text = (getattr(seg, "text", None) or "").strip()
        if not text and i < len(user_lines):
            text = user_lines[i]
        start = float(getattr(seg, "start", 0.0))
        end = float(getattr(seg, "end", start))
        if end < start:
            end = start
        out.append({"t": round(start, 3), "end": round(end, 3), "text": text or user_lines[min(i, len(user_lines) - 1)]})
    if len(out) == len(user_lines):
        for i, line in enumerate(user_lines):
            out[i]["text"] = line
        return out
    if out:
        return remap_lines_to_timing(user_lines, out)
    raise RuntimeError("stable-ts align 冇產出 segments")


def _words_from_stable_result(result: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in getattr(result, "segments", None) or []:
        for w in getattr(seg, "words", None) or []:
            text = (getattr(w, "word", None) or getattr(w, "text", None) or "").strip()
            if not text:
                continue
            start = float(getattr(w, "start", 0.0) or 0.0)
            end = float(getattr(w, "end", start) or start)
            out.append({"t": round(start, 3), "end": round(max(start, end), 3), "text": text})
    return out


def _timing_from_pack(pack: SongPack) -> list[dict[str, Any]]:
    if not pack.lyrics.exists():
        return []
    data = json.loads(pack.lyrics.read_text(encoding="utf-8"))
    lines = data.get("lines") or []
    return [
        {"t": float(x["t"]), "end": float(x.get("end") or x["t"]), "text": x.get("text") or ""}
        for x in lines
        if "t" in x
    ]


def write_lyrics_payload(
    pack: SongPack,
    *,
    lines: list[dict[str, Any]],
    words: list[dict[str, Any]] | None = None,
    method: str,
    source: str,
    lang_key: str,
    whisper_language: str,
    model_name: str | None = None,
    device: str | None = None,
    locked: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict:
    text = "".join(ln.get("text") or "" for ln in lines)
    if lang_key == "english":
        text = " ".join((ln.get("text") or "").strip() for ln in lines)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": method,
        "model": model_name,
        "device": device,
        "lang_preset": lang_key,
        "whisper_language": whisper_language,
        "language": whisper_language,
        "text": text,
        "lines": [{"t": ln["t"], "end": ln["end"], "text": ln["text"]} for ln in lines],
        "words": words or [],
        "source": source,
        "locked": bool(locked),
    }
    if extra:
        payload.update(extra)
    pack.lyrics.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def align_lyrics_from_text(
    pack: SongPack,
    text: str,
    *,
    language: str | None = None,
    model_name: str | None = None,
    prefer_remap: bool = False,
    source: str = "user-txt",
    locked: bool = True,
    extra: dict[str, Any] | None = None,
    method_override: str | None = None,
) -> dict:
    """
    Force-align a user lyric txt (one phrase per line) onto vocals.wav.

    Uses stable-ts when available; otherwise remaps onto existing lyrics.json timing.
    """
    if not pack.vocals.exists():
        raise FileNotFoundError(f"missing vocals: {pack.vocals}")

    user_lines = parse_lyric_txt(text)
    meta = pack.load_meta()
    lang_key = normalize_lang(language or getattr(meta, "lyrics_lang", None) or "cantonese")
    preset = LANG_PRESETS[lang_key]
    if meta.lyrics_lang != lang_key:
        meta.lyrics_lang = lang_key
        pack.save_meta(meta)

    model_name = _pick_model(normalize_whisper_model(model_name), preset["min_model"])
    whisper_language = preset["whisper_language"]
    device = _device()
    method = method_override or "stable-ts-align"
    timed: list[dict[str, Any]]
    words: list[dict[str, Any]] = []

    if prefer_remap:
        existing = _timing_from_pack(pack)
        if not existing:
            raise RuntimeError("prefer_remap 但 pack 未有 lyrics timing — 先 Analyze 或者關 prefer_remap")
        timed = remap_lines_to_timing(user_lines, existing)
        method = method_override or "remap-existing-timing"
    else:
        try:
            import stable_whisper
        except ImportError as exc:
            existing = _timing_from_pack(pack)
            if not existing:
                raise RuntimeError(
                    "未安裝 stable-ts，而且 pack 未有 lyrics timing。"
                    " pip install stable-ts 或者先 Analyze 一次再 Align。"
                ) from exc
            timed = remap_lines_to_timing(user_lines, existing)
            method = method_override or "remap-existing-timing"
        else:
            try:
                with _silence_tqdm():
                    model = get_cached_model(model_name, device, kind="stable")
                script = "\n".join(user_lines)
                with _quiet_stdio():
                    result = model.align(
                        str(pack.vocals),
                        script,
                        language=whisper_language,
                        original_split=True,
                        fast_mode=True,
                    )
                if result is None:
                    raise RuntimeError("stable-ts align 失敗（result=None）")
                timed = _segments_from_stable_result(result, user_lines)
                words = _words_from_stable_result(result)
            except Exception:
                (pack.root / "lyrics.align.error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                raise

    payload = write_lyrics_payload(
        pack,
        lines=timed,
        words=words,
        method=method,
        source=source,
        lang_key=lang_key,
        whisper_language=whisper_language,
        model_name=model_name,
        device=device,
        locked=locked,
        extra=extra,
    )
    err = pack.root / "lyrics.align.error.txt"
    if err.exists():
        err.unlink()
    return payload


MAX_LRC_OFFSET_SEC = 45.0
MIN_LRC_OFFSET_SEC = 0.4


def lrc_offset_for_pack(pack: SongPack, lines: list[dict[str, Any]]) -> float:
    """Seconds to shift LRC so its first line meets real vocal onset.

    LRCLIB timings come from someone else's release. Even a duration match can
    sit on a different intro length, which puts every line ahead of / behind the
    music. Anchor on our own vocals instead of trusting the LRC clock.
    """
    if not lines or not pack.vocals.exists():
        return 0.0
    try:
        from engine.lyrics import _load_vocals_16k, vocal_onset_sec

        onset = vocal_onset_sec(_load_vocals_16k(pack.vocals))
    except Exception:
        return 0.0
    if onset <= 0:
        return 0.0
    first = float(lines[0].get("t") or 0.0)
    delta = onset - first
    if abs(delta) < MIN_LRC_OFFSET_SEC or abs(delta) > MAX_LRC_OFFSET_SEC:
        return 0.0
    return round(delta, 3)


def apply_lrc_to_pack(
    pack: SongPack,
    lrc_text: str,
    *,
    mode: str = "align",
    language: str | None = None,
    model_name: str | None = None,
    source: str = "lrclib",
    locked: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict:
    from engine.lrc import normalize_lrc

    meta = pack.load_meta()
    lang_key = normalize_lang(language or meta.lyrics_lang)
    norm = normalize_lrc(lrc_text, lang=lang_key, title=meta.title or "")
    lines = norm["lines"]
    if not lines:
        raise ValueError("LRC 冇可用歌詞行（過濾後係空）")
    extra = dict(extra or {})
    if "lrclib" in extra and extra["lrclib"] is not None:
        extra["lrclib"] = {**extra["lrclib"], "converted": extra["lrclib"].get("converted") or norm.get("converted")}
    else:
        extra["lrclib"] = {
            "id": None,
            "track_name": meta.title,
            "artist_name": "",
            "album_name": "",
            "duration": None,
            "matched_by": "paste",
            "converted": norm.get("converted"),
        }

    if mode == "trust-lrc":
        from engine.lrc import shift_lines

        offset = lrc_offset_for_pack(pack, lines)
        if offset:
            lines = shift_lines(lines, offset)
        words: list[dict[str, Any]] = []
        for ln in lines:
            words.extend(ln.get("words") or [])
        preset = LANG_PRESETS[lang_key]
        extra["lrc_offset_sec"] = offset
        return write_lyrics_payload(
            pack,
            lines=lines,
            words=words,
            method="lrclib-direct",
            source=source,
            lang_key=lang_key,
            whisper_language=preset["whisper_language"],
            model_name=model_name,
            device=_device(),
            locked=locked,
            extra=extra,
        )

    return align_lyrics_from_text(
        pack,
        norm["txt"],
        language=lang_key,
        model_name=model_name,
        source=source,
        locked=locked,
        extra=extra,
        method_override="lrclib-align",
    )
