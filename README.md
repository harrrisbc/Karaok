# Karaok

Show overlay for live karaoke scoring. Camera stays in OBS / other software.

**Prep** (lens off): drop MP3 or paste YouTube URL → stem split → melody + lyrics into a song pack.  
**Show** (lens on): capture `http://127.0.0.1:8000/show` at 1920×1080.

Only ingest songs you have the right to use.

## Setup (Windows)

Python **3.11** (not 3.14 — Demucs/torch need 3.11). GPU: RTX is used automatically when CUDA torch is installed.

```powershell
cd C:\dev\Karaok
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PIP_CONFIG_FILE = "$PWD\pip.pypi.ini"
pip install -r requirements.txt
pip install -r requirements-ml.txt
pip install --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128
winget install --id Gyan.FFmpeg -e
```

`requirements-ml.txt` is large (Demucs + librosa + whisper). Use the CUDA 12.8 torch wheel so Demucs / Whisper run on the RTX GPU.

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

- Prep studio: http://127.0.0.1:8000/prep
- Live scoring: http://127.0.0.1:8000/live
- Overlay: http://127.0.0.1:8000/show
- Overlay layout check: http://127.0.0.1:8000/show?preview=1
- Transparent-ish stage: http://127.0.0.1:8000/show?transparent=1

OBS: Browser Source, width 1920, height 1080, URL `/show` (**not** `?preview=1`).

### Live / audio team

1. Open `/live`. Pick interface **output** (instrumental only) and **input** (mic). Never route PC mic back to speakers.
2. Start a pack. Read **FOH VOCAL DELAY** — that number is `output_ms`.
3. Console: delay **FOH vocal** by that ms. Foldback / direct vocal stays **0 ms**.
4. Overlay at `/show` follows the live WebSocket.

Align trim on `/live` is scoring-only; do not copy it to the desk.

See [docs/intent/phase-3-live-scoring.md](docs/intent/phase-3-live-scoring.md) and [docs/intent/phase-4-overlay.md](docs/intent/phase-4-overlay.md).

CLI:

```powershell
.\.venv\Scripts\python.exe -m engine ingest "C:\path\song.mp3"
.\.venv\Scripts\python.exe -m engine analyze <pack_id>
.\.venv\Scripts\python.exe -m engine list
```

## Now vs next

Done: song packs, ingest, Demucs, melody + lyrics, live scoring (device picker, FOH delay, Flat/Late), overlay HP + song/singer card.

Not yet: full show start/stop packaging, auto latency calibrate, score reveal.
