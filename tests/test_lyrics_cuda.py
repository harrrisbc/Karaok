from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from engine.lyrics import drop_model_cache, extract_lyrics, release_cuda
from engine.pack import create_pack


def _cuda_mem_mb() -> float:
    import torch

    torch.cuda.synchronize()
    return torch.cuda.memory_reserved() / (1024 * 1024)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("torch") is None,
    reason="torch not installed",
)
def test_large_v3_releases_cuda_when_cache_dropped(tmp_path, monkeypatch):
    import torch

    if not torch.cuda.is_available():
        pytest.skip("no CUDA")
    cache = Path.home() / ".cache" / "whisper" / "large-v3.pt"
    if not cache.exists():
        pytest.skip("large-v3.pt not downloaded")

    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("vram-probe", source="file", lyrics_lang="english")
    # 1.5s of quiet audio — we are testing VRAM release, not lyric quality.
    sf.write(pack.vocals, np.zeros(24000, dtype=np.float32), 16000)

    release_cuda()
    before = _cuda_mem_mb()
    payload = extract_lyrics(pack, model_name="large-v3", language="english")
    cached = _cuda_mem_mb()
    drop_model_cache()
    after = _cuda_mem_mb()

    assert payload["model"] == "large-v3"
    assert cached > 1500, f"Whisper model was unexpectedly not cached: {cached:.0f} MiB"
    # Demucs / Live use this explicit cache clear before consuming GPU VRAM.
    assert after < 1500, f"CUDA still reserved {after:.0f} MiB (was {before:.0f})"
