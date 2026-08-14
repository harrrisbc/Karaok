# Karaoke Show Overlay — confirmed intent

- Outcome: A show overlay. Prep MP3/YouTube offline (stem split + melody + lyrics + optional `mv.mp4`). Live: pick song, sing, 1080p UI shows lyrics, pitch lane, Flat/Late, then end score. Background is **MV** or **camera / capture card** on `/show`.
- User: Haris producing/performing a karaoke show. Capture card feeds `/show`; OBS is optional.
- Why now: Want THEカラオケ★バトル-style live scoring on PC without drawing MIDI by hand.
- Success: In one take, lyrics track, pitch lane tracks, flat vs late are distinguishable. `/show` is a 1920×1080 show surface.
- Constraint: Prep may take minutes. Live must be low-latency.
- Out of scope: Multi-camera switcher; live YouTube paste while rolling; user-authored MIDI; 1:1 DAM scores; full two-player TV packaging.

Done: Phase 0–3 (stems, melody, lyrics, live scoring + FOH delay).
Phase 4 spec: [phase-4-overlay.md](phase-4-overlay.md) — overlay layout, song/singer card, HP fail.
Backlog: [enhancements-from-nightingale.md](enhancements-from-nightingale.md) — ideas borrowed from a similar OSS karaoke app.
