# Karaok

Live karaoke scoring show. `/show` is a 1920×1080 surface with optional **MV** or **camera / capture-card** background; `/live` is the operator desk. OBS is optional.

| Mode | What you get |
|------|----------------|
| **Windows full** | Prep (import → stems → melody/lyrics + MV) + Live + Show |
| **Mac preview** | Live control + Show + mic scoring only (load ready packs) |

Only ingest / perform songs you have the right to use.

## Demo song packs (optional)

Four ready packs (instrumental + lyrics + melody + MV) ship as a **GitHub Release** asset, not in git (too large / rights-sensitive).

1. Open the latest [Release](https://github.com/harrrisbc/Karaok/releases) and download `karaok-demo-packs.zip`.
2. Extract so you get `songs/<pack_id>/meta.json` (into the repo `songs/` folder, or any folder).
3. Windows: restart Prep/Live — packs appear in `/live`.  
   Mac preview: `bash scripts/mac/run.sh /path/to/extracted-songs-parent` (folder that contains `songs/` **or** the pack folders — match your layout).

Rebuild locally after Prep:

```powershell
.\.venv\Scripts\python.exe scripts\pack_demo.py
# optional smaller zip without MV:
.\.venv\Scripts\python.exe scripts\pack_demo.py --no-mv
```

## Choose install

| You have… | Follow |
|-----------|--------|
| Windows show PC / prep machine | [docs/install-windows.md](docs/install-windows.md) |
| Mac demo (boss / preview, no analyze) | [docs/install-mac-preview.md](docs/install-mac-preview.md) |

### Quick start — Windows

```powershell
cd C:\dev\Karaok
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:PIP_CONFIG_FILE = "$PWD\pip.pypi.ini"
pip install -r requirements.txt
pip install -r requirements-ml.txt
pip install --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128
winget install --id Gyan.FFmpeg -e
.\scripts\run.ps1
```

Then open http://127.0.0.1:8000/prep and http://127.0.0.1:8000/live.  
Show: http://127.0.0.1:8000/show (1920×1080). Use `/live` **Show background** to pick MV or camera. `?transparent=1` if you still composite in OBS.

Full steps: [docs/install-windows.md](docs/install-windows.md).

### Quick start — Mac preview

Needs Python **3.11–3.13** (not 3.14), Homebrew, and PortAudio.

1. Copy this repo to the Mac.
2. Copy a Windows `songs/` library (folders with `meta.json` + `instrumental.wav`).
3. Install once, then run:

```bash
cd /path/to/Karaok
bash scripts/mac/setup.sh
bash scripts/mac/run.sh /path/to/copied-songs
```

Browser opens `/live` (control) and `/show?preview=1` (overlay). Stop with Ctrl+C.  
Allow Terminal microphone access when macOS asks.

Full steps: [docs/install-mac-preview.md](docs/install-mac-preview.md).

## Repo layout

```text
engine/          audio, packs, scoring, prep pipelines
server/          FastAPI — app.py (full), preview_app.py (Mac/live-only)
web/             prep / live / overlay UI
songs/           local song packs (gitignored audio)
scripts/
  run.ps1        Windows full server
  mac/setup.sh   Mac preview one-time install
  mac/run.sh     Mac preview start
docs/
  install-windows.md
  install-mac-preview.md
  intent/        design notes
requirements.txt           full app (light)
requirements-ml.txt        Demucs / Whisper / librosa
requirements-preview.txt   Mac/live-only deps
```

## Requirements files

| File | Use |
|------|-----|
| `requirements.txt` | FastAPI, sounddevice, yt-dlp, … |
| `requirements-ml.txt` | Prep models (pulls in `requirements.txt`) |
| `requirements-preview.txt` | Live preview only — no torch / Demucs |

## Status

Done: song packs, ingest, Demucs, melody + lyrics, live scoring, overlay HP / song card, Mac preview entry.

Not yet: full show start/stop packaging, score reveal.
