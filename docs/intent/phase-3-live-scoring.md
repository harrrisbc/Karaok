# Phase 3 — Live scoring (engineering pass)

Status: done 2026-08-14. Overlay layout is Phase 4.  
Parent: [karaoke-show.md](karaoke-show.md)

## Goal

Wire **mic pitch → Flat / Sharp / Early / Late** against an existing song pack (`melody.json` + `lyrics.json` + `instrumental.wav`). Overlay receives live frames. This is an **engineering pass**, not a show-ready open/close flow.

Success for this phase:

- Pick **input** and **output** devices (audio interface).
- App **only plays instrumental**. Never mix mic back to speakers.
- Singer hears themselves via **console / interface direct monitor** (0 ms vocal).
- App UI shows **exact delay numbers** for the audio team.
- Audio team **delays FOH vocal** by our **output latency (ms)** so PA vocal locks to the track.
- Scoring clock in software uses the same I/O latencies so Flat vs Late is distinguishable.

## Roles

| Who | Does |
|---|---|
| Performer | Sings into interface mic. Hears own voice from desk direct / foldback (undelayed). Hears track from our PC → interface → speakers / wedges. |
| This app | Plays instrumental only. Records mic for scoring. Shows overlay + latency readout. |
| Audio team | Console: split mic (direct to PA/foldback + send into PC). Delay **FOH vocal bus** by the number we display. Do **not** delay foldback / direct monitor. |
| Video | OBS captures `/show` as before. Unchanged. |

## Signal flow

```
                    ┌─ interface DIRECT MONITOR ──► foldback / singer (vocal, 0 ms)
Mic ──► interface ──┤
                    └─ USB/ASIO input ────────────► Karaok (scoring only, no monitor)

Karaok instrumental ──► interface output ──► console ──► FOH / wedges (track)
                                                         ▲
FOH vocal ── delay = OUTPUT_MS ──────────────────────────┘  (audio team)
```

Rules:

1. **One mic split:** hardware monitor + computer input. We never play the mic.
2. **One music send:** stereo (or dual mono) instrumental from this PC only.
3. **Two different delays:**
   - **Room / FOH:** audio team delays **vocal**, not the track.
   - **Scoring:** we shift the comparison clock in software. Desk delay does **not** fix scoring by itself.

## Delay model (give this to audio)

Let:

- `OUTPUT_MS` = how late the singer **hears** the instrumental vs our playback clock (DAC + buffer + interface).
- `INPUT_MS` = how late we **receive** the mic vs acoustic now (ADC + buffer).
- `ROUNDTRIP_MS` = `INPUT_MS + OUTPUT_MS` (if we ever loop back; not required for FOH).

**Number to punch on the console**

| Bus | Delay |
|---|---|
| Foldback / direct vocal | **0 ms** |
| FOH vocal (and any PA vocal that must lock to the track) | **`OUTPUT_MS`** (copy from app UI) |
| Instrumental / Karaok output | **0 ms extra** on the desk |

Typical `OUTPUT_MS` on a USB interface (WASAPI shared): ~15–40 ms. ASIO / exclusive / small buffer: ~5–15 ms. **Do not hard-code a guess for the show** — use the live readout after devices and buffer size are set.

If the desk only has one vocal delay for everything, **do not** delay foldback; split before the delay, or singer will fight their own voice.

### Scoring alignment (us, not the desk)

Singer sings along to **what they hear** = playback position minus `OUTPUT_MS`.  
Mic samples we have = acoustic event plus `INPUT_MS` ago.

Compare:

```
expected = melody.at(playback_pos - OUTPUT_MS)
sung     = pitch.from(mic_buffer)          # already late by INPUT_MS
align    = sung vs expected, with extra shift INPUT_MS
         ≈ compare sung to melody.at(playback_pos - OUTPUT_MS + INPUT_MS)
```

Expose a **manual trim** `ALIGN_TRIM_MS` (default 0, range e.g. −80…+80) in case the reported device latency is wrong. Audio team still uses **displayed `OUTPUT_MS` only**, not the trim.

## Device control (required)

Prep or a small **Live** panel (not OBS overlay chrome):

- Output device list → play `instrumental.wav` here only.
- Input device list → mic / interface input for pitch.
- Input channel index if the device is multi-channel (default 0 / left).
- Host API label (WASAPI / DirectSound / MME). Prefer WASAPI. ASIO later if PortAudio sees it — not a Phase 3 must.
- Buffer / block size if the library exposes it; otherwise show whatever latency PortAudio reports.
- Live numbers: `output_ms`, `input_ms`, `align_ms` (= output − input + trim), **FOH vocal delay = output_ms**.
- Big copyable **FOH VOCAL DELAY: NN ms**.

Defaults: system default in/out so it runs before the interface is plugged in; persist last selection.

## Live scoring (engineering)

Inputs: a `ready` pack (`melody.json` notes with `t`, `duration`, `hz` / `midi`).

Each ~10–20 ms:

- F0 from mic (YIN / similar; voiced flag).
- `cents` vs expected Hz at aligned time. `|cents| > ~50` → **Flat** or **Sharp**.
- Onset / lag vs note start → **Early** / **Late** (~80–100 ms).
- Running meters: pitch / rhythm / stability (same 50/30/20 idea as before; not DAM).

WebSocket (or SSE) to overlay, e.g.:

```json
{
  "t": 12.04,
  "playback_t": 12.04,
  "align_t": 11.97,
  "f0": 220.4,
  "expected_hz": 220.0,
  "cents": -3.1,
  "badges": [],
  "pitch": 82,
  "rhythm": 70,
  "stable": 75,
  "lyric": { "text": "…", "progress": 0.4 },
  "latency": { "input_ms": 12, "output_ms": 28, "foh_vocal_delay_ms": 28 }
}
```

Overlay: reuse current HUD; drive badges / sung pitch / meters / timer from these frames. Lyric follow from `lyrics.json` by `align_t` is enough (rough). No Phase 4 visual polish.

## What we need from the audio team (checklist)

Before a take:

1. Split mic: direct/foldback **and** USB input into this PC.
2. PC output (Karaok instrumental) into a stereo line / USB return on the desk.
3. **Do not** route PC mic return to speakers.
4. After Karaok shows devices locked, read **FOH VOCAL DELAY** and set that on the FOH vocal bus only.
5. If the number jumps after changing buffer size or sample rate, update the desk delay.

Sample rate: lock interface and app to the same rate (48 kHz preferred). Mismatched SRC adds delay we cannot see.

## Out of scope (Phase 3)

- Software monitoring / headphone mix of the singer
- Click / loopback auto-calibrate (nice later)
- Must-have ASIO exclusive
- Perfect Cantonese lyrics
- Overlay layout matching the reference graphic
- Song picker + start/stop show ops (Phase 5)
- 1:1 DAM scores
- Camera / OBS switching

## Implementation sketch (for rapid-prototyper)

- `sounddevice` (PortAudio) for device list, input stream, output stream.
- Output callback clocks `playback_pos` from samples written.
- Input callback → YIN on hop windows.
- FastAPI WebSocket `/ws/live` + existing `/show`.
- Live controls on Prep or `/live` page: devices, Start/Stop pack playback, latency readout, trim.
- Tests: melody note lookup at t; cents math; delay formula unit tests without hardware.

## Open later

- One-button calibrate if `OUTPUT_MS` from the driver is a lie.
- Per-pack start button and score reveal (Phase 5).
- `ui-designer` / `technical-artist` on overlay (Phase 4).
