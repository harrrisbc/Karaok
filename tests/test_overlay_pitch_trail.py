from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pitch_highway_has_time_pitch_trail_canvas():
    html = (ROOT / "web" / "overlay.html").read_text(encoding="utf-8")
    assert 'id="pitchTrail"' in html
    assert 'class="pitch-trail"' in html


def test_pitch_highway_uses_center_playhead_and_tall_lane():
    js = (ROOT / "web" / "overlay.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "overlay.css").read_text(encoding="utf-8")
    assert "NOW_X_RATIO = 0.4" in js
    assert "TRAIL_WINDOW_SEC = 1.6" in js
    assert "height: 224px;" in css
    assert "height: 24px;" in css


def test_pitch_trail_records_voiced_pitch_by_time():
    js = (ROOT / "web" / "overlay.js").read_text(encoding="utf-8")
    assert "recordPitchTrail(state.nowSec, sungMidi)" in js
    assert "drawPitchTrail(state.nowSec)" in js


def test_playhead_uses_absolute_midi_not_cents_center():
    js = (ROOT / "web" / "overlay.js").read_text(encoding="utf-8")
    assert "function hzToMidi(" in js
    assert "function sungMidiFromState(" in js
    assert "function setMidiRange(" in js
    assert "setPitchMidi(sungMidi, state.cents)" in js
    # cents-only vertical centering must not be the live path anymore
    assert "setPitch(state.cents)" not in js
