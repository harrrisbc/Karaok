from __future__ import annotations

import re
from typing import Any

from engine.lyrics import _clean_text, is_credit_hallucination

_META = re.compile(r"^\[(ti|ar|al|au|by|offset|length|re|ve):([^\]]*)\]\s*$", re.I)
_TS = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
_WORD = re.compile(r"<(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?>")
_BLANK = re.compile(r"\s+")


def _stamp_to_sec(m: re.Match[str]) -> float | None:
    try:
        mins = int(m.group(1))
        secs = int(m.group(2))
        frac = m.group(3) or "0"
        if len(frac) == 1:
            sub = int(frac) / 10.0
        elif len(frac) == 2:
            sub = int(frac) / 100.0
        else:
            sub = int(frac[:3]) / 1000.0
        return mins * 60.0 + secs + sub
    except (TypeError, ValueError):
        return None


def parse_lrc(text: str) -> dict[str, Any]:
    """Parse LRC / Enhanced LRC into timed lines.

    Honours [offset:] (milliseconds). Drops other metadata tags.
    Multiple timestamps on one line duplicate the lyric at each time.
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    offset_ms = 0.0
    meta: dict[str, str] = {}
    collected: list[dict[str, Any]] = []

    for raw_line in raw.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        meta_m = _META.match(line)
        if meta_m:
            key = meta_m.group(1).lower()
            val = meta_m.group(2).strip()
            meta[key] = val
            if key == "offset":
                try:
                    offset_ms = float(val)
                except ValueError:
                    offset_ms = 0.0
            continue
        stamps = list(_TS.finditer(line))
        if not stamps:
            continue
        payload = _TS.sub("", line).strip()
        times: list[float] = []
        for m in stamps:
            t = _stamp_to_sec(m)
            if t is not None:
                times.append(t)
        if not times:
            continue
        words = _parse_enhanced_words(payload, default_t=times[0])
        text_only = _WORD.sub("", payload)
        text_only = _BLANK.sub(" ", text_only).strip()
        if not text_only and not words:
            continue
        for t in times:
            collected.append(
                {
                    "t": t,
                    "text": text_only,
                    "words": [dict(w) for w in words],
                }
            )

    offset_sec = offset_ms / 1000.0
    collected.sort(key=lambda x: x["t"])
    lines: list[dict[str, Any]] = []
    for i, item in enumerate(collected):
        t = round(item["t"] + offset_sec, 3)
        nxt = collected[i + 1]["t"] + offset_sec if i + 1 < len(collected) else t + 4.0
        end = round(max(t, nxt), 3)
        words = []
        raw_words = item["words"]
        for j, w in enumerate(raw_words):
            wt = round(float(w["t"]) + offset_sec, 3)
            if j + 1 < len(raw_words):
                we = round(float(raw_words[j + 1]["t"]) + offset_sec, 3)
            else:
                we = end
            words.append({"t": wt, "end": we, "text": w["text"]})
        lines.append({"t": t, "end": end, "text": item["text"], "words": words})
    return {"offset_ms": offset_ms, "meta": meta, "lines": lines}


def _parse_enhanced_words(payload: str, default_t: float = 0.0) -> list[dict[str, Any]]:
    if not _WORD.search(payload):
        return []
    words: list[dict[str, Any]] = []
    pos = 0
    last_t: float | None = None
    buf = ""
    for m in _WORD.finditer(payload):
        buf += payload[pos : m.start()]
        t = _stamp_to_sec(m)
        chunk = _BLANK.sub(" ", buf).strip()
        if chunk:
            start = last_t if last_t is not None else default_t
            words.append({"t": start, "text": chunk})
        last_t = t
        buf = ""
        pos = m.end()
    buf += payload[pos:]
    tail = _BLANK.sub(" ", buf).strip()
    if tail:
        start = last_t if last_t is not None else default_t
        words.append({"t": start, "text": tail})
    return words


def lines_to_txt(lines: list[dict[str, Any]]) -> str:
    return "\n".join((ln.get("text") or "").strip() for ln in lines if (ln.get("text") or "").strip())


def filter_lrc_lines(lines: list[dict[str, Any]], title: str = "") -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for ln in lines:
        text = _clean_text(ln.get("text") or "")
        if not text:
            continue
        if is_credit_hallucination(text, t=float(ln.get("t") or 0.0), title=title):
            continue
        words = []
        for w in ln.get("words") or []:
            wtext = _clean_text(w.get("text") or "")
            if wtext:
                words.append({**w, "text": wtext})
        kept.append({**ln, "text": text, "words": words})
    return kept


def convert_s2hk(text: str) -> tuple[str, str | None]:
    """HK Traditional. Returns (text, 's2hk') or (text, None) if OpenCC missing."""
    try:
        from opencc import OpenCC

        return OpenCC("s2hk").convert(text), "s2hk"
    except Exception:
        return text, None


def convert_lines_s2hk(lines: list[dict[str, Any]], lang: str) -> tuple[list[dict[str, Any]], str | None]:
    if lang != "cantonese":
        return lines, None
    converted = None
    out: list[dict[str, Any]] = []
    for ln in lines:
        text, tag = convert_s2hk(ln.get("text") or "")
        converted = tag or converted
        words = []
        for w in ln.get("words") or []:
            wt, wtag = convert_s2hk(w.get("text") or "")
            converted = wtag or converted
            words.append({**w, "text": wt})
        out.append({**ln, "text": text, "words": words})
    return out, converted


def shift_lines(lines: list[dict[str, Any]], delta: float) -> list[dict[str, Any]]:
    """Move every line/word by delta seconds, clamped at 0."""
    if not delta:
        return [dict(ln) for ln in lines]
    out: list[dict[str, Any]] = []
    for ln in lines:
        t = max(0.0, float(ln.get("t") or 0.0) + delta)
        end = max(t, float(ln.get("end") or ln.get("t") or 0.0) + delta)
        words = []
        for w in ln.get("words") or []:
            wt = max(0.0, float(w.get("t") or 0.0) + delta)
            we = max(wt, float(w.get("end") or w.get("t") or 0.0) + delta)
            words.append({**w, "t": round(wt, 3), "end": round(we, 3)})
        out.append({**ln, "t": round(t, 3), "end": round(end, 3), "words": words})
    return out


def normalize_lrc(text: str, *, lang: str = "cantonese", title: str = "") -> dict[str, Any]:
    parsed = parse_lrc(text)
    filtered = filter_lrc_lines(parsed["lines"], title=title)
    converted_lines, converted = convert_lines_s2hk(filtered, lang)
    return {
        "offset_ms": parsed["offset_ms"],
        "meta": parsed["meta"],
        "converted": converted,
        "lines": converted_lines,
        "txt": lines_to_txt(converted_lines),
    }
