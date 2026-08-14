# P1-4 — Word-level lyric highlight

Status: implemented 2026-08-14  
Parent: [enhancements-from-nightingale.md](enhancements-from-nightingale.md) §4  
Audience: engineer implementing this change

## Decision

Drive the overlay lyric sweep from **real word/char timestamps** when `lyrics.json` has them. Keep the existing `lyricProgress` (0–1) frame field so the overlay API stays compatible. Fall back to today’s linear line interpolation when no usable words exist (common for `lrclib-direct`).

Do **not** invent a second sweep UI. Do **not** require Enhanced LRC. Do **not** block on regenerating word timings for every LRCLIB pack in this ticket — fallback is fine.

## Problem today

`engine/score.py` `line_at()` returns progress as `(t - line.t) / (line.end - line.t)` — uniform across the whole line.

`web/overlay.js` `setLyricLine()` maps that progress to character index:

```js
const cut = Math.floor(lyricChars.length * lyricProgress);
```

Long Cantonese lines (e.g. 「仍然沒有遇到那位跟我絕配的戀人」) hold uneven syllable lengths. Linear sweep lights characters early or late vs the sung mouth shape. Pitch highway can look right while the lyric pill drifts.

We already store timings in many packs:

| Source | Typical `words` |
| --- | --- |
| Whisper / `lyric-txt-correct` / stable-ts align | Top-level `words[]` with per-char `{t,end,text}` (often populated) |
| `lrclib-direct` (trust-lrc) | Usually **empty** — line-level only (+ optional Enhanced LRC words if present) |

Measured on this machine (2026-08-14): `信心花舍` / some corrected packs have hundreds of words; LRCLIB 1874 has `n_words=0`.

## Goal

1. When the current line has usable word timings, `lyricProgress` reflects **how far through those words** we are at `align_t`, not wall-clock fraction of the line.
2. When words are missing / unusable, behaviour matches today (linear).
3. Overlay keeps one sweep; no layout redesign.
4. Intro / gap preview (`lyricNext` with `lyricProgress` null or previous line done) unchanged.

## Design

### Progress from words

Add in `engine/score.py`:

```python
def progress_in_line(line: dict, t: float, words: list[dict] | None = None) -> float:
    """0–1 sweep position inside the current line."""
```

Rules:

1. Collect candidate words for this line (see “Word selection” below).
2. If fewer than 2 timed tokens, or tokens don’t cover the line text reasonably → linear fallback: `(t - start) / (end - start)`, clamped 0–1.
3. Else:
   - If `t` before first word start → `0.0`
   - If `t` after last word end → `1.0`
   - If inside word `i` with `start_i <= t < end_i` → `(i + frac) / N` where `frac = (t - start_i) / max(eps, end_i - start_i)` and `N = len(words)`
   - If in a gap between word `i` and `i+1` → treat as end of word `i` (progress `(i+1)/N`) so the sweep doesn’t freeze mid-gap awkwardly — or hold at `(i + 1) / N` without fractional crawl; pick one and test on a long line.

Keep `line_at()` returning `(current, next, progress)` but compute `progress` via `progress_in_line` when `current` is set. Optionally change signature to accept pack-level `words`.

### Word selection

Prefer, in order:

1. `line["words"]` if present and non-empty (Enhanced LRC / future per-line schema).
2. Else filter top-level `lyrics["words"]` to tokens whose midpoint (or start) falls in `[line.t - pad, line.end + pad]` with `pad ≈ 0.05`.
3. Else linear.

CJK: Whisper often emits one Chinese character per word entry. Spaces in `line.text` should be ignored when comparing coverage; overlay already spreads spaces as `&nbsp;` spans — progress should be over **display characters** of `line.text` (`[...str]` in JS), so either:

- **A (preferred):** Keep computing progress 0–1 in Python; overlay continues to map progress → character cut. Word-based progress must be scaled so that finishing word `k` of `N` roughly matches the character index of that token in the line string.
- **B:** Send `lyricCharIndex` / `lyricCut` explicitly and let overlay use that.

Prefer **A** to avoid breaking preview mode and older clients: only change how `lyricProgress` is computed.

**Character alignment helper (needed for A):** map each timed token onto a span of the line’s display chars (strip nothing the overlay keeps). If token texts concatenate (ignoring spaces) to the line (ignoring spaces), assign each token a char weight = `len(token.text)` (or 1 if empty). Progress = weighted position through tokens, then map to 0–1 over total weight. That keeps 「朋友 我」 spaces from desyncing the cut.

### Wiring

| File | Change |
| --- | --- |
| `engine/score.py` | `progress_in_line`, update `line_at` and/or `score_snapshot` to take `words` |
| `engine/live.py` (or wherever lyrics load into the session) | Pass `words` from `lyrics.json` into `score_snapshot` |
| `web/overlay.js` | No API change required if progress stays 0–1; optional: when `lyricProgress` jumps at word boundaries, keep existing span classes |
| `tests/test_score.py` | Unit tests for word progress + linear fallback |

Out of scope for this ticket unless cheap:

- Backfilling word timings onto existing `lrclib-direct` packs (would need align or uniform split).
- Jyutping row (P2 item 5) — needs this progress model first, but separate UI.

### Optional follow-up (not required to close)

If product wants word sweep on LRCLIB packs without Whisper: uniform-split each line’s characters across `[line.t, line.end]` when writing `trust-lrc` payload. That is synthetic, not sung-aligned — better than nothing, worse than Whisper words. Call it out in the PR if you add it; default leave empty + linear.

## Acceptance

1. Pack with non-empty `words` (e.g. a `lyric-txt-correct` song): during a line, the lit character tracks syllable timing better than linear (manual listen on one long line is enough).
2. Pack with empty `words` (`lrclib-direct`): sweep behaviour identical to pre-change linear.
3. Intro: `lyricNow` empty / previous done, `lyricNext` still previews; no false sweep on the upcoming line before its `t`.
4. Frame schema still has `lyricProgress` as float|null; no required new fields.
5. `pytest tests/test_score.py` covers:
   - mid-word fractional progress
   - before first / after last word
   - no words → linear equals old `line_at`
   - gap between words (document chosen behaviour)

## Tests (required)

```python
# Pseudocode shapes — implement against real helpers

def test_progress_linear_fallback_matches_old():
    line = {"t": 0.0, "end": 4.0, "text": "abcd"}
    assert abs(progress_in_line(line, 1.0, words=None) - 0.25) < 1e-6

def test_progress_uses_word_timestamps():
    line = {"t": 0.0, "end": 4.0, "text": "朋友"}
    words = [
        {"t": 0.0, "end": 1.0, "text": "朋"},
        {"t": 3.0, "end": 4.0, "text": "友"},  # long hold on first syllable
    ]
    # At t=0.5 still in first half of first char → progress near 0.25 of two equal weights
    p = progress_in_line(line, 0.5, words=words)
    assert 0.0 < p < 0.5
    # At t=2.0 in gap / after first word → at least halfway
    assert progress_in_line(line, 2.0, words=words) >= 0.5
```

## Out of scope

- In-process Whisper model cache (P1-2) — separate brief
- Hash skip of Demucs (P1-3)
- Prep candidate picker for LRCLIB
- Changing LRCLIB default back to `align` for word timings
- Overlay CSS redesign / dual-line Jyutping

## Suggested commit message

```
drive lyric sweep from word timestamps when available

Keep lyricProgress 0–1 for the overlay; fall back to linear
interpolation when lyrics.json has no usable words (e.g. LRCLIB).
```

## Estimate

Small–medium: ~½–1 day including tests and a listen-pass on one Whisper pack + one LRCLIB pack.
