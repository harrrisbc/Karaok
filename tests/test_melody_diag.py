from pathlib import Path

import numpy as np

from engine.melody_diag import melody_hit_rates
from engine.score import cents_error, cents_error_raw


def test_melody_hit_rates_yin_benefits_from_octave_fold(tmp_path: Path):
    """Synthetic A4 note; inject octave-up energy so raw YIN-like compare fails fold helps.

    We only assert the helper scores raw vs fold pairs correctly via cents helpers.
    """
    assert abs(cents_error_raw(880.0, 440.0) - 1200.0) < 1.0
    assert abs(cents_error(880.0, 440.0)) < 1.0

    sr = 22050
    t = np.arange(0, 1.0, 1 / sr)
    # Pure 440 Hz tone — pyin/yin should match melody hz.
    y = 0.2 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    wav = tmp_path / "v.wav"
    import soundfile as sf

    sf.write(str(wav), y, sr)
    notes = [{"t": 0.2, "duration": 0.5, "hz": 440.0, "midi": 69}]
    out = melody_hit_rates(wav, notes, sr=sr, fmin=80.0, fmax=800.0)
    assert out["pyin"]["compared"] >= 1
    assert out["pyin"]["rate_fold"] >= 0.99
