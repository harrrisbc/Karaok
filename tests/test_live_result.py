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
