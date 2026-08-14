from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.devices import default_device_indices, list_devices
from engine.ingest import has_youtube_tools
from engine.jobs import BusyError, runner, start_analyze, start_local_import, start_lyrics_align, start_youtube_import
from engine.live import session
from engine.lyrics import (
    LANG_PRESETS,
    WHISPER_MODELS,
    lyrics_available,
    normalize_lang,
    normalize_whisper_model,
)
from engine.melody import melody_available
from engine.pack import get_pack, list_packs
from engine.paths import SONGS_DIR, WEB_DIR, ensure_dirs
from engine.stems import demucs_available, detect_device
from engine.tools import find_ffmpeg

ensure_dirs()

NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


class NoCacheStatic(StaticFiles):
    def is_not_modified(self, *args, **kwargs) -> bool:  # noqa: ARG002
        return False


app = FastAPI(title="Karaok")
app.mount("/web", NoCacheStatic(directory=WEB_DIR), name="web")


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((WEB_DIR / name).read_text(encoding="utf-8"), headers=NO_CACHE)


@app.middleware("http")
async def no_store_ui(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/web/") or path in {"/", "/prep", "/show", "/live"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        if "etag" in response.headers:
            del response.headers["etag"]
    return response


@app.get("/")
def home() -> HTMLResponse:
    return _page("prep.html")


@app.get("/prep")
def prep() -> HTMLResponse:
    return _page("prep.html")


@app.get("/show")
def show() -> HTMLResponse:
    return _page("overlay.html")


@app.get("/live")
def live() -> HTMLResponse:
    return _page("live.html")


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


@app.get("/api/songs")
def songs() -> dict:
    return {"songs": [pack.public_dict() for pack in list_packs()]}


@app.get("/api/songs/{pack_id}")
def song(pack_id: str) -> dict:
    try:
        return get_pack(pack_id).public_dict()
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None


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


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = runner.get(job_id)
    if not job:
        raise HTTPException(404, "job 唔存在")
    return job.public_dict()


@app.get("/api/devices")
def api_devices() -> dict:
    try:
        devices = list_devices()
        defaults = default_device_indices()
    except Exception as exc:
        raise HTTPException(500, f"audio devices: {exc}") from exc
    return {
        "devices": devices,
        "default_input": defaults[0],
        "default_output": defaults[1],
    }


@app.get("/api/songs/{pack_id}/chart")
def song_chart(pack_id: str) -> dict:
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    melody = {}
    lyrics = {}
    if pack.melody.exists():
        melody = json.loads(pack.melody.read_text(encoding="utf-8"))
    if pack.lyrics.exists():
        lyrics = json.loads(pack.lyrics.read_text(encoding="utf-8"))
    meta = pack.load_meta()
    return {
        "id": pack_id,
        "title": meta.title,
        "singer": meta.singer,
        "duration": melody.get("duration"),
        "notes": [
            {"t": n["t"], "duration": n["duration"], "midi": n.get("midi")}
            for n in (melody.get("notes") or [])
        ],
        "lines": lyrics.get("lines") or [],
    }


class SongPatchBody(BaseModel):
    singer: str = Field(default="", max_length=120)


class LiveStartBody(BaseModel):
    pack_id: str
    input_device: int | None = None
    output_device: int | None = None
    input_channel: int = 0
    trim_ms: float = Field(default=0, ge=-80, le=80)
    vocal_mix: float = Field(default=0, ge=0, le=1)
    singer: str | None = None


class LiveTrimBody(BaseModel):
    trim_ms: float = Field(ge=-80, le=80)


class LiveVocalMixBody(BaseModel):
    vocal_mix: float = Field(ge=0, le=1)


@app.patch("/api/songs/{pack_id}")
def patch_song(pack_id: str, body: SongPatchBody) -> dict:
    try:
        pack = get_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    meta = pack.load_meta()
    meta.singer = body.singer.strip()
    pack.save_meta(meta)
    return pack.public_dict()


@app.post("/api/live/start")
def live_start(body: LiveStartBody) -> dict:
    try:
        get_pack(body.pack_id)
    except FileNotFoundError:
        raise HTTPException(404, "song pack 唔存在") from None
    try:
        return session.start(
            body.pack_id,
            input_device=body.input_device,
            output_device=body.output_device,
            input_channel=body.input_channel,
            trim_ms=body.trim_ms,
            singer=body.singer,
            vocal_mix=body.vocal_mix,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/live/stop")
def live_stop() -> dict:
    session.stop()
    return session.status()


@app.post("/api/live/trim")
def live_trim(body: LiveTrimBody) -> dict:
    session.set_trim(body.trim_ms)
    return session.status()


@app.post("/api/live/vocal-mix")
def live_vocal_mix(body: LiveVocalMixBody) -> dict:
    session.set_vocal_mix(body.vocal_mix)
    return session.status()


@app.get("/api/live/status")
def live_status() -> dict:
    return session.status()


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    sent_chart_for = None
    try:
        while True:
            status = session.status()
            if status["pack_id"] and status["pack_id"] != sent_chart_for and (
                status["running"] or status.get("failed")
            ):
                await ws.send_json(session.chart())
                sent_chart_for = status["pack_id"]
            frame = status.get("frame") or {"type": "idle"}
            await ws.send_json(frame)
            await asyncio.sleep(0.04)
    except WebSocketDisconnect:
        return
    except Exception:
        return
