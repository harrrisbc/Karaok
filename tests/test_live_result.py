from engine.live import LiveSession
from engine.score import HealthPoints, RunningSkill


def _session_with_take() -> LiveSession:
    sess = LiveSession()
    sess.title = "Test Song"
    sess.singer = "Haris"
    sess.difficulty = "normal"
    sess.running = True
    sess.failed = False
    sess.cleared = False
    sess._skill = RunningSkill()
    sess._skill.pitch = 80
    sess._skill.rhythm = 70
    sess._skill.stable = 75
    sess._hp = HealthPoints()
    sess._hp.pitch = 62
    sess._hp.rhythm = 81
    sess.latest = {
        "type": "frame",
        "score": 87.3,
        "pitch": 80,
        "rhythm": 70,
        "stable": 75,
        "hp": {"pitch": 62, "rhythm": 81},
    }
    return sess


def test_natural_end_clears_when_hp_alive():
    sess = _session_with_take()
    sess._freeze_clear_if_alive()
    assert sess.cleared is True
    assert sess.failed is False
    assert sess.latest["type"] == "result"
    assert sess.latest["outcome"] == "clear"
    assert sess.latest["stars"] == 2
    assert sess.latest["score"] == 87.3


def test_natural_end_skipped_when_failed():
    sess = _session_with_take()
    sess.failed = True
    sess.latest = {"type": "frame", "failed": True, "fail_reason": "pitch"}
    sess._freeze_clear_if_alive()
    assert sess.cleared is False
    assert sess.latest["type"] == "frame"


def test_natural_end_skipped_when_hp_dead():
    sess = _session_with_take()
    sess._hp.pitch = 0
    sess._freeze_clear_if_alive()
    assert sess.cleared is False


def test_stop_aborts_without_clear():
    sess = _session_with_take()
    sess.stop()
    assert sess.cleared is False
    assert sess.failed is False
    assert sess.latest == {"type": "idle"}


def test_start_does_not_drop_model_cache():
    import inspect

    src = inspect.getsource(LiveSession.start)
    assert "drop_model_cache" not in src


def test_set_thresholds_overrides_pitch_and_tempo_independently():
    sess = LiveSession()
    sess.set_difficulty("hard")
    assert sess.cents_limit == 35.0
    assert abs(sess.timing_limit - 0.06) < 1e-9
    out = sess.set_thresholds(cents_limit=70.0)
    assert out["cents_limit"] == 70.0
    assert abs(out["timing_limit"] - 0.06) < 1e-9
    out = sess.set_thresholds(timing_limit=0.12)
    assert out["cents_limit"] == 70.0
    assert abs(out["timing_limit"] - 0.12) < 1e-9
    status = sess.status()
    assert status["cents_limit"] == 70.0
    assert abs(status["timing_limit"] - 0.12) < 1e-9
