from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from engine.ingest import has_youtube_tools
from engine.jobs import (
    BusyError,
    runner,
    start_analyze,
    start_local_import,
    start_lyrics_align,
    start_lyrics_lrclib,
    start_lyrics_whisper,
    start_youtube_import,
)
from engine.lrclib import (
    cache_raw,
    pack_duration_sec,
    public_candidate,
    search_lrclib,
    split_artist_title,
)
from engine.lyrics import (
    LANG_PRESETS,
    WHISPER_MODELS,
    lyrics_available,
    normalize_lang,
    normalize_whisper_model,
)
from engine.melody import melody_available
from engine.pack import get_pack
from engine.paths import SONGS_DIR, ensure_dirs
from engine.stems import demucs_available, detect_device
from engine.tools import find_ffmpeg
from server.live_api import html_page, register_live_routes, register_no_cache_middleware, register_static

ensure_dirs()

app = FastAPI(title="Karaok")
register_static(app)
register_no_cache_middleware(app, extra_paths={"/prep"})
register_live_routes(app)


@app.get("/")
def home() -> HTMLResponse:
    return html_page("prep.html")


@app.get("/prep")
def prep() -> HTMLResponse:
    return html_page("prep.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": bool(find_ffmpeg()),
        "demucs": demucs_available(),
        "melody": melody_available(),
        "lyrics": lyrics_available(),
        "device": detect_device() if demucs_available() else "cpu",
        "langs": [
            {"id": key, "label": preset["label"]}
            for key, preset in LANG_PRESETS.items()
        ],
        "whisper_models": list(WHISPER_MODELS),
        **has_youtube_tools(),
    }


def _parse_lang(raw: str | None) -> str:
    try:
        return normalize_lang(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _parse_model(raw: str | None) -> str | None:
    try:
        return normalize_whisper_model(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _start_or_busy(fn) -> dict:
    try:
        return fn().public_dict()
    except BusyError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/jobs/active")
def job_active() -> dict:
    job = runner.active()
    return {"job": None if job is None else job.public_dict()}


@app.post("/api/jobs/local")
async def job_local(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    singer: str = Form(default=""),
    lang: str = Form(default="cantonese"),
    whisper_model: str | None = Form(default=None),
) -> dict:
    lyrics_lang = _parse_lang(lang)
    suffix = Path(file.filename or "source.mp3").suffix.lower() or ".mp3"
    tmp = SONGS_DIR / "_incoming"
    tmp.mkdir(parents=True, exist_ok=True)
    dest = tmp / f"{Path(file.filename or 'upload').stem}{suffix}"
    dest.write_bytes(await file.read())

    def start():
        return start_local_import(
            dest,
            title=title or Path(file.filename or "song").stem,
            lyrics_lang=lyrics_lang,
            whisper_model=_parse_model(whisper_model),
            singer=singer,
        )

    try:
        return _start_or_busy(start)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise


@app.post("/api/jobs/youtube")
def job_youtube(
    url: str = Form(...),
    singer: str = Form(default=""),
    lang: str = Form(default="cantonese"),
    whisper_model: str | None = Form(default=None),
) -> dict:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "請提供 YouTube URL")
    return _start_or_busy(
        lambda: start_youtube_import(
            url,
            lyrics_lang=_parse_lang(lang),
            whisper_model=_parse_model(whisper_model),
            singer=singer,
        )
    )


@app.post("/api/jobs/analyze/{pack_id}")
def job_analyze(
    pack_id: str,
    lang: str | None = Form(default=None),
    whisper_model: str | None = Form(default=None),
    prefer_whisper: bool = Form(default=False),
) -> dict:
    try:
        get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    lyrics_lang = _parse_lang(lang) if lang else None
    return _start_or_busy(
        lambda: start_analyze(
            pack_id,
            lyrics_lang=lyrics_lang,
            whisper_model=_parse_model(whisper_model),
            prefer_whisper=bool(prefer_whisper),
        )
    )


@app.post("/api/jobs/lyrics-whisper/{pack_id}")
def job_lyrics_whisper(
    pack_id: str,
    lang: str | None = Form(default=None),
    whisper_model: str | None = Form(default=None),
) -> dict:
    """Force Whisper lyrics — skip LRCLIB. Use when LRCLIB timing/text is wrong."""
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    if not pack.vocals.exists():
        raise HTTPException(400, "vocals.wav missing — 先 Import / split") from None
    lyrics_lang = _parse_lang(lang) if lang else None
    return _start_or_busy(
        lambda: start_lyrics_whisper(
            pack_id,
            lyrics_lang=lyrics_lang,
            whisper_model=_parse_model(whisper_model),
        )
    )


@app.post("/api/jobs/lyrics-align/{pack_id}")
async def job_lyrics_align(
    pack_id: str,
    text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    lang: str | None = Form(default=None),
    whisper_model: str | None = Form(default=None),
    prefer_remap: bool = Form(default=False),
) -> dict:
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    if not pack.vocals.exists():
        raise HTTPException(400, "vocals.wav missing — 先 Import / split") from None

    body = (text or "").strip()
    if file is not None and file.filename:
        raw = await file.read()
        body = raw.decode("utf-8-sig", errors="replace").strip()
    if not body:
        raise HTTPException(400, "請提供 lyrics txt（file 或 text）") from None

    lyrics_lang = _parse_lang(lang) if lang else None
    return _start_or_busy(
        lambda: start_lyrics_align(
            pack_id,
            body,
            lyrics_lang=lyrics_lang,
            whisper_model=_parse_model(whisper_model),
            prefer_remap=bool(prefer_remap),
        )
    )


class LrclibApplyBody(BaseModel):
    id: int = Field(ge=1)
    mode: str = "align"
    force: bool = False
    whisper_model: str | None = None


@app.get("/api/lyrics/lrclib/search/{pack_id}")
def lyrics_lrclib_search(
    pack_id: str,
    title: str | None = None,
    artist: str | None = None,
) -> dict:
    """Manual LRCLIB browser: search candidates and cache them on the pack."""
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    meta = pack.load_meta()
    query_title = (title or "").strip() or meta.title
    query_artist = (artist or "").strip()
    if not query_artist:
        parsed_artist, _parsed_track = split_artist_title(query_title)
        if not parsed_artist:
            query_artist = (meta.singer or "").strip()
    duration = pack_duration_sec(pack)
    try:
        found = search_lrclib(title=query_title, artist=query_artist, duration=duration)
    except Exception as exc:
        raise HTTPException(502, f"LRCLIB 連線失敗: {exc}") from exc
    cache_raw(pack, found)
    return {
        "pack_id": pack_id,
        "query": {"title": query_title, "artist": query_artist, "duration": duration},
        "auto": public_candidate(found["auto"]) if found.get("auto") else None,
        "candidates": [public_candidate(c) for c in (found.get("candidates") or [])],
        "attempts": found.get("attempts") or [],
        "error": found.get("error"),
    }


@app.post("/api/lyrics/lrclib/apply/{pack_id}")
def lyrics_lrclib_apply(pack_id: str, body: LrclibApplyBody) -> dict:
    """Apply a searched LRCLIB record onto the pack (trust-lrc or align)."""
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    if not pack.vocals.exists():
        raise HTTPException(400, "vocals.wav missing — 先 Import / split") from None
    mode = body.mode.strip().lower()
    if mode not in {"trust-lrc", "align"}:
        raise HTTPException(400, "mode 要係 trust-lrc 或 align") from None
    meta = pack.load_meta()
    return _start_or_busy(
        lambda: start_lyrics_lrclib(
            pack_id,
            lrclib_id=body.id,
            mode=mode,
            lyrics_lang=meta.lyrics_lang,
            whisper_model=_parse_model(body.whisper_model) or "small",
            force=body.force,
            matched_by="manual",
        )
    )


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = runner.get(job_id)
    if not job:
        raise HTTPException(404, "job 唔存在")
    return job.public_dict()
