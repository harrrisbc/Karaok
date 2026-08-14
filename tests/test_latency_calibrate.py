import numpy as np

from engine.latency_calibrate import clamp_trim_ms, make_click, measure_from_buffers


def _recorded_with(click: np.ndarray, events: list[tuple[int, float]], size: int = 12000) -> np.ndarray:
    recorded = np.zeros(size, dtype=np.float32)
    for start, gain in events:
        recorded[start : start + len(click)] += click * gain
    return recorded


def test_measure_from_buffers_finds_synthetic_delay_within_one_sample():
    sr = 48000
    click = make_click(sr=sr)
    delay = 1234
    result = measure_from_buffers(click, _recorded_with(click, [(delay, 1.0)]), sr=sr)
    assert result["ok"] is True
    assert abs(result["lag_samples"] - delay) <= 1


def test_measure_from_buffers_returns_weak_for_silence():
    click = make_click()
    result = measure_from_buffers(click, np.zeros(12000, dtype=np.float32))
    assert result == {"ok": False, "error": "weak_signal", "peak": 0.0}


def test_measure_prefers_earliest_credible_peak_over_louder_echo():
    sr = 48000
    click = make_click(sr=sr)
    direct = int(0.020 * sr)
    echo = int(0.060 * sr)
    result = measure_from_buffers(
        click,
        _recorded_with(click, [(direct, 0.55), (echo, 1.0)]),
        sr=sr,
    )
    assert result["ok"] is True
    assert abs(result["lag_samples"] - direct) <= 1


def test_trim_is_clamped_to_existing_slider_range():
    assert clamp_trim_ms(99) == 80.0
    assert clamp_trim_ms(-99) == -80.0
    assert clamp_trim_ms(12.34) == 12.3
