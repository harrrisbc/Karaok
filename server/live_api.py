from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.devices import default_device_indices, list_devices
from engine.live import session
from engine.pack import get_pack, list_packs
from engine.paths import WEB_DIR
from engine.score import DIFFICULTY_PRESETS, difficulty_params

NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


class NoCacheStatic(StaticFiles):
    def is_not_modified(self, *args, **kwargs) -> bool:  # noqa: ARG002
        return False


def html_page(name: str) -> HTMLResponse:
    return HTMLResponse((WEB_DIR / name).read_text(encoding="utf-8"), headers=NO_CACHE)


def register_static(app: FastAPI) -> None:
    app.mount("/web", NoCacheStatic(directory=WEB_DIR), name="web")


def register_no_cache_middleware(app: FastAPI, extra_paths: set[str] | None = None) -> None:
    ui_paths = {"/", "/show", "/live"} | set(extra_paths or ())

    @app.middleware("http")
    async def no_store_ui(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/web/") or path in ui_paths:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            if "etag" in response.headers:
                del response.headers["etag"]
        return response


class SongPatchBody(BaseModel):
    singer: str = Field(default="", max_length=120)


class LiveStartBody(BaseModel):
    pack_id: str
    input_device: int | None = None
    output_device: int | None = None
    input_channel: int = 0
    trim_ms: float = Field(default=0, ge=-80, le=80)
    vocal_mix: float = Field(default=0, ge=0, le=1)
    difficulty: str = "normal"
    singer: str | None = None


class LiveTrimBody(BaseModel):
    trim_ms: float = Field(ge=-80, le=80)


class LiveCalibrateBody(BaseModel):
    input_device: int | None = None
    output_device: int | None = None
    input_channel: int = Field(default=0, ge=0)


class LiveVocalMixBody(BaseModel):
    vocal_mix: float = Field(ge=0, le=1)


class LiveDifficultyBody(BaseModel):
    difficulty: str


class LiveHealBody(BaseModel):
    amount: float = Field(default=10.0, ge=1.0, le=100.0)


def register_live_routes(app: FastAPI) -> None:
    @app.get("/show")
    def show() -> HTMLResponse:
        return html_page("overlay.html")

    @app.get("/live")
    def live() -> HTMLResponse:
        return html_page("live.html")

    @app.get("/api/songs")
    def songs() -> dict:
        return {"songs": [pack.public_dict() for pack in list_packs()]}

    @app.get("/api/songs/{pack_id}")
    def song(pack_id: str) -> dict:
        try:
            return get_pack(pack_id).public_dict()
        except FileNotFoundError:
            raise HTTPException(404, "song pack 唔存在") from None

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

    @app.post("/api/live/start")
    def live_start(body: LiveStartBody) -> dict:
        try:
            get_pack(body.pack_id)
        except FileNotFoundError:
            raise HTTPException(404, "song pack 唔存在") from None
        if body.difficulty.strip().lower() not in DIFFICULTY_PRESETS:
            raise HTTPException(400, f"unknown difficulty: {body.difficulty}") from None
        session.set_difficulty(body.difficulty)
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

    @app.post("/api/live/calibrate")
    def live_calibrate(body: LiveCalibrateBody) -> dict:
        return session.calibrate(
            input_device=body.input_device,
            output_device=body.output_device,
            input_channel=body.input_channel,
        )

    @app.post("/api/live/vocal-mix")
    def live_vocal_mix(body: LiveVocalMixBody) -> dict:
        session.set_vocal_mix(body.vocal_mix)
        return session.status()

    @app.post("/api/live/difficulty")
    def live_difficulty(body: LiveDifficultyBody) -> dict:
        key = body.difficulty.strip().lower()
        if key not in DIFFICULTY_PRESETS:
            raise HTTPException(400, f"unknown difficulty: {body.difficulty}") from None
        session.set_difficulty(key)
        status = session.status()
        status["difficulty_params"] = difficulty_params(key)
        return status

    @app.post("/api/live/heal")
    def live_heal(body: LiveHealBody) -> dict:
        hp = session.heal_hp(body.amount)
        status = session.status()
        status["healed"] = hp
        return status

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
                    status["running"] or status.get("failed") or status.get("cleared")
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
