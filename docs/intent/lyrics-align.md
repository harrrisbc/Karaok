# Lyric TXT align

Status: implemented 2026-08-14.  
Parent: [karaoke-show.md](karaoke-show.md)

## Goal

Import a **correct lyric .txt** (one phrase per line) and write timed `lyrics.json` against `vocals.wav`.

## Flow

1. Pack must already have `vocals.wav` (Import / split).
2. Prep → **Align lyrics** → pick `.txt`, or CLI:
   `python -m engine lyrics-align <pack_id> lyrics.txt`
3. Uses **stable-ts** forced align (`language=zh` for cantonese/chinese).
4. Fallback: `--remap` / `prefer_remap` keeps old timing, only swaps text.

## Txt format

```
# comments ok
第一句
第二句
第三句
```

## Out of scope

Live paste while rolling; editing per-word karaoke karaoke karaoke highlight beyond line level.
