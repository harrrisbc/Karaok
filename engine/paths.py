from __future__ import annotations

import os
import sys
from pathlib import Path


def detect_root() -> Path:
    """Repo root, or Contents/Resources when frozen as a Mac .app (py2app)."""
    if getattr(sys, "frozen", False):
        resource = os.environ.get("RESOURCEPATH", "").strip()
        if resource:
            return Path(resource).resolve()
        # .../Karaok Preview.app/Contents/MacOS/<exe> → Resources
        return Path(sys.executable).resolve().parent.parent / "Resources"
    return Path(__file__).resolve().parent.parent


ROOT = detect_root()
WEB_DIR = ROOT / "web"
ENV_SONGS_DIR = "KARAOK_SONGS_DIR"


def resolve_songs_dir(raw: str | None = None) -> Path:
    value = (raw if raw is not None else os.environ.get(ENV_SONGS_DIR, "")).strip()
    path = Path(value).expanduser() if value else (ROOT / "songs")
    return path.resolve()


SONGS_DIR = resolve_songs_dir()


def configure_songs_dir(raw: str | None = None) -> Path:
    """Point pack discovery at a library root. Empty/None uses env or repo songs/."""
    global SONGS_DIR
    SONGS_DIR = resolve_songs_dir(raw)
    try:
        import engine.pack as pack_mod

        pack_mod.SONGS_DIR = SONGS_DIR
    except ImportError:
        pass
    ensure_dirs()
    return SONGS_DIR


def ensure_dirs() -> None:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
