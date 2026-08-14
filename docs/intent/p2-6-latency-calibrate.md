# P2-6 — Beep-based mic latency calibrate

Status: implemented 2026-08-14  
Parent: [enhancements-from-nightingale.md](enhancements-from-nightingale.md) §6  
Audience: engineer implementing this change  
Covers roadmap todo: auto latency calibrate

## Decision

Add a **Calibrate** action on `/live` that plays a short click out the selected output device, records from the selected mic, estimates round-trip lag via cross-correlation, and proposes a value for the existing **Align trim** (`trim_ms`).

Do **not** invent a second latency model. Do **not** change the FOH contract: audio team still delays vocals by displayed `output_ms` / `foh_vocal_delay_ms` only. Calibration only fills `trim_ms` (scoring timeline), with user confirmation.

Do **not** require a song pack to be playing. Calibration is a short standalone take before Start (or while idle).

## Problem today

Scoring time is:

```text
align_t = playback_pos − output_ms/1000 + input_ms/1000 + trim_ms/1000
```

(`engine/score.py` `align_time`)

- `output_ms` / `input_ms` come from PortAudio stream latency (`engine/live.py` on start), with crude fallbacks (20 / 10 ms) if the driver reports 0.
- `trim_ms` is a manual slider ±80 ms on `/live` (`POST /api/live/trim`).

Driver-reported latency ignores room distance, USB buffer quirks, OBS monitoring paths, and interface mode changes. A 30–50 ms error flips EARLY/LATE badges and wrecks rhythm score while pitch can still look “ok.”

Nightingale solves this with a beep test in Settings. Karaok needs the same idea, wired into the trim we already have.

## Goal

1. One click on `/live` → measure acoustic+driver round-trip → show proposed `trim_ms`.
2. User confirms (or adjusts) before it sticks.
3. Persist last successful calibration in the browser (localStorage) as a default for the next Start — optional but cheap.
4. No change to melody/lyrics packs or Demucs.

## How the measurement works

```text
t0: schedule click on output
    record N seconds from mic (mono, same TARGET_SR as live = 48000 if that is current)

click waveform (known)  ⊗  mic buffer
        → cross-correlation peak at lag L samples
        → lag_ms = 1000 * L / sr
```

Then map lag into trim. Important: `align_time` already subtracts `output_ms` and adds `input_ms`. The beep measures the **full** path the singer hears+sings through, which is not identical to `output_ms - input_ms`.

**Recommended mapping (document in code comments after a dry run):**

1. Compute `reported = output_ms - input_ms` from the open streams used during the test (or device defaults if streams are opened only for calibrate).
2. Measured round-trip ≈ what we want the scoring loop to cancel.
3. Proposed trim:

```text
trim_ms ≈ clamp( measured_lag_ms − reported , −80 , +80 )
```

If streams are opened fresh for calibrate and report the same latencies as a live Start, this puts `align_t` in the right place when those same devices are used for the take.

If the first field test shows systematic bias, adjust the formula once and lock it with a unit test on a synthetic delayed click — do not expose three mystery knobs.

**Peak picking:**

- Use normalized cross-correlation (or FFT correlate).
- Search lag in a bounded window, e.g. 0–150 ms (or −20–150 if loopback can appear “early”).
- Require peak correlation above a threshold; otherwise return `status: "weak"` and do not auto-apply.
- If two peaks (direct + room reflection), prefer the **earliest** peak above threshold, not the tallest late echo.

## Design

### Engine

New helper (e.g. `engine/latency_calibrate.py` or methods on `LiveSession`):

```python
def measure_loop_latency_ms(
    *,
    input_device: int | None,
    output_device: int | None,
    input_channel: int = 0,
    sr: int = 48000,
    click_hz: float = 1000.0,
    click_ms: float = 8.0,
    record_ms: float = 400.0,
) -> dict:
    """Play click, record, return {ok, lag_ms, peak, trim_ms, output_ms, input_ms, error}."""
```

Constraints:

- Must not leave streams open if calibrate fails mid-way.
- Must refuse if a live take is `running` (or stop is required first) — avoid fighting the instrumental callback.
- Use the same WASAPI / device selection preferences as `LiveSession.start` where practical.
- Generate click in-process (numpy burst + short fade); no asset file required.

`LiveSession.set_trim` already clamps ±80 — keep that clamp for apply.

### API

```http
POST /api/live/calibrate
{ "input_device": int|null, "output_device": int|null, "input_channel": 0 }
→ {
    "ok": true,
    "lag_ms": 37.2,
    "peak": 0.82,
    "proposed_trim_ms": 12.0,
    "output_ms": 28.0,
    "input_ms": 12.0,
    "message": "…"
  }
```

Failure shapes:

- `ok: false`, `error: "weak_signal"` — mic didn’t hear the click (headphones-only, muted speakers, wrong device).
- `ok: false`, `error: "busy"` — live session running.
- `ok: false`, `error: "device"` — open stream failed.

Applying trim stays on existing `POST /api/live/trim` after the user confirms (or a `apply: true` flag on calibrate if you want one round-trip — prefer explicit confirm in UI).

### UI (`web/live.*`)

- Button: **Calibrate latency** near the trim slider.
- While running: disable Start / Calibrate, show “Playing click…”.
- On success: show `Measured loop ~37 ms → proposed trim +12 ms` + **Apply** / **Dismiss**.
- On weak signal: short hint — “Turn up speakers / point mic at speakers / unmute monitor.”
- After Apply: update trim slider + `trimVal` + existing `/api/live/trim` call.
- Optional: `localStorage` key `karaok-trim-ms` written on Apply; read as default when loading the page.

### What not to change

- `foh_vocal_delay_ms` remains `output_ms` (phase-3 contract).
- Do not widen trim beyond ±80 without a product decision (larger errors usually mean wrong devices).
- Do not calibrate by singing a song lyric — beep only.

## Acceptance

1. With speakers audible to the mic, Calibrate returns `ok: true` and a stable `lag_ms` (±5 ms across 3 runs on the same desk setup).
2. Apply updates `trim_ms`; subsequent Start uses that trim in `score_snapshot` / status.
3. Mic muted or wrong input → `weak_signal` (or equivalent), trim unchanged.
4. Calibrate while a take is running → busy error, take continues.
5. Unit test: synthetic mic buffer = click delayed by N samples → estimated lag within 1 sample (or ±0.5 ms).
6. Manual: after Apply, EARLY/LATE on a known on-grid clap/sing feels closer than trim=0 with wrong reported latency (desk check is enough).

## Tests (required)

Offline / synthetic — no real audio hardware in CI:

- Build click + delay by `d` samples → `measure_from_buffers(click, recorded)` returns lag ≈ `d`.
- Peak below threshold → not ok.
- Earliest-of-two-peaks: direct at 20 ms, louder echo at 60 ms → picks ~20 ms.
- `proposed_trim_ms` clamp to [-80, 80].

## Out of scope

- Continuous adaptive latency during a take
- Calibrating FOH / PA digital delay (human audio op)
- Bluetooth multipoint magic (warn in UI if user picks BT devices — optional hint only)
- Score reveal (P2-8), word-level lyrics (P1-4)

## Suggested commit message

```
add beep-based latency calibrate for Align trim

Measure output→mic lag via cross-correlation and propose trim_ms
so EARLY/LATE scoring matches the room without hand-tuning.
```

## Estimate

Medium: ~1 day including device-open edge cases on Windows WASAPI, UI confirm flow, and synthetic tests. Field-tune the `trim ≈ lag − (output − input)` mapping once on the show machine.
