"""Serialize Live audio vs GPU Prep jobs to avoid native process crashes.

Windows + CUDA Whisper/Demucs + PortAudio in one process often dies with
ACCESS_VIOLATION when both run at once. Rules:

- While Live audio streams are open, Whisper prefers CPU.
- Live Start is refused while a GPU Prep step (Demucs / Whisper) is running.
- Melody extract (librosa, CPU) can overlap Live safely.
"""

from __future__ import annotations

import threading
from typing import Any


_lock = threading.Lock()
_live_audio = False


def set_live_audio(active: bool) -> None:
    global _live_audio
    with _lock:
        _live_audio = bool(active)


def live_audio_active() -> bool:
    with _lock:
        return _live_audio


def _gpu_heavy_step(step: str, kind: str) -> bool:
    s = (step or "").strip().lower()
    k = (kind or "").strip().lower()
    if s.startswith("split") or "lyrics" in s:
        return True
    # Import / prep still on Demucs before stems_ready
    if k in {"import_youtube", "import_local", "prep"} and s in {"queued", "split"}:
        return True
    return False


def gpu_job_blocks_live(job: Any | None) -> str | None:
    """Return a user-facing reason if Live Start must wait, else None."""
    if job is None:
        return None
    if getattr(job, "status", None) not in ("queued", "running"):
        return None
    step = str(getattr(job, "step", "") or "")
    kind = str(getattr(job, "kind", "") or "")
    if not _gpu_heavy_step(step, kind):
        return None
    pack = getattr(job, "pack_id", None) or "-"
    return (
        f"Prep 用緊 GPU（{step} · pack={pack}）。等 Analyze/Import 完再開 Live，"
        f"唔係 Windows 會直接 crash。Live 開住之後再開 Analyze → Whisper 會自動用 CPU。"
    )


def asr_device(preferred: str | None = None) -> str:
    """Device for Whisper: force CPU while Live audio is holding PortAudio."""
    if live_audio_active():
        return "cpu"
    if preferred in {"cuda", "cpu"}:
        return preferred
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"
