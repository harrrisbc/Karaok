from __future__ import annotations

import numpy as np


def yin_f0(
    frame: np.ndarray,
    sr: int,
    *,
    fmin: float = 80.0,
    fmax: float = 800.0,
    threshold: float = 0.15,
) -> tuple[float | None, float]:
    """Return (hz or None, voiced_confidence 0..1) for one mono frame."""
    x = np.asarray(frame, dtype=np.float64)
    if x.size < 32 or not np.any(x):
        return None, 0.0
    x = x - np.mean(x)
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1e-4:
        return None, 0.0

    tau_min = max(2, int(sr / fmax))
    tau_max = min(len(x) // 2 - 1, int(sr / fmin))
    if tau_max <= tau_min + 2:
        return None, 0.0

    # Difference function
    w = len(x)
    df = np.empty(tau_max + 1, dtype=np.float64)
    df[0] = 0.0
    for tau in range(1, tau_max + 1):
        diff = x[: w - tau] - x[tau:]
        df[tau] = float(np.dot(diff, diff))

    # Cumulative mean normalized difference
    cmnd = np.ones_like(df)
    running = 0.0
    for tau in range(1, tau_max + 1):
        running += df[tau]
        cmnd[tau] = df[tau] * tau / running if running > 0 else 1.0

    tau = tau_min
    found = None
    while tau < tau_max:
        if cmnd[tau] < threshold:
            while tau + 1 < tau_max and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
            found = tau
            break
        tau += 1
    if found is None:
        found = int(tau_min + np.argmin(cmnd[tau_min : tau_max + 1]))
        if cmnd[found] > 0.45:
            return None, float(max(0.0, 1.0 - cmnd[found]))

    # Parabolic interpolation
    if 1 <= found < len(cmnd) - 1:
        a, b, c = cmnd[found - 1], cmnd[found], cmnd[found + 1]
        denom = a - 2 * b + c
        if denom != 0:
            found = found + (a - c) / (2 * denom)

    hz = sr / float(found)
    if hz < fmin or hz > fmax:
        return None, 0.0
    conf = float(max(0.0, min(1.0, 1.0 - cmnd[int(round(found))])))
    return hz, conf
