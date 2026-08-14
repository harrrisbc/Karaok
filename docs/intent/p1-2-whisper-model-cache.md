# P1-2 — In-process Whisper / stable-ts model cache

Status: implemented 2026-08-14  
Parent: [enhancements-from-nightingale.md](enhancements-from-nightingale.md) §2  
Audience: engineer implementing this change

## Decision (do this, not the Nightingale daemon)

**Chosen approach: in-process model cache inside the existing FastAPI / JobRunner process.**

Do **not** spawn a separate analyzer process or loopback socket (Nightingale’s design). Reasons:

- This laptop is ~8 GB VRAM. Demucs and Whisper cannot both stay resident.
- Jobs are already single-flight (`BusyError` in `engine/jobs.py`) — no parallel GPU work.
- A daemon only buys “skip reload”; the same win is available with a module-level cache and far less ops surface (no crash protocol, no Windows process babysitting).

Accuracy is unchanged. This only removes repeated cold-start cost (disk → GPU load of the checkpoint, often 30–90 s for `large-v3`).

## Problem today

Every lyrics / align job:

1. `whisper.load_model(...)` or `stable_whisper.load_model(...)`
2. run
3. `del model` + `release_cuda()`

So a Prep session that re-runs lyrics or Aligns five packs pays the load cost five times.

Relevant code:

- `engine/lyrics.py` — `extract_lyrics()` loads then `del model` in `finally`
- `engine/lyrics_align.py` — `align_lyrics_from_text()` loads stable-ts the same way
- `engine/stems.py` / `engine/jobs.py` `_prep_full` — call `release_cuda()` before Demucs (keep this behaviour)

## Goal

- Same model name + device + kind → reuse the already-loaded object.
- Different model / Demucs / explicit clear → drop cache and free VRAM.
- No behaviour change to transcript quality, job API, or UI.

## Design

### Cache key

`(kind, model_name, device)` where:

| `kind` | Loader |
| --- | --- |
| `"whisper"` | `whisper.load_model(name, device=device)` |
| `"stable"` | `stable_whisper.load_model(name, device=device)` |

Hold **at most one** cached entry (simplest + VRAM-safe). If the next request differs on any key field, drop the old model first, then load.

### API (put in `engine/lyrics.py`)

```python
def get_cached_model(name: str, device: str, kind: str = "whisper"):
    """Return a loaded model; reuse if (kind, name, device) matches."""

def drop_model_cache() -> None:
    """Drop the cached model and call release_cuda()."""
```

Thread-safety: `JobRunner` is single-active-job, but still guard the cache with a `threading.Lock` so a future change cannot double-load.

### Call sites

| Location | Change |
| --- | --- |
| `extract_lyrics` | `model = get_cached_model(..., kind="whisper")`. **Do not** `del model` after success. |
| `align_lyrics_from_text` | `model = get_cached_model(..., kind="stable")`. **Do not** `del model` after success. |
| `split_stems` / `_prep_full` before Demucs | Call `drop_model_cache()` (or keep `release_cuda()` but make it call `drop_model_cache` first). Demucs must never run while Whisper sits in VRAM. |
| Live start (optional but recommended) | If live scoring shares the GPU machine, call `drop_model_cache()` when a live session starts so Prep leftovers do not pin VRAM during a show. |

### `release_cuda()` contract

Update so clearing VRAM always clears the Python reference first:

```text
drop_model_cache()  →  del cached model  →  gc.collect()  →  torch.cuda.empty_cache()
```

Existing callers of `release_cuda()` then stay correct without hunting every call site. Prefer making `release_cuda()` invoke `drop_model_cache()` internally (idempotent).

### What not to build

- No separate process / socket / RPC
- No multi-model LRU (one slot is enough)
- No UI toggle
- No change to Whisper decode options or Align CLI flags
- Do not keep the model across a Demucs job “to save a reload later” — free VRAM for stems

## Acceptance criteria

1. Two sequential `extract_lyrics` (or Align) jobs with the **same** model on the same server process: second job does **not** call `load_model` again (assert via mock / spy in unit test).
2. Switching model name (e.g. `small` → `large-v3`) loads once for the new name; old model is released.
3. `_prep_full` / `split_stems` still frees VRAM before Demucs — no OOM regression on 8 GB when Import → split → lyrics runs end-to-end.
4. Transcript / align output schema unchanged (`lyrics.json` fields same).
5. Existing tests still pass (`tests/test_lyrics_lang.py`, align tests, etc.).

## Tests (required)

Offline / mocked — do not require GPU for CI:

- Cache hit: second `get_cached_model("small", "cpu", "whisper")` returns the same object id; loader called once.
- Cache miss on name change: loader called twice; only the new model retained.
- `drop_model_cache()` / `release_cuda()`: subsequent get loads again.
- Kind isolation: cached `"whisper"` is not reused for `"stable"` (different loader path).

Optional manual check on the show machine:

1. Start uvicorn once.
2. Analyze lyrics on pack A (`large-v3` if available) — note wall time.
3. Analyze / Align pack B with the same model — cold-start gap should disappear (second run much faster to “transcribe started”).
4. Import a new YouTube song (Demucs path) — must still complete without CUDA OOM.

## Out of scope

- Hash-based skip of Demucs/Whisper when the source file is unchanged → that is **P1-3**, separate brief.
- LRCLIB hybrid lyrics → **P1-1** (partially in tree already); orthogonal to this cache.
- Persistent analyzer as a Windows service / second Python interpreter.

## Suggested commit message

```
cache Whisper/stable-ts models in-process between lyrics jobs

Avoid reloading the checkpoint on every Align/Analyze while still
dropping the cache before Demucs so 8GB VRAM stays usable.
```

## Estimate

Small: ~½ day including tests and a smoke run on the GPU machine.
