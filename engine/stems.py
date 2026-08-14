from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from engine.lyrics import release_cuda
from engine.pack import SongPack
from engine.tools import run, which


def _demucs_cmd() -> list[str]:
    if which("demucs"):
        return ["demucs"]
    return [sys.executable, "-m", "demucs"]


def demucs_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("demucs") is not None
    except Exception:
        return False


def detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def split_stems(pack: SongPack, device: str | None = None) -> None:
    source = pack.source_audio
    if not source.exists():
        raise FileNotFoundError("song pack 未有 source audio")

    device = device or detect_device()
    release_cuda()
    work = pack.root / "_demucs"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    env_jobs = os.environ.get("KARAOK_DEMUCS_JOBS", "2")

    def _cmd(dev: str) -> list[str]:
        return _demucs_cmd() + [
            "--two-stems=vocals",
            "-n",
            "htdemucs",
            "-d",
            dev,
            "-j",
            env_jobs,
            "-o",
            str(work),
            str(source),
        ]

    try:
        run(_cmd(device))
    except RuntimeError as exc:
        msg = str(exc).lower()
        if device == "cuda" and "out of memory" in msg:
            run(_cmd("cpu"))
        else:
            raise

    vocals, instrumental = _find_stems(work)
    shutil.copy2(vocals, pack.vocals)
    shutil.copy2(instrumental, pack.instrumental)
    shutil.rmtree(work, ignore_errors=True)


def _find_stems(work: Path) -> tuple[Path, Path]:
    vocals = list(work.rglob("vocals.wav"))
    instrumental = list(work.rglob("no_vocals.wav"))
    if not vocals or not instrumental:
        raise RuntimeError(f"Demucs 未產出 stems: {work}")
    return vocals[0], instrumental[0]
