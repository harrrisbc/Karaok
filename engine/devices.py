from __future__ import annotations

from typing import Any


def list_devices() -> list[dict[str, Any]]:
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    devices = sd.query_devices()
    rows: list[dict[str, Any]] = []
    for idx, dev in enumerate(devices):
        api = hostapis[int(dev["hostapi"])]
        rows.append(
            {
                "index": idx,
                "name": dev["name"],
                "hostapi": api["name"],
                "max_input_channels": int(dev["max_input_channels"]),
                "max_output_channels": int(dev["max_output_channels"]),
                "default_samplerate": float(dev["default_samplerate"]),
                "default_low_input_latency": float(dev.get("default_low_input_latency") or 0),
                "default_low_output_latency": float(dev.get("default_low_output_latency") or 0),
                "is_default_input": idx == sd.default.device[0],
                "is_default_output": idx == sd.default.device[1],
            }
        )
    return rows


def default_device_indices() -> tuple[int | None, int | None]:
    import sounddevice as sd

    inp, out = sd.default.device
    return (
        None if inp is None or inp < 0 else int(inp),
        None if out is None or out < 0 else int(out),
    )
