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
| http://127.0.0.1:8000/show | Show surface (1920×1080) — MV or camera background |
| http://127.0.0.1:8000/show?preview=1 | Overlay scaled to window |
| http://127.0.0.1:8000/show?transparent=1 | Transparent HUD for OBS composite |

Karaok must run on the **audio PC** (mic + instrumental). Remote browsers can open `/live` / `/show` but cannot move PortAudio. Camera / capture card must be granted on the machine that displays `/show`.

### LAN / two-machine show

```powershell
$env:KARAOK_HOST = "0.0.0.0"
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host $env:KARAOK_HOST --port 8000
```

Allow inbound TCP **8000** on a trusted venue LAN only (no auth).

1. Audio PC: run server, operate `/live`
2. Show display: full-screen `http://<audio-pc-ip>:8000/show` (MV or capture card)
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
    mv.mp4          # optional show background (YouTube import or Attach MV)
```

CLI:

```powershell
.\.venv\Scripts\python.exe -m engine ingest "C:\path\song.mp3"
.\.venv\Scripts\python.exe -m engine analyze <pack_id>
.\.venv\Scripts\python.exe -m engine list
```

Only ingest songs you have the right to use.

Whisper runs on the vocal stem. Guitar solo / long instrumental gaps can still drop a line or two at the edges — prefer LRCLIB or **Align lyrics** when you have the official text.

## 5. Live / FOH notes

1. `/live`: pick output (instrumental) and input (mic). Never route PC mic back to speakers.
2. Start a pack → read **FOH VOCAL DELAY** (`output_ms`).
3. Delay FOH vocal by that ms; foldback / direct vocal stays 0 ms.
4. Align trim on `/live` is scoring-only — do not copy it to the desk.
5. Prep **Analyze** and Live **Start** can overlap for **melody** (CPU). While Whisper/Demucs use the GPU, Live Start returns 409 — wait for that step to finish (otherwise Windows can hard-crash the server). If Live is already playing, a new Analyze runs Whisper on **CPU** (slower, safer).
6. **Blue-hit ground truth:** use `/live` **Guide vocal** mix + **Calibrate latency** on the same PC audio chain. Do **not** judge pitch hits by playing `vocals.wav` from a phone into the mic — that adds unknown delay so most notes miss even when the chart is correct.

More: [phase-3-live-scoring](intent/phase-3-live-scoring.md), [phase-4-overlay](intent/phase-4-overlay.md).

## Mac?

For a Mac that only needs control + overlay + scoring (no analyze), see [install-mac-preview.md](install-mac-preview.md).
