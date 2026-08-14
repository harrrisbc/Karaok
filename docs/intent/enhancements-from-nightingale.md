# Enhancements borrowed from Nightingale

Status: backlog. Item 1 (LRCLIB) largely shipped; item 2 brief ready; item 4 brief ready.
Parent: [karaoke-show.md](karaoke-show.md)

Source: [rzru/nightingale](https://github.com/rzru/nightingale) — Tauri (Rust + React) karaoke app, GPL-3.0, ~1.4k stars. Same pipeline shape as Karaok (stem split → ASR → timed lyrics → pitch scoring), but a **living-room app**, not a show overlay. Only the ideas that serve a live show are listed.

Do not copy code: Nightingale is GPL-3.0. Re-implement ideas only.

## P1 — fixes pain we hit this week

### 1. LRCLIB synced lyrics before Whisper

Nightingale asks [LRCLIB](https://lrclib.net) for already-synced lyrics first, and only falls back to ASR. Karaok always runs Whisper, which is why we keep filtering hallucinated 《title》 / Unknown / 作詞 lines.

Detailed spec below — this is the one item with a design worked out.

#### Goal

Stop trusting Whisper for **what the words are**, keep trusting our own audio for **when they land**.

Whisper's weakness on Cantopop is character accuracy and hallucination, not timing. LRCLIB's weakness is timing (line-level only, tied to a release we may not have) and script (often Simplified). Take the half each side is good at:

```
LRCLIB text → OpenCC s2hk → align_lyrics_from_text(pack, text) → lyrics.json
                                     ↑ existing stable-ts path
```

ASR stays as the fallback when LRCLIB has nothing.

#### Cantonese coverage — measured, 2026-08-14

Probed `lrclib.net/api/search` directly. `synced` = results carrying `syncedLyrics`.

| Query | results | synced |
| --- | --- | --- |
| 陳奕迅 – 1874 | 20 | 20 |
| 陳奕迅 – 富士山下 | 20 | 20 |
| 謝安琪 – 囍帖街 | 20 | 20 |
| 謝安琪 – 喜帖街 | 0 | 0 |
| Kay Tse – 囍帖街 | 5 | 4 |
| MIRROR – Warrior | 2 | 2 |
| 張國榮 – Monica | 20 | 5 (rest plain-only) |
| 容祖兒 – 小小 | 2 | 0 |
| Dear Jane – 哪裡只有天氣不好 | 0 | 0 |
| Pandora – Safety Distance | 0 | 0 |

Read: mainstream Cantopop is well covered. Indie, very new, and YouTube-only tracks are not. So this is an accelerator, never a replacement.

Four findings that shape the design:

1. **Titles must match exactly.** `喜帖街` → 0 hits; `囍帖街` → 20 hits. Search must be tried more than one way.
2. **Simplified script is common.** Best `囍帖街` hit reads 「忘掉种过的花重新的出发」. Unusable on a HK show screen as-is.
3. **Credit lines are in the LRC too.** `1874` starts `[00:09.10]1874` then `[00:15.17]作詞：黃偉文 作曲：王雙駿`. Exactly what `filter_lyric_segments` already strips from ASR output — the LRC path needs the same filter.
4. **Line-level only.** No word timings, so no per-word overlay sweep (item 4) from LRCLIB alone.

#### API contract

Public, no key, no auth. Send a real `User-Agent` (`Karaok/<ver> (<repo url>)`) — their docs ask for it.

- `GET /api/get?artist_name=&track_name=&album_name=&duration=` — exact match, `duration` in seconds, tolerance about ±2 s. Returns one record or 404.
- `GET /api/search?artist_name=&track_name=` — fuzzy, returns up to 20 records.
- `GET /api/search?q=<free text>` — last resort when artist/title split is unknown.

Record fields we care about: `trackName`, `artistName`, `albumName`, `duration`, `instrumental`, `plainLyrics`, `syncedLyrics`.

#### Matching strategy

Try in order, stop at first record with non-empty `syncedLyrics` and `instrumental == false`:

1. `/api/get` with title + artist + our pack duration.
2. `/api/search` with title + artist, keep candidates within ±3 s of pack duration.
3. `/api/search` with title only, same duration filter.
4. `/api/search?q=` with the raw ingest title (YouTube titles carry ` (Official Music Video)` noise — strip bracketed suffixes, `MV`, `Official`, `Lyrics`, `HD` before querying).

Never auto-commit a fuzzy match. Ranks 2–4 return a candidate list to Prep and a human picks. Only rank 1 may apply without confirmation.

#### Normalization pipeline

Applied to every fetched LRC before it reaches the aligner:

1. Parse `[mm:ss.xx]` timestamps; support multiple timestamps per line and Enhanced LRC `<mm:ss.xx>` word tags (keep word tags if present — free word timing when we get it).
2. Drop LRC metadata tags (`[ti:]`, `[ar:]`, `[al:]`, `[by:]`, `[offset:]`) but honour `[offset:]` if non-zero.
3. Run existing credit/title filtering on the text (finding 3).
4. Convert to Traditional with OpenCC `s2hk` — HK variants, not `s2t`. New dep: `opencc-python-reimplemented`. Gate behind `lyrics_lang == "cantonese"`.
5. Collapse blank lines, trim whitespace.

Never write converted text back over the fetched cache — keep the raw response so a bad conversion is debuggable.

#### Timing strategy

Two modes, because they fail differently:

- **`align` (default)** — throw away LRCLIB timing, pass text to `align_lyrics_from_text()`. Timing then matches *our* audio, so a live/remaster/edit version still lines up, and we get whatever word timing stable-ts produces. Costs one GPU pass.
- **`trust-lrc`** — use LRCLIB timestamps directly, no GPU pass. Only offer this when `/api/get` matched exactly on duration. Fast preview path; expect drift on any other release.

Both write `lyrics.json` with existing schema. Record provenance so the UI can show where lyrics came from:

- `method`: `"lrclib-align"` or `"lrclib-direct"`
- `source`: `"lrclib"`
- new `lrclib` block: `{ id, track_name, artist_name, album_name, duration, matched_by, converted: "s2hk" | null }`

#### Failure modes to handle explicitly

| Case | Behaviour |
| --- | --- |
| 404 / no synced result | Fall through to Whisper ASR silently, log the attempt |
| Network down or timeout (5 s) | Same as 404, never fail the job |
| `instrumental: true` | Reject the record, keep searching |
| Duration off by > 3 s | Do not auto-apply, offer as candidate only |
| Line count wildly off vs vocal span | Warn in Prep before overwriting a good `lyrics.json` |
| Existing hand-corrected `lyrics.json` | Never silently overwrite — require an explicit Prep action |

#### Wiring

The align path already exists, so this is mostly a fetcher.

- New `engine/lrclib.py` — HTTP client, matching ladder, response cache under the pack (`lrclib.raw.json`).
- New `engine/lrc.py` — LRC/Enhanced LRC parse + serialize, reusable for pasted files.
- `engine/lyrics_align.py` — add an LRC-timed entry point beside `align_lyrics_from_text()`; extend the payload with the `lrclib` block.
- `engine/jobs.py` — try LRCLIB inside the analyze flow before the Whisper step; new `start_lyrics_lrclib` for the manual path.
- `server/app.py` — `GET /api/lyrics/lrclib/search/{pack_id}` (candidates) and `POST /api/lyrics/lrclib/apply/{pack_id}` (`{ id, mode }`).
- `web/prep.*` — candidate list with title/artist/album/duration, mode toggle, and a paste box that accepts LRC text directly (offline / manually sourced lyrics).
- `requirements.txt` — `opencc-python-reimplemented`.

#### Tests

Offline only — no network in tests. Fixture JSON captured from real responses.

- LRC parse: multi-timestamp lines, Enhanced LRC word tags, `[offset:]`, CRLF, malformed timestamps.
- `s2hk` conversion on the real 囍帖街 Simplified sample.
- Credit-line filtering on the real 1874 head (`1874`, `作詞：黃偉文 作曲：王雙駿`).
- Matching ladder: exact hit wins; `instrumental` rejected; out-of-tolerance duration returns candidate, not auto-apply.
- Fallback: fetch raises → analyze still completes via ASR.

#### Acceptance

1. A mainstream Cantopop pack gets correct Traditional characters with zero hallucinated credit lines, without anyone typing lyrics.
2. An indie pack with no LRCLIB entry analyzes exactly as it does today.
3. Timing on a live/remaster version is no worse than the current ASR path.
4. A hand-corrected `lyrics.json` is never clobbered without a click.

### 2. Persistent analyzer process (model stays loaded)

Nightingale keeps one analyzer process alive and talks to it over a loopback socket, so model load and CUDA init are paid once. Karaok calls `whisper.load_model()` on every job (`engine/lyrics.py`) and unloads right after to free VRAM for Demucs.

**Decision:** do **not** copy the daemon. Use an in-process one-slot cache instead (same win, fits 8 GB VRAM + Demucs).

→ Programmer brief: [p1-2-whisper-model-cache.md](p1-2-whisper-model-cache.md)

### 3. Cache analysis by file hash

Nightingale hashes source files (blake3) and re-analyses only when the file changes or the user asks. Karaok re-runs Demucs + Whisper on every Analyze.

- Store source hash in `meta.json`; skip stems when the hash matches and `vocals.wav` exists.
- Saves the 2–5 min GPU pass when we only wanted to re-run lyrics.

### 4. Word-level lyric highlight

We already write a `words` array in `lyrics.json` — nothing reads it. `engine/score.py` `line_at()` interpolates progress linearly across the line, so the sweep drifts inside long lines.

- Feed `words` into the frame and drive the overlay sweep off real word timestamps.
- Files: `engine/score.py`, `web/overlay.js`.
- LRCLIB `trust-lrc` packs often have empty `words` — keep linear fallback for those.

→ Programmer brief: [p1-4-word-level-lyric-highlight.md](p1-4-word-level-lyric-highlight.md)

## P2 — show quality

### 5. Jyutping / romanization above lyrics

Nightingale shows per-character readings (Jyutping for Cantonese, pinyin, Hepburn, Revised Romanization) above each token.

- For a Cantonese show this helps a guest singer who reads romanization faster than characters.
- Overlay would need a second, smaller line above the lyric pill.

### 6. Beep-based mic latency test

Nightingale runs a beep test from Settings so scoring lines up with the room. Karaok has a manual ±80 ms **Align trim** and reports FOH delay, but nothing measures the loop.

- Play a click out, capture it back, cross-correlate, set trim automatically.
- Covers the existing "auto latency calibrate" todo.
- Files: `engine/live.py`, `web/live.*`.
- FOH delay stays `output_ms`; calibrate only proposes `trim_ms` (with confirm).

→ Programmer brief: [p2-6-latency-calibrate.md](p2-6-latency-calibrate.md)

### 7. Key and tempo shift with cached variants

Adjust song key and tempo after analysis, cache the shifted audio for retries. Useful when a guest cannot reach the original key.

- Melody note targets must shift with the key, or scoring breaks.

### 8. Score reveal, profiles, per-song scoreboard

Nightingale has star ratings, player profiles, and per-song score history. Karaok shows a running score chip but has no end-of-take reveal — still the top gap for show feel.

- Reveal panel at end of take + store results per singer per pack.

### 9. Skip intro / skip outro

On-screen skip buttons for long instrumental intros. Pairs well with the vocal-onset detection we already compute (`vocal_onset` in `lyrics.json`).

### 10. Keyboard shortcuts during a take

Nightingale maps guide-vocal toggle (`G`), guide volume (`+`/`-`), mic toggle, fullscreen. Karaok's new guide-vocal fader is mouse-only on `/live`.

## P3 — platform and packaging

### 11. LAN / self-hosted mode

Nightingale runs on a LAN box and is opened from other devices. Karaok binds `127.0.0.1` by default so a video PC cannot pull `/show`.

- Bind `0.0.0.0` behind an explicit flag (`KARAOK_HOST` / uvicorn `--host`), keep localhost the default.
- Operator desk is `/live`; sticky OBS capture is `/show`. Server stays on the audio PC.
- Documented in README (two-machine show). Trusted venue LAN; no auth.

### 12. UltraStar Deluxe (USDX) song import

USDX bundles carry pitch and lyric data, so no analyzer pass is needed. A large existing chart ecosystem we could read instead of generating everything from audio.

- Would give us hand-authored, reliable note charts for free.

### 13. UVR Karaoke separation model as an alternative to Demucs

Nightingale defaults to the UVR Karaoke model (ONNX Runtime, CUDA or CoreML) and notes it keeps backing vocals in the instrumental for a more natural karaoke sound. Demucs `--two-stems` strips all voices.

- Directly affects how the guide-vocal fader sounds.

### 14. Release discipline

Tag-driven release workflow, `CHANGELOG.md` section per version, draft release then publish. Karaok has one commit and no releases.

- Worth a light version of this once the show runs end to end.

## Deliberately skipped

- Media-server libraries (Plex / Jellyfin / Navidrome) — we import one song at a time.
- Audio-reactive shader backgrounds and video loops — OBS owns visuals.
- Gamepad navigation, in-app updater, Docker images, mobile/TV scaling — app concerns, not show concerns.
- Bundling Python / ffmpeg / models into one binary — our setup is a dev machine we control.
