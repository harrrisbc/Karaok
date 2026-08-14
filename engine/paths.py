from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SONGS_DIR = ROOT / "songs"
WEB_DIR = ROOT / "web"


def ensure_dirs() -> None:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
