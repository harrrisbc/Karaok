"""py2app setup for Karaok Preview.app — run via scripts/mac/build-app.sh on macOS."""
from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP = ["scripts/mac/app_main.py"]
WEB_FILES = [str(p) for p in sorted((ROOT / "web").iterdir()) if p.is_file()]
DATA_FILES = [("web", WEB_FILES)] if WEB_FILES else []

OPTIONS = {
    "argv_emulation": False,
    "emulate_shell_environment": True,
    "packages": [
        "uvicorn",
        "fastapi",
        "starlette",
        "anyio",
        "sniffio",
        "h11",
        "click",
        "pydantic",
        "multipart",
        "numpy",
        "scipy",
        "soundfile",
        "sounddevice",
        "cffi",
        "engine",
        "server",
    ],
    "includes": [
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "server.preview_app",
        "server.live_api",
        "engine.paths",
        "engine.pack",
        "engine.live",
        "engine.devices",
        "engine.score",
        "engine.concurrency",
    ],
    "excludes": [
        "PyQt5",
        "PyQt6",
        "matplotlib",
        "torch",
        "torchaudio",
        "demucs",
        "whisper",
        "faster_whisper",
        "yt_dlp",
    ],
    "plist": {
        "CFBundleName": "Karaok Preview",
        "CFBundleDisplayName": "Karaok Preview",
        "CFBundleIdentifier": "com.harrrisbc.karaok.preview",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": (
            "Karaok Preview needs the microphone to score your singing against the song pack."
        ),
        "NSCameraUsageDescription": (
            "Karaok Preview can use a camera or capture card as the Show background."
        ),
    },
}

setup(
    name="KaraokPreview",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
