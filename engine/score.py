from __future__ import annotations

import math
from typing import Any

HP_DRAIN_PER_SEC = 10.0
PITCH_CENTS_LIMIT = 50.0
TIMING_LIMIT_SEC = 0.09

# Operator desk presets — higher cents/timing = more forgiving; lower drain = slower fail.
DIFFICULTY_PRESETS: dict[str, dict[str, float | str]] = {
    "easy": {
        "label": "Easy",
        "cents_limit": 80.0,
        "timing_limit": 0.15,
        "drain_per_sec": 6.0,
    },
    "normal": {
        "label": "Normal",
        "cents_limit": 50.0,
        "timing_limit": 0.09,
        "drain_per_sec": 10.0,
    },
    "hard": {
        "label": "Hard",
        "cents_limit": 35.0,
        "timing_limit": 0.06,
        "drain_per_sec": 14.0,
    },
    "expert": {
        "label": "Expert",
        "cents_limit": 25.0,
        "timing_limit": 0.045,
        "drain_per_sec": 18.0,
    },
}
DEFAULT_DIFFICULTY = "normal"


def difficulty_params(name: str | None) -> dict[str, float | str]:
    key = (name or DEFAULT_DIFFICULTY).strip().lower()
    if key not in DIFFICULTY_PRESETS:
        key = DEFAULT_DIFFICULTY
    preset = DIFFICULTY_PRESETS[key]
    return {"id": key, **preset}


def clamp_cents_limit(value: float) -> float:
    return float(max(15.0, min(120.0, float(value))))


def clamp_timing_limit(value: float) -> float:
    """Clamp timing threshold in seconds (± window for EARLY/LATE)."""
    return float(max(0.03, min(0.25, float(value))))


def cents_error_raw(sung_hz: float, expected_hz: float) -> float:
    """Signed cents with no octave folding (diagnostic / legacy)."""
    if sung_hz <= 0 or expected_hz <= 0:
        return 0.0
    return 1200.0 * math.log2(sung_hz / expected_hz)


def cents_error(sung_hz: float, expected_hz: float, *, octaves: int = 2) -> float:
    """Signed cents after folding sung pitch into the nearest octave of expected.

    Live YIN and melody pyin often disagree by ±1 octave; without folding,
    |cents| ≈ 1200 and blue hits almost never light.
    """
    if sung_hz <= 0 or expected_hz <= 0:
        return 0.0
    best = cents_error_raw(sung_hz, expected_hz)
    for k in range(1, max(0, int(octaves)) + 1):
        for factor in (2.0**k, 0.5**k):
            cand = cents_error_raw(sung_hz * factor, expected_hz)
            if abs(cand) < abs(best):
                best = cand
    return best


def align_time(
    playback_pos: float,
    output_ms: float,
    input_ms: float,
    trim_ms: float = 0.0,
) -> float:
    """Time on the melody/lyric timeline corresponding to the current mic frame."""
    return playback_pos - (output_ms / 1000.0) + (input_ms / 1000.0) + (trim_ms / 1000.0)


def note_at(notes: list[dict], t: float) -> dict | None:
    if t < 0 or not notes:
        return None
    lo, hi = 0, len(notes) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        n = notes[mid]
        start = float(n["t"])
        end = start + float(n["duration"])
        if t < start:
            hi = mid - 1
        elif t > end:
            lo = mid + 1
        else:
            return n
    # nearest in a small window (gaps between notes)
    i = min(max(lo, 0), len(notes) - 1)
    for j in (i, i - 1, i + 1):
        if 0 <= j < len(notes):
            n = notes[j]
            start = float(n["t"])
            end = start + float(n["duration"])
            if start - 0.04 <= t <= end + 0.04:
                best = n
    return best


def _linear_line_progress(line: dict, t: float) -> float:
    start = float(line["t"])
    end = float(line.get("end") or start)
    return max(0.0, min(1.0, (t - start) / max(1e-6, end - start)))


def _compact_text(text: object) -> str:
    return "".join(str(text or "").split())


def _line_words(line: dict, words: list[dict] | None) -> list[dict]:
    """Prefer line-owned words; otherwise select pack words by their midpoint."""
    candidates = list(line.get("words") or [])
    if not candidates and words:
        start = float(line["t"]) - 0.05
        end = float(line.get("end") or line["t"]) + 0.05
        candidates = [
            word
            for word in words
            if start <= (float(word.get("t", 0.0)) + float(word.get("end", word.get("t", 0.0)))) / 2 <= end
        ]

    timed = []
    for word in candidates:
        text = str(word.get("text") or word.get("word") or "").strip()
        try:
            start = float(word["t"] if "t" in word else word["start"])
            end = float(word.get("end", word.get("end", start)))
        except (KeyError, TypeError, ValueError):
            continue
        if text and end >= start:
            timed.append({"t": start, "end": end, "text": text})
    return sorted(timed, key=lambda word: (word["t"], word["end"]))


def progress_in_line(line: dict, t: float, words: list[dict] | None = None) -> float:
    """Return a 0–1 lyric sweep, using word timestamps when they cover the line."""
    timed = _line_words(line, words)
    line_text = _compact_text(line.get("text"))
    token_text = "".join(_compact_text(word["text"]) for word in timed)
    if len(timed) < 2 or not line_text or token_text != line_text:
        return _linear_line_progress(line, t)

    weights = [max(1, len(_compact_text(word["text"]))) for word in timed]
    total = sum(weights)
    if t < timed[0]["t"]:
        return 0.0

    completed = 0
    for word, weight in zip(timed, weights):
        start, end = word["t"], word["end"]
        if t < start:
            # A timing gap holds at the previous word boundary.
            return completed / total
        if t < end:
            fraction = (t - start) / max(1e-6, end - start)
            return max(0.0, min(1.0, (completed + weight * fraction) / total))
        completed += weight
    return 1.0


def line_at(
    lines: list[dict],
    t: float,
    words: list[dict] | None = None,
) -> tuple[dict | None, dict | None, float]:
    current = None
    nxt = None
    progress = 0.0
    for i, line in enumerate(lines):
        start = float(line["t"])
        end = float(line.get("end") or start)
        if start <= t <= end:
            current = line
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            progress = progress_in_line(line, t, words)
            break
        if t < start:
            nxt = line
            current = lines[i - 1] if i else None
            progress = 1.0 if current is not None else 0.0
            break
    if current is None and nxt is None and lines and t > float(lines[-1].get("end") or 0):
        current = lines[-1]
        progress = 1.0
    return current, nxt, progress


def badges_for(
    *,
    cents: float | None,
    voiced: bool,
    align_t: float,
    note: dict | None,
    cents_limit: float = PITCH_CENTS_LIMIT,
    timing_limit: float = 0.09,
) -> list[str]:
    out: list[str] = []
    if not voiced or cents is None or note is None:
        return out
    if cents < -cents_limit:
        out.append("flat")
    elif cents > cents_limit:
        out.append("sharp")
    start = float(note["t"])
    lag = align_t - start
    if abs(lag) <= 0.2:
        if lag < -timing_limit:
            out.append("early")
        elif lag > timing_limit:
            out.append("late")
    return out


class HealthPoints:
    """Show HP: drains on bad pitch/timing. Manual heal via operator desk."""

    def __init__(
        self,
        *,
        cents_limit: float = PITCH_CENTS_LIMIT,
        drain_per_sec: float = HP_DRAIN_PER_SEC,
        invincible: bool = False,
    ) -> None:
        self.pitch = 100.0
        self.rhythm = 100.0
        self.cents_limit = float(cents_limit)
        self.drain_per_sec = float(drain_per_sec)
        self.invincible = bool(invincible)

    @property
    def dead(self) -> bool:
        if self.invincible:
            return False
        return self.pitch <= 0.0 or self.rhythm <= 0.0

    @property
    def fail_reason(self) -> str | None:
        if self.invincible:
            return None
        if self.pitch <= 0.0:
            return "pitch"
        if self.rhythm <= 0.0:
            return "rhythm"
        return None

    def configure(self, *, cents_limit: float, drain_per_sec: float) -> None:
        self.cents_limit = float(cents_limit)
        self.drain_per_sec = float(drain_per_sec)

    def set_invincible(self, enabled: bool) -> None:
        self.invincible = bool(enabled)
        if self.invincible:
            self.pitch = 100.0
            self.rhythm = 100.0

    def heal(self, amount: float = 10.0) -> None:
        """Add HP to both bars (operator mercy). Does not un-fail a stopped take."""
        bump = max(0.0, float(amount))
        self.pitch = min(100.0, self.pitch + bump)
        self.rhythm = min(100.0, self.rhythm + bump)

    def tick(
        self,
        *,
        voiced: bool,
        cents: float | None,
        badges: list[str],
        dt: float,
    ) -> None:
        if self.invincible or self.dead or dt <= 0:
            return
        if voiced and cents is not None and abs(cents) >= self.cents_limit:
            self.pitch = max(0.0, self.pitch - self.drain_per_sec * dt)
        if "early" in badges or "late" in badges:
            self.rhythm = max(0.0, self.rhythm - self.drain_per_sec * dt)

    def as_dict(self) -> dict[str, float]:
        return {
            "pitch": round(self.pitch, 1),
            "rhythm": round(self.rhythm, 1),
        }

class RunningSkill:
    def __init__(self) -> None:
        self.pitch = 50.0
        self.rhythm = 50.0
        self.stable = 50.0
        self._last_cents: float | None = None

    def update(self, *, voiced: bool, cents: float | None, badges: list[str]) -> None:
        a = 0.08
        if voiced and cents is not None:
            pitch_hit = max(0.0, 1.0 - abs(cents) / 100.0)
            self.pitch += a * (pitch_hit * 100.0 - self.pitch)
            timing_ok = "early" not in badges and "late" not in badges
            self.rhythm += a * ((85.0 if timing_ok else 35.0) - self.rhythm)
            if self._last_cents is not None:
                jitter = abs(cents - self._last_cents)
                stable_hit = max(0.0, 1.0 - jitter / 40.0)
                self.stable += a * (stable_hit * 100.0 - self.stable)
            self._last_cents = cents
        else:
            self.pitch += a * (40.0 - self.pitch)
            self._last_cents = None

    def as_dict(self) -> dict[str, int]:
        return {
            "pitch": int(round(self.pitch)),
            "rhythm": int(round(self.rhythm)),
            "stable": int(round(self.stable)),
        }


def score_snapshot(
    *,
    playback_pos: float,
    duration: float,
    output_ms: float,
    input_ms: float,
    trim_ms: float,
    sung_hz: float | None,
    voiced: bool,
    notes: list[dict],
    lines: list[dict],
    skill: RunningSkill,
    hp: HealthPoints,
    title: str,
    singer: str = "",
    dt: float = 0.0,
    words: list[dict] | None = None,
    cents_limit: float = PITCH_CENTS_LIMIT,
    timing_limit: float = TIMING_LIMIT_SEC,
) -> dict[str, Any]:
    align_t = align_time(playback_pos, output_ms, input_ms, trim_ms)
    note = note_at(notes, align_t)
    expected_hz = float(note["hz"]) if note else None
    cents = None
    if voiced and sung_hz and expected_hz:
        cents = cents_error(sung_hz, expected_hz)
    flags = badges_for(
        cents=cents,
        voiced=voiced,
        align_t=align_t,
        note=note,
        cents_limit=cents_limit,
        timing_limit=timing_limit,
    )
    skill.update(voiced=voiced and cents is not None, cents=cents, badges=flags)
    hp.tick(voiced=voiced and cents is not None, cents=cents, badges=flags, dt=dt)
    meters = skill.as_dict()
    cur, nxt, progress = line_at(lines, align_t, words)
    remaining = max(0.0, duration - playback_pos)
    in_tune = abs(cents) < (cents_limit * 0.7) if cents is not None else False
    score = (meters["pitch"] * 0.5 + meters["rhythm"] * 0.3 + meters["stable"] * 0.2)
    return {
        "type": "frame",
        "t": round(align_t, 4),
        "playback_t": round(playback_pos, 4),
        "align_t": round(align_t, 4),
        "nowSec": round(align_t, 4),
        "f0": None if sung_hz is None else round(sung_hz, 2),
        "expected_hz": None if expected_hz is None else round(expected_hz, 2),
        "cents": None if cents is None else round(cents, 1),
        "badges": flags,
        "pitch": meters["pitch"],
        "rhythm": meters["rhythm"],
        "stable": meters["stable"],
        "hp": hp.as_dict(),
        "failed": hp.dead,
        "fail_reason": hp.fail_reason,
        "score": round(score, 1),
        "title": title,
        "singer": singer,
        "lyricNow": (cur or {}).get("text") or "",
        "lyricNext": (nxt or {}).get("text") or "",
        "lyricProgress": round(progress, 3) if cur else None,
        "remaining": round(remaining, 2),
        "in_tune": in_tune,
        "latency": {
            "input_ms": round(input_ms, 1),
            "output_ms": round(output_ms, 1),
            "trim_ms": round(trim_ms, 1),
            "foh_vocal_delay_ms": round(output_ms, 1),
        },
    }


def stars_for_score(score: float) -> int:
    if score >= 90:
        return 3
    if score >= 75:
        return 2
    if score >= 60:
        return 1
    return 0


def build_clear_result(
    *,
    title: str,
    singer: str,
    score: float,
    hp: dict[str, float],
    pitch: int | float,
    rhythm: int | float,
    stable: int | float,
    difficulty: str,
) -> dict[str, Any]:
    return {
        "type": "result",
        "outcome": "clear",
        "title": title,
        "singer": singer,
        "score": round(float(score), 1),
        "hp": {
            "pitch": round(float(hp.get("pitch", 0)), 1),
            "rhythm": round(float(hp.get("rhythm", 0)), 1),
        },
        "pitch": int(round(float(pitch))),
        "rhythm": int(round(float(rhythm))),
        "stable": int(round(float(stable))),
        "difficulty": difficulty,
        "stars": stars_for_score(float(score)),
    }