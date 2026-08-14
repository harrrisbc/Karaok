# Install — Windows (full)

Full Karaok: **Prep** (import + Demucs + lyrics/melody) and **Show** (live scoring + overlay).

Python **3.11** required (Demucs / torch). Prefer an NVIDIA GPU with CUDA for stem split and Whisper.

## 1. Prerequisites

- Python 3.11 (`py -3.11 --version`)
- Git (optional)
- ffmpeg: `winget install --id Gyan.FFmpeg -e`
- Enough disk for models + song packs

## 2. Create venv and install

```powershell
cd C:\dev\Karaok
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PIP_CONFIG_FILE = "$PWD\pip.pypi.ini"
pip install -r requirements.txt
pip install -r requirements-ml.txt
pip install --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128
```

`requirements-ml.txt` is large (Demucs, librosa, Whisper). The CUDA 12.8 torch wheel is for RTX GPUs on Windows.

## 3. Run

```powershell
.\scripts\run.ps1
```

Or:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

### Pages

| URL | Role |
|-----|------|
| http://127.0.0.1:8000/prep | Prep studio — import / analyze |
| http://127.0.0.1:8000/live | Operator desk — Start/Stop, devices, trim |
| http://127.0.0.1:8000/show | OBS overlay (1920×1080 Browser Source) |
| http://127.0.0.1:8000/show?preview=1 | Overlay scaled to window |

Karaok must run on the **audio PC** (mic + instrumental). Remote browsers can open `/live` / `/show` but cannot move PortAudio.

### LAN / two-machine show

```powershell
$env:KARAOK_HOST = "0.0.0.0"
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host $env:KARAOK_HOST --port 8000
```

Allow inbound TCP **8000** on a trusted venue LAN only (no auth).

1. Audio PC: run server, operate `/live`
2. Video PC OBS: Browser Source `http://<audio-pc-ip>:8000/show`
3. Stage tablet/laptop: `http://<audio-pc-ip>:8000/live`

## 4. Song packs

Prep writes under `songs/<pack_id>/`:

```text
songs/
  <pack_id>/
    meta.json
    instrumental.wav
    vocals.wav      # optional
    melody.json     # optional
    lyrics.json     # optional
```

CLI:

```powershell
.\.venv\Scripts\python.exe -m engine ingest "C:\path\song.mp3"
.\.venv\Scripts\python.exe -m engine analyze <pack_id>
.\.venv\Scripts\python.exe -m engine list
```

Only ingest songs you have the right to use.

## 5. Live / FOH notes

1. `/live`: pick output (instrumental) and input (mic). Never route PC mic back to speakers.
2. Start a pack → read **FOH VOCAL DELAY** (`output_ms`).
3. Delay FOH vocal by that ms; foldback / direct vocal stays 0 ms.
4. Align trim on `/live` is scoring-only — do not copy it to the desk.

More: [phase-3-live-scoring](intent/phase-3-live-scoring.md), [phase-4-overlay](intent/phase-4-overlay.md).

## Mac?

For a Mac that only needs control + overlay + scoring (no analyze), see [install-mac-preview.md](install-mac-preview.md).
