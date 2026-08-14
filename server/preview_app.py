"""Live-only ASGI entry: uvicorn server.preview_app:app

Control `/live` + overlay `/show`. No Prep / Demucs / Whisper.
Set KARAOK_SONGS_DIR to a folder of ready song packs.
"""
from __future__ import annotations

from fastapi import FastAPI

from engine.paths import configure_songs_dir
from server.live_api import html_page, register_live_routes, register_no_cache_middleware, register_static

configure_songs_dir()

app = FastAPI(title="Karaok Preview")
register_static(app)
register_no_cache_middleware(app)
register_live_routes(app)


@app.get("/")
def home():
    return html_page("live.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "preview": True}
