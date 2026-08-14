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
    normalize_lang,
    normalize_whisper_model,
    release_cuda,
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


def align_lyrics_from_text(
    pack: SongPack,
    text: str,
    *,
    language: str | None = None,
    model_name: str | None = None,
    prefer_remap: bool = False,
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
    method = "stable-ts-align"
    timed: list[dict[str, Any]]

    if prefer_remap:
        existing = _timing_from_pack(pack)
        if not existing:
            raise RuntimeError("prefer_remap 但 pack 未有 lyrics timing — 先 Analyze 或者關 prefer_remap")
        timed = remap_lines_to_timing(user_lines, existing)
        method = "remap-existing-timing"
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
            method = "remap-existing-timing"
        else:
            model = None
            try:
                with _silence_tqdm():
                    model = stable_whisper.load_model(model_name, device=device)
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
            except Exception:
                (pack.root / "lyrics.align.error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                raise
            finally:
                del model
                release_cuda()

    words: list[dict[str, Any]] = []
    payload = {
        "schema_version": 1,
        "method": method,
        "model": model_name,
        "device": device,
        "lang_preset": lang_key,
        "whisper_language": whisper_language,
        "language": whisper_language,
        "text": "".join(user_lines) if lang_key != "english" else " ".join(user_lines),
        "lines": timed,
        "words": words,
        "source": "user-txt",
    }
    pack.lyrics.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    err = pack.root / "lyrics.align.error.txt"
    if err.exists():
        err.unlink()
    return payload
