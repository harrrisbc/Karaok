# Phase 4 — Show overlay (HP + song/singer)

Status: implementing 2026-08-14.  
Parent: [karaoke-show.md](karaoke-show.md)

## Goal

OBS-ready **1920×1080** overlay. Camera/logos stay in OBS. This app is the scoring surface: lyrics, pitch highway, Flat/Late, song+singer card, two HP bars.

Success:

- Top-left branding gone (OBS owns logos).
- Middle left: **song name + singer name**.
- Bottom left: **音準** and **拍子** HP, each **100**, drain only, no recover.
- Either bar hitting **0** stops instrumental playback. Overlay shows FAIL.
- Lyric pill, pitch highway (coin, star, red now-line), timer, Flat/Sharp/Early/Late stay.
- Past notes on the highway: **blue = hit**, **red = miss** (|cents| ≥ 50 or silent through the note).

## Singer

- Prep can set `singer` on import (stored on pack `meta.json`).
- Existing packs: PATCH singer.
- Live can **override for this take** (session only, does not rewrite pack unless Prep/PATCH).

## HP rules

| Bar | Drains when | Does not drain |
|---|---|---|
| 音準 (pitch) | Voiced + on a melody note + \|cents\| ≥ 50 (FLAT/SHARP) | Rests, unvoiced, in-tune |
| 拍子 (rhythm) | EARLY or LATE badge | Rests, unvoiced, on-time |

- Rate: **10 HP / second** of continuous bad singing → empty in **10 s**.
- No regen. Good singing only stops the drain.
- Either bar ≤ 0 → `running = False`, output silence, frame `failed: true`. App still never plays mic.

## Out of scope

Recover HP; both-must-be-0 to fail; Alipay/TVB/mystery boxes; cloning DAM 精密採点.

## Overlay WS frame (additions)

```
hp: { pitch: 0–100, rhythm: 0–100 }
singer: string
failed: bool
fail_reason: "pitch" | "rhythm" | null
```

Legacy `pitch` / `rhythm` / `stable` remain for the score chip (RunningSkill), not the HP bars.
