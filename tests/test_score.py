from engine.score import (
    HP_DRAIN_PER_SEC,
    HealthPoints,
    RunningSkill,
    align_time,
    badges_for,
    cents_error,
    line_at,
    note_at,
    progress_in_line,
    score_snapshot,
)


def test_cents_unison_and_semitone():
    assert abs(cents_error(440.0, 440.0)) < 0.01
    # 1 semitone up ≈ 100 cents
    assert abs(cents_error(440.0 * (2 ** (1 / 12)), 440.0) - 100.0) < 0.5


def test_align_time_formula():
    # playback 1.000s, hear track 28ms late, mic 12ms late, trim 0
    # → compare at 1.000 - 0.028 + 0.012 = 0.984
    t = align_time(1.0, output_ms=28, input_ms=12, trim_ms=0)
    assert abs(t - 0.984) < 1e-9
    t2 = align_time(1.0, 28, 12, trim_ms=10)
    assert abs(t2 - 0.994) < 1e-9


def test_note_at_and_badges():
    notes = [
        {"t": 1.0, "duration": 0.5, "hz": 220.0, "midi": 57},
        {"t": 2.0, "duration": 0.5, "hz": 247.0, "midi": 59},
    ]
    n = note_at(notes, 1.2)
    assert n is not None and n["midi"] == 57
    assert note_at(notes, 0.1) is None
    cents = cents_error(196.0, 220.0)  # flat
    flags = badges_for(cents=cents, voiced=True, align_t=1.25, note=notes[0])
    assert "flat" in flags
    early = badges_for(cents=0.0, voiced=True, align_t=0.88, note=notes[0])
    assert "early" in early


def test_line_at_progress():
    lines = [
        {"t": 0.0, "end": 2.0, "text": "hello"},
        {"t": 2.0, "end": 4.0, "text": "world"},
    ]
    cur, nxt, prog = line_at(lines, 1.0)
    assert cur["text"] == "hello"
    assert nxt["text"] == "world"
    assert abs(prog - 0.5) < 1e-6


def test_line_at_previews_next_in_intro_and_gap():
    lines = [
        {"t": 2.0, "end": 4.0, "text": "a"},
        {"t": 6.0, "end": 8.0, "text": "b"},
    ]
    cur, nxt, prog = line_at(lines, 0.5)
    assert cur is None
    assert nxt["text"] == "a"
    assert prog == 0.0
    cur, nxt, prog = line_at(lines, 5.0)
    assert cur["text"] == "a"
    assert nxt["text"] == "b"
    assert prog == 1.0


def test_progress_in_line_falls_back_to_linear_without_words():
    line = {"t": 0.0, "end": 4.0, "text": "abcd"}
    assert abs(progress_in_line(line, 1.0) - 0.25) < 1e-6
    assert abs(progress_in_line(line, 1.0, [{"t": 0, "end": 1, "text": "nope"}]) - 0.25) < 1e-6


def test_progress_in_line_uses_word_timestamps_and_holds_gaps():
    line = {"t": 0.0, "end": 4.0, "text": "朋友"}
    words = [
        {"t": 0.0, "end": 1.0, "text": "朋"},
        {"t": 3.0, "end": 4.0, "text": "友"},
    ]
    assert abs(progress_in_line(line, -0.1, words) - 0.0) < 1e-6
    assert abs(progress_in_line(line, 0.5, words) - 0.25) < 1e-6
    # The 1–3s gap holds at the first word boundary instead of creeping linearly.
    assert abs(progress_in_line(line, 2.0, words) - 0.5) < 1e-6
    assert abs(progress_in_line(line, 3.5, words) - 0.75) < 1e-6
    assert abs(progress_in_line(line, 4.1, words) - 1.0) < 1e-6


def test_line_at_uses_top_level_word_timestamps():
    lines = [{"t": 0.0, "end": 4.0, "text": "朋友"}]
    words = [
        {"t": 0.0, "end": 1.0, "text": "朋"},
        {"t": 3.0, "end": 4.0, "text": "友"},
    ]
    current, _, progress = line_at(lines, 2.0, words)
    assert current == lines[0]
    assert abs(progress - 0.5) < 1e-6


def test_hp_starts_full():
    hp = HealthPoints()
    assert hp.pitch == 100.0
    assert hp.rhythm == 100.0
    assert hp.dead is False
    assert hp.fail_reason is None


def test_hp_unvoiced_does_not_drain():
    hp = HealthPoints()
    hp.tick(voiced=False, cents=None, badges=[], dt=1.0)
    assert hp.pitch == 100.0
    assert hp.rhythm == 100.0


def test_hp_in_tune_does_not_drain_pitch():
    hp = HealthPoints()
    hp.tick(voiced=True, cents=20.0, badges=[], dt=1.0)
    assert hp.pitch == 100.0


def test_hp_flat_drains_pitch_only():
    hp = HealthPoints()
    hp.tick(voiced=True, cents=-80.0, badges=["flat"], dt=1.0)
    assert abs(hp.pitch - (100.0 - HP_DRAIN_PER_SEC)) < 1e-6
    assert hp.rhythm == 100.0


def test_hp_late_drains_rhythm_only():
    hp = HealthPoints()
    hp.tick(voiced=True, cents=10.0, badges=["late"], dt=1.0)
    assert hp.pitch == 100.0
    assert abs(hp.rhythm - (100.0 - HP_DRAIN_PER_SEC)) < 1e-6


def test_hp_does_not_recover():
    hp = HealthPoints()
    hp.tick(voiced=True, cents=-80.0, badges=["flat"], dt=2.0)
    drained = hp.pitch
    hp.tick(voiced=True, cents=0.0, badges=[], dt=2.0)
    assert hp.pitch == drained


def test_hp_pitch_zero_is_dead():
    hp = HealthPoints()
    hp.tick(voiced=True, cents=-80.0, badges=["flat"], dt=12.0)
    assert hp.pitch == 0.0
    assert hp.dead is True
    assert hp.fail_reason == "pitch"
    hp.tick(voiced=True, cents=-80.0, badges=["flat"], dt=1.0)
    assert hp.pitch == 0.0


def test_score_snapshot_includes_hp_and_fail():
    notes = [{"t": 0.0, "duration": 20.0, "hz": 220.0, "midi": 57}]
    hp = HealthPoints()
    skill = RunningSkill()
    snap = score_snapshot(
        playback_pos=1.0,
        duration=20.0,
        output_ms=0,
        input_ms=0,
        trim_ms=0,
        sung_hz=196.0,
        voiced=True,
        notes=notes,
        lines=[],
        skill=skill,
        hp=hp,
        dt=12.0,
        title="R7",
        singer="Haris",
    )
    assert snap["title"] == "R7"
    assert snap["singer"] == "Haris"
    assert snap["hp"]["pitch"] == 0.0
    assert snap["failed"] is True
    assert snap["fail_reason"] == "pitch"
