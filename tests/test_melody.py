import numpy as np

from engine.melody import (
    _frames_to_notes,
    _hz_to_midi,
    _midi_to_hz,
    _note_overlaps_windows,
    refine_melody_with_lyrics,
)
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
    )
    assert len(notes) >= 2
    assert notes[0]["midi"] == 69
    assert notes[1]["midi"] == 72


def test_note_overlaps_windows():
    note = {"t": 10.0, "duration": 0.5}
    assert _note_overlaps_windows(note, [(9.5, 11.0)])
    assert not _note_overlaps_windows(note, [(0.0, 2.0)])


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
                "lines": [
                    {"t": 0.8, "end": 1.6, "text": "a"},
                    {"t": 11.5, "end": 12.5, "text": "b"},
                ]
            }
        ),
        encoding="utf-8",
    )
    out = refine_melody_with_lyrics(pack, pad_sec=0.2)
    assert out is not None
    assert out["note_count"] == 2
    assert [n["t"] for n in out["notes"]] == [1.0, 12.0]
