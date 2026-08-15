from __future__ import annotations

import json
import math

import librosa
import numpy as np
from scipy.ndimage import median_filter

from engine.pack import SongPack

DEFAULT_SMOOTH_FRAMES = 9
DEFAULT_HYSTERESIS_SEMITONES = 1.0
DEFAULT_MERGE_SEMITONES = 1.0
DEFAULT_MERGE_GAP_SEC = 0.12
DEFAULT_MIN_NOTE_SEC = 0.08
DEFAULT_GAP_FLUSH_SEC = 0.05
OCTAVE_JUMP_SEMITONES = 11
OCTAVE_MATCH_SEMITONES = 3.0


def apply_voiced_energy_gate(
    voiced_flag: np.ndarray,
    rms: np.ndarray,
    voiced_prob: np.ndarray | None,
    *,
    energy_percentile: float = 30.0,
    soft_voiced_prob: float = 0.6,
) -> tuple[np.ndarray, float]:
    """Keep pyin-voiced frames unless both quiet and low-confidence (bleed).

    A whole-track RMS percentile alone kills soft verse openings (e.g. Eason
    《1874》). Soft but confident voiced frames are kept even below the thr.
    """
    rms_arr = np.asarray(rms, dtype=float)
    flag = np.asarray(voiced_flag, dtype=bool)
    if len(rms_arr) != len(flag):
        n = len(flag)
        if len(rms_arr) < n:
            rms_arr = np.pad(rms_arr, (0, n - len(rms_arr)))
        else:
            rms_arr = rms_arr[:n]
    energy_thr = float(np.percentile(rms_arr, energy_percentile)) if len(rms_arr) else 0.0
    loud = rms_arr >= energy_thr
    if voiced_prob is None:
        gated = flag & loud
    else:
        prob = np.asarray(voiced_prob, dtype=float)
        if len(prob) != len(flag):
            n = len(flag)
            if len(prob) < n:
                prob = np.pad(prob, (0, n - len(prob)))
            else:
                prob = prob[:n]
        soft_ok = prob >= soft_voiced_prob
        gated = flag & (loud | soft_ok)
    return gated.astype(bool), energy_thr


def extract_melody(
    pack: SongPack,
    *,
    sr: int = 22050,
    hop_length: int = 512,
    fmin: float = 80.0,
    fmax: float = 800.0,
    min_note_sec: float = DEFAULT_MIN_NOTE_SEC,
    gap_merge_sec: float = DEFAULT_GAP_FLUSH_SEC,
    energy_percentile: float = 30.0,
    soft_voiced_prob: float = 0.6,
    smooth_frames: int = DEFAULT_SMOOTH_FRAMES,
    hysteresis_semitones: float = DEFAULT_HYSTERESIS_SEMITONES,
    merge_semitones: float = DEFAULT_MERGE_SEMITONES,
    merge_gap_sec: float = DEFAULT_MERGE_GAP_SEC,
) -> dict:
    """Build melody.json from vocals using librosa pyin → smoothed notes.

    Demucs vocals still leak piano/synth. An RMS energy gate drops quiet bleed,
    but soft confident singing (below the track-wide thr) is kept.

    Notes are segmented with median-smoothed continuous MIDI + hysteresis so
    vibrato does not shatter into discarded fragments.
    """
    if not pack.vocals.exists():
        raise FileNotFoundError(f"missing vocals: {pack.vocals}")

    y, _ = librosa.load(str(pack.vocals), sr=sr, mono=True)
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        hop_length=hop_length,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    voiced, energy_thr = apply_voiced_energy_gate(
        voiced_flag,
        rms,
        voiced_prob,
        energy_percentile=energy_percentile,
        soft_voiced_prob=soft_voiced_prob,
    )
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        voiced_prob=voiced_prob,
        min_note_sec=min_note_sec,
        gap_merge_sec=gap_merge_sec,
        smooth_frames=smooth_frames,
        hysteresis_semitones=hysteresis_semitones,
        merge_semitones=merge_semitones,
        merge_gap_sec=merge_gap_sec,
    )
    notes, octave_fixed = fix_octave_outliers(notes)
    payload = {
        "schema_version": 2,
        "sample_rate": sr,
        "hop_length": hop_length,
        "method": "librosa.pyin+smoothed",
        "fmin": fmin,
        "fmax": fmax,
        "energy_percentile": energy_percentile,
        "soft_voiced_prob": soft_voiced_prob,
        "energy_threshold": round(energy_thr, 6),
        "smooth_frames": int(smooth_frames),
        "hysteresis_semitones": float(hysteresis_semitones),
        "merge_semitones": float(merge_semitones),
        "merge_gap_sec": float(merge_gap_sec),
        "min_note_sec": float(min_note_sec),
        "octave_fixed": int(octave_fixed),
        "note_count": len(notes),
        "duration": float(len(y) / sr),
        "notes": notes,
    }
    pack.melody.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def lyrics_timing_untrusted(lyrics: dict) -> bool:
    """Whisper / ASR line clocks often leave holes that erase real melody notes."""
    source = str(lyrics.get("source") or "").strip().lower()
    method = str(lyrics.get("method") or "").strip().lower()
    if "whisper" in source or "whisper" in method:
        return True
    if method in {"openai-whisper", "faster-whisper"}:
        return True
    return False


def refine_melody_with_lyrics(
    pack: SongPack,
    *,
    pad_sec: float = 0.4,
    max_drop_ratio: float = 0.25,
    min_notes_for_drop_guard: int = 40,
) -> dict | None:
    """Keep melody notes that overlap lyric lines (drops intro/solo/outro bars).

    Safety:
    - Skip when lyric timing is Whisper/ASR (gappy clocks wipe sung notes).
    - On large charts, abort if refine would drop more than max_drop_ratio.
    """
    if not pack.melody.exists() or not pack.lyrics.exists():
        return None
    melody = json.loads(pack.melody.read_text(encoding="utf-8"))
    lyrics = json.loads(pack.lyrics.read_text(encoding="utf-8"))
    if lyrics_timing_untrusted(lyrics):
        return None
    windows = [
        (float(line["t"]) - pad_sec, float(line["end"]) + pad_sec)
        for line in lyrics.get("lines") or []
        if "t" in line and "end" in line
    ]
    if not windows:
        return None

    before = list(melody.get("notes") or [])
    kept = [n for n in before if _note_overlaps_windows(n, windows)]
    before_n = len(before)
    kept_n = len(kept)
    if (
        before_n >= min_notes_for_drop_guard
        and kept_n < before_n * (1.0 - max_drop_ratio)
    ):
        return None
    melody["notes"] = kept
    melody["note_count"] = kept_n
    melody["refined"] = "lyrics_windows"
    melody["refine_pad_sec"] = pad_sec
    melody["notes_before_refine"] = before_n
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


def _hz_to_midi_float(hz: float) -> float:
    return float(69 + 12 * math.log2(hz / 440.0))


def _midi_to_hz(midi: float | int) -> float:
    return float(440.0 * (2 ** ((float(midi) - 69) / 12.0)))


def _smooth_midi(midi: np.ndarray, voiced: np.ndarray, smooth_frames: int) -> np.ndarray:
    """Median-filter continuous MIDI on voiced frames only."""
    out = midi.copy()
    if smooth_frames <= 1 or len(midi) == 0:
        return out
    size = max(1, int(smooth_frames) | 1)  # odd window
    filled = np.where(np.isfinite(midi), midi, 0.0)
    smoothed = median_filter(filled, size=size, mode="nearest")
    out = np.where(voiced & np.isfinite(midi), smoothed, np.nan)
    return out


def _frames_to_notes(
    *,
    times: np.ndarray,
    f0: np.ndarray,
    voiced: np.ndarray,
    voiced_prob: np.ndarray | None = None,
    min_note_sec: float = DEFAULT_MIN_NOTE_SEC,
    gap_merge_sec: float = DEFAULT_GAP_FLUSH_SEC,
    smooth_frames: int = DEFAULT_SMOOTH_FRAMES,
    hysteresis_semitones: float = DEFAULT_HYSTERESIS_SEMITONES,
    merge_semitones: float = DEFAULT_MERGE_SEMITONES,
    merge_gap_sec: float = DEFAULT_MERGE_GAP_SEC,
) -> list[dict]:
    """Segment F0 into notes via smoothed continuous MIDI + hysteresis.

    Merge near-pitch neighbours first, then drop segments shorter than
    min_note_sec so vibrato fragments are absorbed instead of discarded.
    """
    times_arr = np.asarray(times, dtype=float)
    f0_arr = np.asarray(f0, dtype=float)
    voiced_arr = np.asarray(voiced, dtype=bool)
    if voiced_prob is None:
        prob_arr = np.ones(len(times_arr), dtype=float)
    else:
        prob_arr = np.asarray(voiced_prob, dtype=float)
        if len(prob_arr) != len(times_arr):
            n = len(times_arr)
            if len(prob_arr) < n:
                prob_arr = np.pad(prob_arr, (0, n - len(prob_arr)))
            else:
                prob_arr = prob_arr[:n]

    midi_raw = np.full(len(times_arr), np.nan, dtype=float)
    for i, (freq, is_voiced) in enumerate(zip(f0_arr, voiced_arr, strict=False)):
        ok = bool(is_voiced) and freq is not None and np.isfinite(freq) and float(freq) > 0
        if ok:
            midi_raw[i] = _hz_to_midi_float(float(freq))

    midi_s = _smooth_midi(midi_raw, voiced_arr, smooth_frames)

    segments: list[dict] = []
    cur_samples: list[float] = []
    cur_hz: list[float] = []
    cur_prob: list[float] = []
    start_t = 0.0
    last_voiced_t = 0.0

    def flush(end_t: float) -> None:
        nonlocal cur_samples, cur_hz, cur_prob
        if not cur_samples:
            return
        med_midi = float(np.median(cur_samples))
        med_hz = float(np.median(cur_hz)) if cur_hz else _midi_to_hz(med_midi)
        mean_hz = float(np.mean(cur_hz)) if cur_hz else med_hz
        conf = float(np.mean(cur_prob)) if cur_prob else 0.0
        midi_q = int(round(med_midi))
        segments.append(
            {
                "t": float(start_t),
                "duration": float(end_t - start_t),
                "midi": midi_q,
                "midi_f": med_midi,
                "hz": round(_midi_to_hz(midi_q), 3),
                "hz_mean": round(mean_hz, 3),
                "hz_median": round(med_hz, 3),
                "conf": round(conf, 3),
            }
        )
        cur_samples = []
        cur_hz = []
        cur_prob = []

    for t, mc, freq, is_voiced, conf in zip(
        times_arr, midi_s, f0_arr, voiced_arr, prob_arr, strict=False
    ):
        t = float(t)
        ok = bool(is_voiced) and np.isfinite(mc)
        if not ok:
            if cur_samples and (t - last_voiced_t) > gap_merge_sec:
                flush(last_voiced_t)
            continue

        last_voiced_t = t
        hz_val = float(freq) if np.isfinite(freq) and float(freq) > 0 else _midi_to_hz(mc)
        if not cur_samples:
            start_t = t
            cur_samples = [float(mc)]
            cur_hz = [hz_val]
            cur_prob = [float(conf) if np.isfinite(conf) else 0.0]
            continue

        center = float(np.median(cur_samples))
        if abs(float(mc) - center) > hysteresis_semitones:
            flush(t)
            start_t = t
            cur_samples = [float(mc)]
            cur_hz = [hz_val]
            cur_prob = [float(conf) if np.isfinite(conf) else 0.0]
        else:
            cur_samples.append(float(mc))
            cur_hz.append(hz_val)
            cur_prob.append(float(conf) if np.isfinite(conf) else 0.0)

    if cur_samples:
        flush(last_voiced_t if last_voiced_t > start_t else float(times_arr[-1]))

    merged = _merge_near_pitch(segments, merge_semitones, merge_gap_sec)
    notes: list[dict] = []
    for seg in merged:
        if seg["duration"] < min_note_sec:
            continue
        notes.append(
            {
                "t": round(seg["t"], 4),
                "duration": round(seg["duration"], 4),
                "midi": int(seg["midi"]),
                "hz": round(float(seg["hz"]), 3),
                "hz_mean": round(float(seg["hz_mean"]), 3),
                "hz_median": round(float(seg["hz_median"]), 3),
                "conf": round(float(seg.get("conf", 0.0)), 3),
            }
        )
    return notes


def _merge_near_pitch(
    segments: list[dict],
    merge_semitones: float,
    merge_gap_sec: float,
) -> list[dict]:
    if not segments:
        return segments
    out = [segments[0].copy()]
    for seg in segments[1:]:
        prev = out[-1]
        prev_end = prev["t"] + prev["duration"]
        gap = seg["t"] - prev_end
        pitch_delta = abs(float(seg.get("midi_f", seg["midi"])) - float(prev.get("midi_f", prev["midi"])))
        if pitch_delta <= merge_semitones and gap <= merge_gap_sec:
            w1 = float(prev["duration"])
            w2 = float(seg["duration"])
            total = max(1e-6, w1 + w2)
            midi_f = (float(prev.get("midi_f", prev["midi"])) * w1 + float(seg.get("midi_f", seg["midi"])) * w2) / total
            hz_med = (float(prev["hz_median"]) * w1 + float(seg["hz_median"]) * w2) / total
            hz_mean = (float(prev["hz_mean"]) * w1 + float(seg["hz_mean"]) * w2) / total
            conf = (float(prev.get("conf", 0.0)) * w1 + float(seg.get("conf", 0.0)) * w2) / total
            new_end = seg["t"] + seg["duration"]
            prev["duration"] = new_end - prev["t"]
            prev["midi_f"] = midi_f
            prev["midi"] = int(round(midi_f))
            prev["hz"] = round(_midi_to_hz(prev["midi"]), 3)
            prev["hz_median"] = hz_med
            prev["hz_mean"] = hz_mean
            prev["conf"] = conf
        else:
            out.append(seg.copy())
    return out


def fix_octave_outliers(
    notes: list[dict],
    *,
    jump_semitones: float = OCTAVE_JUMP_SEMITONES,
    match_semitones: float = OCTAVE_MATCH_SEMITONES,
) -> tuple[list[dict], int]:
    """Fold isolated ±octave blips toward local neighbour median.

    A note that is ≥jump_semitones from both neighbours is likely a pyin
    subharmonic / harmonic error. Try ±1 octave and keep the fold that lands
    within match_semitones of the local median.
    """
    if len(notes) < 3:
        return [n.copy() for n in notes], 0

    out = [n.copy() for n in notes]
    fixed = 0
    for i in range(1, len(out) - 1):
        prev_m = float(out[i - 1]["midi"])
        cur_m = float(out[i]["midi"])
        next_m = float(out[i + 1]["midi"])
        if abs(cur_m - prev_m) < jump_semitones or abs(cur_m - next_m) < jump_semitones:
            continue
        local = 0.5 * (prev_m + next_m)
        best_m = cur_m
        best_dist = abs(cur_m - local)
        for delta in (12.0, -12.0, 24.0, -24.0):
            cand = cur_m + delta
            dist = abs(cand - local)
            if dist < best_dist:
                best_dist = dist
                best_m = cand
        if best_m != cur_m and best_dist <= match_semitones:
            midi_q = int(round(best_m))
            ratio = 2.0 ** ((best_m - cur_m) / 12.0)
            out[i]["midi"] = midi_q
            out[i]["hz"] = round(_midi_to_hz(midi_q), 3)
            if "hz_mean" in out[i]:
                out[i]["hz_mean"] = round(float(out[i]["hz_mean"]) * ratio, 3)
            if "hz_median" in out[i]:
                out[i]["hz_median"] = round(float(out[i]["hz_median"]) * ratio, 3)
            fixed += 1
    return out, fixed


def melody_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("librosa") is not None
    except Exception:
        return False
