from __future__ import annotations

import threading
from typing import Any

import numpy as np


def clamp_trim_ms(value: float) -> float:
    return round(max(-80.0, min(80.0, float(value))), 1)


def make_click(
    *,
    sr: int = 48000,
    hz: float = 1000.0,
    duration_ms: float = 8.0,
) -> np.ndarray:
    """Short sine burst with fades, so it does not pop at the output."""
    n = max(8, int(sr * duration_ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / sr
    # A small deterministic noise component makes the burst unambiguous to correlate.
    rng = np.random.default_rng(int(hz * 1000 + sr + n))
    click = (
        0.45 * np.sin(2 * np.pi * hz * t)
        + 0.55 * rng.standard_normal(n, dtype=np.float32)
    ).astype(np.float32)
    fade_n = max(1, min(n // 2, int(sr * 0.001)))
    fade = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
    click[:fade_n] *= fade
    click[-fade_n:] *= fade[::-1]
    return click


def measure_from_buffers(
    click: np.ndarray,
    recorded: np.ndarray,
    *,
    sr: int = 48000,
    min_lag_ms: float = -20.0,
    max_lag_ms: float = 150.0,
    peak_threshold: float = 0.70,
) -> dict[str, Any]:
    """Find the earliest credible normalized-correlation peak in recorded audio."""
    click = np.asarray(click, dtype=np.float32).reshape(-1)
    recorded = np.asarray(recorded, dtype=np.float32).reshape(-1)
    if len(click) < 2 or len(recorded) < len(click):
        return {"ok": False, "error": "weak_signal", "peak": 0.0}

    click = click - float(np.mean(click))
    click_norm = float(np.linalg.norm(click))
    if click_norm < 1e-8:
        return {"ok": False, "error": "weak_signal", "peak": 0.0}

    dots = np.correlate(recorded, click, mode="valid")
    energy = np.convolve(recorded * recorded, np.ones(len(click), dtype=np.float32), mode="valid")
    scores = dots / (np.sqrt(np.maximum(energy, 1e-12)) * click_norm)

    lo = max(0, int(round(min_lag_ms * sr / 1000.0)))
    hi = min(len(scores) - 1, int(round(max_lag_ms * sr / 1000.0)))
    if hi < lo:
        return {"ok": False, "error": "weak_signal", "peak": 0.0}

    window = scores[lo : hi + 1]
    absolute = np.abs(window)
    # Choose the earliest local peak over threshold: direct sound beats a louder room echo.
    candidates = [
        index
        for index, score in enumerate(absolute)
        if score >= peak_threshold
        and (index == 0 or score >= absolute[index - 1])
        and (index == len(absolute) - 1 or score >= absolute[index + 1])
    ]
    if not candidates:
        return {
            "ok": False,
            "error": "weak_signal",
            "peak": round(float(np.max(absolute)) if len(absolute) else 0.0, 3),
        }

    sample_lag = lo + candidates[0]
    peak = float(absolute[candidates[0]])
    return {
        "ok": True,
        "lag_samples": sample_lag,
        "lag_ms": round(1000.0 * sample_lag / sr, 3),
        "peak": round(peak, 3),
    }


def _latency_ms(value: Any) -> float:
    if isinstance(value, (tuple, list)):
        value = value[-1]
    try:
        return max(0.0, float(value) * 1000.0)
    except (TypeError, ValueError):
        return 0.0


def measure_loop_latency_ms(
    *,
    input_device: int | None,
    output_device: int | None,
    input_channel: int = 0,
    sr: int = 48000,
    click_hz: float = 1000.0,
    click_ms: float = 8.0,
    record_ms: float = 400.0,
) -> dict[str, Any]:
    """Play a click and record it. Always closes streams before returning."""
    import sounddevice as sd

    click = make_click(sr=sr, hz=click_hz, duration_ms=click_ms)
    lead_samples = int(0.05 * sr)
    output = np.concatenate((np.zeros(lead_samples, dtype=np.float32), click))
    target_samples = int(record_ms * sr / 1000.0)
    captured = np.zeros(target_samples, dtype=np.float32)
    cursor = {"out": 0, "in": 0}
    done = threading.Event()
    out_stream = in_stream = None

    try:
        out_channels = 1
        in_channels = max(1, int(input_channel) + 1)
        try:
            if output_device is not None:
                out_channels = max(1, min(2, int(sd.query_devices(output_device)["max_output_channels"])))
            if input_device is not None:
                in_channels = max(
                    1,
                    min(in_channels, int(sd.query_devices(input_device)["max_input_channels"])),
                )
        except Exception:
            pass

        def out_cb(outdata, frames, time_info, status):  # noqa: ARG001
            outdata.fill(0)
            start = cursor["out"]
            chunk = output[start : start + frames]
            if len(chunk):
                outdata[: len(chunk), :] = chunk[:, None]
            cursor["out"] = start + frames

        def in_cb(indata, frames, time_info, status):  # noqa: ARG001
            start = cursor["in"]
            take = min(frames, target_samples - start)
            if take > 0:
                channel = min(max(0, input_channel), indata.shape[1] - 1)
                captured[start : start + take] = indata[:take, channel]
                cursor["in"] = start + take
            if cursor["in"] >= target_samples:
                done.set()

        in_stream = sd.InputStream(
            samplerate=sr,
            blocksize=0,
            device=input_device,
            channels=in_channels,
            dtype="float32",
            callback=in_cb,
        )
        out_stream = sd.OutputStream(
            samplerate=sr,
            blocksize=0,
            device=output_device,
            channels=out_channels,
            dtype="float32",
            callback=out_cb,
        )
        in_stream.start()
        out_stream.start()
        if not done.wait(record_ms / 1000.0 + 1.0):
            return {"ok": False, "error": "device", "message": "record timeout"}

        measured = measure_from_buffers(
            click,
            captured,
            sr=sr,
            min_lag_ms=-20,
            max_lag_ms=150,
        )
        if not measured["ok"]:
            measured["message"] = "Mic 冇收到 click；開大喇叭、對準 mic，或者檢查 input device。"
            return measured

        # Correlation offset includes our 50ms lead-in before emitting the click.
        lag_ms = float(measured["lag_ms"]) - (lead_samples * 1000.0 / sr)
        output_ms = _latency_ms(getattr(out_stream, "latency", 0)) or 20.0
        input_ms = _latency_ms(getattr(in_stream, "latency", 0)) or 10.0
        proposed = clamp_trim_ms(lag_ms - (output_ms - input_ms))
        return {
            "ok": True,
            "lag_ms": round(lag_ms, 1),
            "peak": measured["peak"],
            "proposed_trim_ms": proposed,
            "output_ms": round(output_ms, 1),
            "input_ms": round(input_ms, 1),
            "message": f"Measured loop ~{lag_ms:.1f} ms → proposed trim {proposed:+.1f} ms",
        }
    except Exception as exc:
        return {"ok": False, "error": "device", "message": str(exc)}
    finally:
        for stream in (out_stream, in_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
