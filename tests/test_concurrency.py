from types import SimpleNamespace

from engine.concurrency import (
    asr_device,
    gpu_job_blocks_live,
    live_audio_active,
    set_live_audio,
)


def setup_function() -> None:
    set_live_audio(False)


def test_asr_device_forces_cpu_while_live_audio():
    set_live_audio(True)
    assert live_audio_active() is True
    assert asr_device() == "cpu"
    assert asr_device("cuda") == "cpu"
    set_live_audio(False)
    # Without live, preferred cuda is honored when asked explicitly.
    assert asr_device("cpu") == "cpu"


def test_gpu_job_blocks_live_on_lyrics_and_split():
    lyrics = SimpleNamespace(status="running", step="lyrics (large-v3)", kind="analyze", pack_id="x")
    split = SimpleNamespace(status="running", step="split", kind="import_youtube", pack_id="y")
    melody = SimpleNamespace(status="running", step="melody", kind="analyze", pack_id="z")
    assert gpu_job_blocks_live(lyrics)
    assert gpu_job_blocks_live(split)
    assert gpu_job_blocks_live(melody) is None
    assert gpu_job_blocks_live(None) is None
