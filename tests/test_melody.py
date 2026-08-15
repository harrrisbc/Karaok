import numpy as np

from engine.melody import (
    _frames_to_notes,
    _hz_to_midi,
    _midi_to_hz,
    _note_overlaps_windows,
    apply_voiced_energy_gate,
    fix_octave_outliers,
    refine_melody_with_lyrics,
)
from engine.melody_diag import note_coverage_vs_voiced
from engine.pack import create_pack


def test_midi_roundtrip():
    assert _hz_to_midi(440.0) == 69
    assert abs(_midi_to_hz(69) - 440.0) < 0.01


def test_frames_to_notes_holds_pitch():
    # 0.5s of A4 then 0.5s of C5 at hop ~0.05s
    hop = 0.05
    times = np.arange(0, 1.0, hop)
    f0 = np.array([440.0 if t < 0.5 else 523.25 for t in times])
    voiced = np.ones_like(times, dtype=bool)
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        min_note_sec=0.08,
        gap_merge_sec=0.05,
        smooth_frames=1,
        hysteresis_semitones=0.5,
        merge_semitones=0.0,
        merge_gap_sec=0.0,
    )
    assert len(notes) >= 2
    assert notes[0]["midi"] == 69
    assert notes[1]["midi"] == 72


def test_vibrato_stays_one_note():
    """±60¢ vibrato must not shatter into discarded semitone fragments."""
    hop = 0.023
    times = np.arange(0, 1.2, hop)
    # A4 with ±60 cents wobble — crosses semitone boundaries every cycle.
    cents = 60.0 * np.sin(2 * np.pi * 5.0 * times)
    f0 = 440.0 * (2.0 ** (cents / 1200.0))
    voiced = np.ones_like(times, dtype=bool)
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        min_note_sec=0.08,
        smooth_frames=9,
        hysteresis_semitones=1.0,
        merge_semitones=1.0,
        merge_gap_sec=0.12,
    )
    assert len(notes) == 1
    assert notes[0]["midi"] == 69
    assert notes[0]["duration"] >= 1.0
    assert "hz_median" in notes[0]
    assert "conf" in notes[0]


def test_short_fragments_absorbed_not_dropped():
    """Brief pitch blips merge into neighbour instead of vanishing."""
    hop = 0.05
    # Long A4, 2-frame B4 blip, long A4 again.
    midis = [69] * 20 + [71, 71] + [69] * 20
    times = np.arange(len(midis)) * hop
    f0 = np.array([440.0 * (2.0 ** ((m - 69) / 12.0)) for m in midis])
    voiced = np.ones(len(midis), dtype=bool)
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        min_note_sec=0.08,
        smooth_frames=5,
        hysteresis_semitones=1.0,
        merge_semitones=1.0,
        merge_gap_sec=0.12,
    )
    covered = sum(n["duration"] for n in notes)
    voiced_sec = (len(midis) - 1) * hop
    assert covered / voiced_sec >= 0.90
    # Should be mostly one A4 note (blip absorbed), not three with a hole.
    assert len(notes) <= 2
    assert any(n["midi"] == 69 for n in notes)


def test_fix_octave_outliers_folds_isolated_blip():
    notes = [
        {"t": 0.0, "duration": 0.3, "midi": 60, "hz": 261.626, "hz_mean": 261.0, "hz_median": 261.0},
        {"t": 0.4, "duration": 0.2, "midi": 72, "hz": 523.251, "hz_mean": 523.0, "hz_median": 523.0},
        {"t": 0.7, "duration": 0.3, "midi": 60, "hz": 261.626, "hz_mean": 261.0, "hz_median": 261.0},
    ]
    fixed, n = fix_octave_outliers(notes)
    assert n == 1
    assert fixed[1]["midi"] == 60
    assert abs(fixed[1]["hz"] - 261.626) < 1.0


def test_note_coverage_vs_voiced_helper():
    notes = [{"duration": 8.0}, {"duration": 2.0}]
    assert abs(note_coverage_vs_voiced(notes, voiced_sec=10.0) - 1.0) < 1e-6
    assert note_coverage_vs_voiced(notes, voiced_sec=0.0) == 0.0


def test_synthetic_coverage_high():
    hop = 0.05
    times = np.arange(0, 2.0, hop)
    f0 = np.full(len(times), 440.0)
    voiced = np.ones_like(times, dtype=bool)
    notes = _frames_to_notes(
        times=times,
        f0=f0,
        voiced=voiced,
        min_note_sec=0.08,
        smooth_frames=9,
        hysteresis_semitones=1.0,
    )
    voiced_sec = float(np.sum(voiced) - 1) * hop
    assert note_coverage_vs_voiced(notes, voiced_sec=voiced_sec) >= 0.90


def test_note_overlaps_windows():
    note = {"t": 10.0, "duration": 0.5}
    assert _note_overlaps_windows(note, [(9.5, 11.0)])
    assert not _note_overlaps_windows(note, [(0.0, 2.0)])


def test_soft_voiced_frames_survive_energy_gate():
    """Quiet but confident pyin frames must stay (soft verse openings)."""
    # Plenty of loud frames so p50 thr sits above the soft 0.01s.
    voiced_flag = np.array([True, True, True, True, True, False], dtype=bool)
    rms = np.array([0.01, 0.01, 0.20, 0.20, 0.20, 0.01], dtype=float)
    voiced_prob = np.array([0.85, 0.20, 0.40, 0.40, 0.40, 0.10], dtype=float)
    gated, thr = apply_voiced_energy_gate(
        voiced_flag,
        rms,
        voiced_prob,
        energy_percentile=50.0,
        soft_voiced_prob=0.6,
    )
    assert thr > 0.05
    assert gated.tolist() == [True, False, True, True, True, False]


def test_energy_gate_without_probs_keeps_only_loud_voiced():
    voiced_flag = np.array([True, True, False], dtype=bool)
    rms = np.array([0.01, 0.5, 0.5], dtype=float)
    gated, _thr = apply_voiced_energy_gate(
        voiced_flag,
        rms,
        None,
        energy_percentile=50.0,
    )
    assert gated.tolist() == [False, True, False]


def test_refine_melody_with_lyrics_drops_solo(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Solo Test", source="mp3")
    pack.melody.write_text(
        __import__("json").dumps(
            {
                "notes": [
                    {"t": 1.0, "duration": 0.4, "midi": 60},
                    {"t": 8.0, "duration": 1.0, "midi": 64},  # piano solo window
                    {"t": 12.0, "duration": 0.3, "midi": 62},
                ],
                "note_count": 3,
            }
        ),
        encoding="utf-8",
    )
    pack.lyrics.write_text(
        __import__("json").dumps(
            {
                "source": "lrclib",
                "method": "lrclib-direct",
                "lines": [
                    {"t": 0.8, "end": 1.6, "text": "a"},
                    {"t": 11.5, "end": 12.5, "text": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = refine_melody_with_lyrics(pack, pad_sec=0.2)
    assert out is not None
    assert out["note_count"] == 2
    assert [n["t"] for n in out["notes"]] == [1.0, 12.0]


def test_refine_skips_whisper_lyrics(tmp_path, monkeypatch):
    """Whisper line clocks are too gappy — keep full melody instead of chopping."""
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Whisper Sparse", source="mp3")
    notes = [
        {"t": 1.0, "duration": 0.4, "midi": 60},
        {"t": 8.0, "duration": 1.0, "midi": 64},
        {"t": 12.0, "duration": 0.3, "midi": 62},
    ]
    pack.melody.write_text(
        __import__("json").dumps({"notes": notes, "note_count": 3}),
        encoding="utf-8",
    )
    pack.lyrics.write_text(
        __import__("json").dumps(
            {
                "source": "whisper",
                "method": "openai-whisper",
                "lines": [
                    {"t": 0.8, "end": 1.6, "text": "a"},
                    {"t": 11.5, "end": 12.5, "text": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = refine_melody_with_lyrics(pack, pad_sec=0.2)
    assert out is None
    kept = __import__("json").loads(pack.melody.read_text(encoding="utf-8"))
    assert kept["note_count"] == 3
    assert len(kept["notes"]) == 3


def test_refine_aborts_when_drop_too_aggressive(tmp_path, monkeypatch):
    """Trusted LRC still must not wipe a large chart when windows are sparse."""
    monkeypatch.setattr("engine.pack.SONGS_DIR", tmp_path)
    monkeypatch.setattr("engine.paths.SONGS_DIR", tmp_path)
    pack = create_pack("Sparse Guard", source="mp3")
    notes = [{"t": float(i), "duration": 0.3, "midi": 60 + (i % 5)} for i in range(50)]
    pack.melody.write_text(
        __import__("json").dumps({"notes": notes, "note_count": 50}),
        encoding="utf-8",
    )
    pack.lyrics.write_text(
        __import__("json").dumps(
            {
                "source": "lrclib",
                "method": "lrclib-direct",
                # Only covers a few notes → would drop most of the chart.
                "lines": [
                    {"t": 0.0, "end": 1.5, "text": "a"},
                    {"t": 40.0, "end": 41.5, "text": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = refine_melody_with_lyrics(pack, pad_sec=0.2)
    assert out is None
    kept = __import__("json").loads(pack.melody.read_text(encoding="utf-8"))
    assert kept["note_count"] == 50
