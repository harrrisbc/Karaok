from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
