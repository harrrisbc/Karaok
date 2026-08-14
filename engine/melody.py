from __future__ import annotations

import json
import math

import librosa
import numpy as np

from engine.pack import SongPack


def extract_melody(
    pack: SongPack,
    *,
    sr: int = 22050,
    hop_length: int = 512,
    fmin: float = 100.0,
    fmax: float = 800.0,
    min_note_sec: float = 0.1,
    gap_merge_sec: float = 0.05,
    energy_percentile: float = 45.0,
) -> dict:
    """Build melody.json from vocals using librosa pyin → quantized notes.

    Demucs vocals still leak piano/synth. An RMS energy gate drops quiet bleed
    so the pitch highway tracks singing more than solos.
    """
    if not pack.vocals.exists():
        raise FileNotFoundError(f"missing vocals: {pack.vocals}")

    y, _ = librosa.load(str(pack.vocals), sr=sr, mono=True)
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        hop_length=hop_length,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    if len(rms) < len(f0):
        rms = np.pad(rms, (0, len(f0) - len(rms)))
    else:
        rms = rms[: len(f0)]
    energy_thr = float(np.percentile(rms, energy_percentile)) if len(rms) else 0.0
    voiced = np.asarray(
        [
            bool(v) and (r >= energy_thr)
            for v, r in zip(voiced_flag, rms, strict=False)
        ],
        dtype=bool,
    )
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        min_note_sec=min_note_sec,
        gap_merge_sec=gap_merge_sec,
    )
    payload = {
        "schema_version": 1,
        "sample_rate": sr,
        "hop_length": hop_length,
        "method": "librosa.pyin",
        "fmin": fmin,
        "fmax": fmax,
        "energy_percentile": energy_percentile,
        "energy_threshold": round(energy_thr, 6),
        "note_count": len(notes),
        "duration": float(len(y) / sr),
        "notes": notes,
    }
    pack.melody.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def refine_melody_with_lyrics(pack: SongPack, *, pad_sec: float = 0.4) -> dict | None:
    """Keep only melody notes that overlap lyric lines (drops intro/solo/outro bars)."""
    if not pack.melody.exists() or not pack.lyrics.exists():
        return None
    melody = json.loads(pack.melody.read_text(encoding="utf-8"))
    lyrics = json.loads(pack.lyrics.read_text(encoding="utf-8"))
    windows = [
        (float(line["t"]) - pad_sec, float(line["end"]) + pad_sec)
        for line in lyrics.get("lines") or []
        if "t" in line and "end" in line
    ]
    if not windows:
        return None

    before = list(melody.get("notes") or [])
    kept = [n for n in before if _note_overlaps_windows(n, windows)]
    melody["notes"] = kept
    melody["note_count"] = len(kept)
    melody["refined"] = "lyrics_windows"
    melody["refine_pad_sec"] = pad_sec
    melody["notes_before_refine"] = len(before)
    pack.melody.write_text(json.dumps(melody, indent=2), encoding="utf-8")
    return melody


def _note_overlaps_windows(note: dict, windows: list[tuple[float, float]]) -> bool:
    start = float(note["t"])
    end = start + float(note["duration"])
    for w0, w1 in windows:
        if start < w1 and end > w0:
            return True
    return False


def _hz_to_midi(hz: float) -> int:
    return int(round(69 + 12 * math.log2(hz / 440.0)))


def _midi_to_hz(midi: int) -> float:
    return float(440.0 * (2 ** ((midi - 69) / 12.0)))


def _frames_to_notes(
    *,
    times: np.ndarray,
    f0: np.ndarray,
    voiced: np.ndarray,
    min_note_sec: float,
    gap_merge_sec: float,
) -> list[dict]:
    notes: list[dict] = []
    cur_midi: int | None = None
    start_t = 0.0
    last_voiced_t = 0.0
    hz_samples: list[float] = []

    def flush(end_t: float) -> None:
        nonlocal cur_midi, hz_samples
        if cur_midi is None:
            return
        dur = end_t - start_t
        if dur < min_note_sec or not hz_samples:
            cur_midi = None
            hz_samples = []
            return
        mean_hz = float(np.mean(hz_samples))
        notes.append(
            {
                "t": round(start_t, 4),
                "duration": round(dur, 4),
                "midi": cur_midi,
                "hz": round(_midi_to_hz(cur_midi), 3),
                "hz_mean": round(mean_hz, 3),
            }
        )
        cur_midi = None
        hz_samples = []

    for t, freq, is_voiced in zip(times, f0, voiced, strict=False):
        t = float(t)
        ok = bool(is_voiced) and freq is not None and not np.isnan(freq) and freq > 0
        if not ok:
            if cur_midi is not None and (t - last_voiced_t) > gap_merge_sec:
                flush(last_voiced_t)
            continue

        midi = _hz_to_midi(float(freq))
        last_voiced_t = t
        if cur_midi is None:
            cur_midi = midi
            start_t = t
            hz_samples = [float(freq)]
            continue
        if midi != cur_midi:
            flush(t)
            cur_midi = midi
            start_t = t
            hz_samples = [float(freq)]
        else:
            hz_samples.append(float(freq))

    if cur_midi is not None:
        flush(last_voiced_t if last_voiced_t > start_t else float(times[-1]))

    return _merge_same_pitch(notes, gap_merge_sec)


def _merge_same_pitch(notes: list[dict], gap: float) -> list[dict]:
    if not notes:
        return notes
    merged = [notes[0].copy()]
    for note in notes[1:]:
        prev = merged[-1]
        prev_end = prev["t"] + prev["duration"]
        if note["midi"] == prev["midi"] and (note["t"] - prev_end) <= gap:
            new_end = note["t"] + note["duration"]
            prev["duration"] = round(new_end - prev["t"], 4)
        else:
            merged.append(note.copy())
    return merged


def melody_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("librosa") is not None
    except Exception:
        return False
