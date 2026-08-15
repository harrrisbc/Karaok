"""Offline vocal F0 vs melody.json hit-rate diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from engine.melody import apply_voiced_energy_gate
from engine.pitch import yin_f0
from engine.score import cents_error, cents_error_raw


def note_coverage_vs_voiced(
    notes: list[dict],
    *,
    voiced_sec: float,
) -> float:
    """Fraction of gated-voiced time covered by chart notes (0..1+)."""
    if voiced_sec <= 0:
        return 0.0
    note_sec = sum(float(n.get("duration") or 0.0) for n in notes)
    return float(note_sec / voiced_sec)


def _hz_at_time(times: np.ndarray, f0: np.ndarray, voiced: np.ndarray, t: float) -> float | None:
    if len(times) == 0:
        return None
    i = int(np.argmin(np.abs(times - t)))
    if not bool(voiced[i]):
        return None
    hz = float(f0[i])
    if not np.isfinite(hz) or hz <= 0:
        return None
    return hz


def _yin_hz_at(y: np.ndarray, sr: int, t: float, *, frame: int = 2048) -> float | None:
    center = int(t * sr)
    half = frame // 2
    start = max(0, center - half)
    end = min(len(y), start + frame)
    if end - start < frame // 2:
        return None
    chunk = y[start:end]
    if len(chunk) < frame:
        chunk = np.pad(chunk, (0, frame - len(chunk)))
    hz, conf = yin_f0(chunk.astype(np.float32), sr)
    if hz is None or conf < 0.35:
        return None
    return float(hz)


def _score_pairs(
    pairs: list[tuple[float, float]],
    *,
    hit_cents: float,
) -> dict[str, float | int]:
    compared = len(pairs)
    hit_raw = sum(1 for sung, exp in pairs if abs(cents_error_raw(sung, exp)) < hit_cents)
    hit_fold = sum(1 for sung, exp in pairs if abs(cents_error(sung, exp)) < hit_cents)

    def rate(n: int) -> float:
        return float(n / compared) if compared else 0.0

    return {
        "compared": compared,
        "hit_raw": hit_raw,
        "hit_fold": hit_fold,
        "rate_raw": rate(hit_raw),
        "rate_fold": rate(hit_fold),
    }


def melody_hit_rates(
    vocals_path: Path,
    notes: list[dict],
    *,
    sr: int = 22050,
    hop_length: int = 512,
    fmin: float = 80.0,
    fmax: float = 800.0,
    hit_cents: float = 50.0,
    energy_percentile: float = 30.0,
    soft_voiced_prob: float = 0.6,
) -> dict[str, Any]:
    """Compare F0 at each note midpoint to note.hz (pyin + live-like YIN)."""
    y, _ = librosa.load(str(vocals_path), sr=sr, mono=True)
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        hop_length=hop_length,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    gated, _thr = apply_voiced_energy_gate(
        voiced_flag,
        rms,
        voiced_prob,
        energy_percentile=energy_percentile,
        soft_voiced_prob=soft_voiced_prob,
    )
    hop_sec = float(hop_length) / float(sr)
    voiced_sec = float(np.sum(gated)) * hop_sec
    note_sec = sum(float(n.get("duration") or 0.0) for n in notes)
    coverage = note_coverage_vs_voiced(notes, voiced_sec=voiced_sec)

    pyin_pairs: list[tuple[float, float]] = []
    yin_pairs: list[tuple[float, float]] = []
    for note in notes:
        start = float(note["t"])
        dur = float(note["duration"])
        expected = float(note.get("hz") or 0.0)
        if expected <= 0 or dur <= 0:
            continue
        mid = start + dur * 0.5
        sung_pyin = _hz_at_time(times, f0, gated, mid)
        if sung_pyin is not None:
            pyin_pairs.append((sung_pyin, expected))
        sung_yin = _yin_hz_at(y, sr, mid)
        if sung_yin is not None:
            yin_pairs.append((sung_yin, expected))

    return {
        "notes": len(notes),
        "voiced_sec": round(voiced_sec, 2),
        "note_sec": round(note_sec, 2),
        "coverage": round(coverage, 3),
        "pyin": _score_pairs(pyin_pairs, hit_cents=hit_cents),
        "yin": _score_pairs(yin_pairs, hit_cents=hit_cents),
    }


def pack_melody_hit_rates(pack_root: Path, **kwargs: Any) -> dict[str, Any]:
    melody = json.loads((pack_root / "melody.json").read_text(encoding="utf-8"))
    vocals = pack_root / "vocals.wav"
    out = melody_hit_rates(vocals, list(melody.get("notes") or []), **kwargs)
    out["pack"] = pack_root.name
    out["energy_percentile"] = melody.get("energy_percentile")
    return out
