from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from engine.lrc import normalize_lrc
from engine.pack import SongPack

LRCLIB_BASE = "https://lrclib.net"
USER_AGENT = "Karaok/0.1 (https://github.com; lyrics via lrclib.net)"
TIMEOUT_SEC = 5.0
GET_DURATION_TOL = 2.0

HttpFn = Callable[[str], tuple[int, Any]]

_BRACKET = re.compile(r"\s*[\(\[【][^\)\]】]*[\)\]】]\s*")
_NOISE_WORDS = re.compile(
    r"\b(official(\s+music)?\s+video|official\s+audio|lyrics?|mv|hd|4k|字幕版?)\b",
    re.I,
)
_ARTIST_SEP = re.compile(r"\s+(?:–|—|-)\s+")


def clean_track_query(title: str) -> str:
    text = (title or "").strip()
    text = _BRACKET.sub(" ", text)
    text = _NOISE_WORDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" -_|") or (title or "").strip()


def split_artist_title(title: str) -> tuple[str, str]:
    raw = (title or "").strip()
    cleaned = clean_track_query(raw)
    parts = _ARTIST_SEP.split(cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return "", cleaned or raw


def pack_duration_sec(pack: SongPack) -> float | None:
    if pack.melody.exists():
        try:
            data = json.loads(pack.melody.read_text(encoding="utf-8"))
            dur = data.get("duration")
            if dur:
                return float(dur)
        except (OSError, ValueError, TypeError):
            pass
    for path in (pack.vocals, pack.source_audio):
        if not path.exists():
            continue
        try:
            import soundfile as sf

            return float(sf.info(str(path)).duration)
        except Exception:
            continue
    return None


def _http_get(url: str) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        if exc.code == 404:
            return 404, None
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise
    try:
        return status, json.loads(body) if body else None
    except json.JSONDecodeError:
        return status, None


def _url(path: str, params: dict[str, Any]) -> str:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{LRCLIB_BASE}{path}?{q}" if q else f"{LRCLIB_BASE}{path}"


def _usable(record: dict | None) -> bool:
    if not record or not isinstance(record, dict):
        return False
    if record.get("instrumental") is True:
        return False
    synced = (record.get("syncedLyrics") or "").strip()
    return bool(synced)


def _duration_delta(record: dict, duration: float | None) -> float | None:
    if duration is None:
        return None
    try:
        rec_d = float(record.get("duration") or 0.0)
    except (TypeError, ValueError):
        return None
    if rec_d <= 0:
        return None
    return abs(rec_d - float(duration))


def _candidate(record: dict, matched_by: str, duration: float | None, auto: bool) -> dict:
    delta = _duration_delta(record, duration)
    return {
        "id": record.get("id"),
        "track_name": record.get("trackName") or "",
        "artist_name": record.get("artistName") or "",
        "album_name": record.get("albumName") or "",
        "duration": record.get("duration"),
        "instrumental": bool(record.get("instrumental")),
        "has_synced": bool((record.get("syncedLyrics") or "").strip()),
        "matched_by": matched_by,
        "duration_delta": None if delta is None else round(delta, 3),
        "auto_apply": auto,
        "record": record,
    }


def search_lrclib(
    *,
    title: str,
    artist: str = "",
    duration: float | None = None,
    http: HttpFn | None = None,
) -> dict[str, Any]:
    """Matching ladder. Only `/api/get` with duration may auto-apply."""
    get = http or _http_get
    track = clean_track_query(title)
    if not artist:
        parsed_artist, parsed_track = split_artist_title(title)
        artist = parsed_artist
        if parsed_track:
            track = parsed_track
    attempts: list[str] = []
    candidates: list[dict] = []
    seen: set[Any] = set()

    def add_many(records: list, matched_by: str, auto: bool = False) -> dict | None:
        for rec in records:
            if not _usable(rec):
                attempts.append(f"{matched_by}: reject instrumental/empty id={rec.get('id')}")
                continue
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            cand = _candidate(rec, matched_by, duration, auto)
            candidates.append(cand)
            if auto:
                return cand
        return None

    try:
        if artist and track and duration:
            attempts.append("get")
            status, body = get(
                _url(
                    "/api/get",
                    {
                        "artist_name": artist,
                        "track_name": track,
                        "duration": int(round(duration)),
                    },
                )
            )
            if status == 200 and isinstance(body, dict):
                hit = add_many([body], "get", auto=True)
                if hit:
                    return {"auto": hit, "candidates": candidates, "attempts": attempts}
            else:
                attempts.append(f"get status={status}")

        if artist and track:
            attempts.append("search-artist")
            _search_add(get, add_many, track, artist, duration, "search-artist")

        if track:
            attempts.append("search-title")
            _search_add(get, add_many, track, "", duration, "search-title")

        q = clean_track_query(title)
        if q:
            attempts.append("search-q")
            status, body = get(_url("/api/search", {"q": q}))
            recs = body if isinstance(body, list) else []
            add_many([r for r in recs if isinstance(r, dict)], "search-q")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "auto": None,
            "candidates": [],
            "attempts": attempts + [f"network: {exc}"],
            "error": str(exc),
        }

    # Packs often have title only (no artist) so /api/get never runs. If a search
    # hit is within ±2s and the track name matches, treat it like an exact get.
    auto = _auto_from_duration_match(candidates, track)
    if auto:
        attempts.append(f"auto-duration id={auto.get('id')} delta={auto.get('duration_delta')}")
        auto["auto_apply"] = True
    return {"auto": auto, "candidates": candidates, "attempts": attempts}


def _auto_from_duration_match(candidates: list[dict], track: str) -> dict | None:
    track_key = (track or "").strip().lower()
    if not track_key or not candidates:
        return None
    near: list[dict] = []
    for cand in candidates:
        delta = cand.get("duration_delta")
        if delta is None or float(delta) > GET_DURATION_TOL:
            continue
        name = (cand.get("track_name") or "").strip().lower()
        if name != track_key:
            continue
        near.append(cand)
    if not near:
        return None
    near.sort(key=lambda c: (float(c.get("duration_delta") or 99.0), str(c.get("id"))))
    return near[0]


def _search_add(get: HttpFn, add_many, track: str, artist: str, duration: float | None, matched_by: str) -> None:
    params = {"track_name": track}
    if artist:
        params["artist_name"] = artist
    status, body = get(_url("/api/search", params))
    recs = body if isinstance(body, list) else []
    add_many([r for r in recs if isinstance(r, dict)], matched_by)


def fetch_record_by_id(lrclib_id: int, http: HttpFn | None = None) -> dict | None:
    get = http or _http_get
    status, body = get(_url("/api/get", {"id": int(lrclib_id)}))
    if status == 200 and isinstance(body, dict):
        return body
    return None


def public_candidate(cand: dict) -> dict:
    return {k: v for k, v in cand.items() if k != "record"}


def cache_raw(pack: SongPack, payload: dict) -> None:
    pack.root.joinpath("lrclib.raw.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_cached_raw(pack: SongPack) -> dict | None:
    path = pack.root / "lrclib.raw.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def record_by_id(pack: SongPack, lrclib_id: int, cached: dict | None = None) -> dict | None:
    data = cached if cached is not None else load_cached_raw(pack)
    if not data:
        return None
    auto = data.get("auto")
    if auto and auto.get("id") == lrclib_id:
        return auto.get("record") or auto
    for cand in data.get("candidates") or []:
        if cand.get("id") == lrclib_id:
            return cand.get("record") or cand
    return None


def lyrics_locked(pack: SongPack) -> bool:
    if not pack.lyrics.exists():
        return False
    try:
        data = json.loads(pack.lyrics.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("locked"):
        return True
    return data.get("source") in {"user-txt", "paste-lrc"}


def line_count_sane(old_n: int, new_n: int) -> bool:
    if old_n < 8:
        return True
    if new_n < 4:
        return False
    ratio = new_n / max(1, old_n)
    return 0.45 <= ratio <= 2.2


def prepare_record(
    record: dict,
    *,
    lang: str,
    title: str,
    matched_by: str,
) -> dict[str, Any]:
    synced = (record.get("syncedLyrics") or "").strip()
    if not synced:
        raise ValueError("record has no syncedLyrics")
    norm = normalize_lrc(synced, lang=lang, title=title)
    return {
        "normalized": norm,
        "lrclib": {
            "id": record.get("id"),
            "track_name": record.get("trackName") or "",
            "artist_name": record.get("artistName") or "",
            "album_name": record.get("albumName") or "",
            "duration": record.get("duration"),
            "matched_by": matched_by,
            "converted": norm.get("converted"),
        },
    }
