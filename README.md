# Karaok

Windows karaoke show stack: **Prep** song packs → **Live** operator desk → **Show** 1920×1080 overlay (OBS optional). Mac runs a **Live + Show preview** only.

Only ingest / perform songs you have the right to use.

| | Windows full | Mac preview |
|--|--------------|-------------|
| Prep (import, Demucs, Whisper, LRCLIB) | Yes | No |
| Live scoring + Show | Yes | Yes |
| Song source | Prep locally | Copy packs from Windows |
| Launch | `scripts/run.ps1` | `Karaok Preview.app` or `scripts/mac/run.sh` |

## Install

| Machine | Guide |
|---------|--------|
| Windows show / prep PC | [docs/install-windows.md](docs/install-windows.md) |
| Mac control + overlay | [docs/install-mac-preview.md](docs/install-mac-preview.md) |

### Windows (quick)

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

Open http://127.0.0.1:8000/prep and http://127.0.0.1:8000/live.  
Show: http://127.0.0.1:8000/show — pick MV or camera under Live **Show background**.

**Prep flow:** Import (small Whisper) → **LRCLIB → Align** → optional Align .txt. LRCLIB is manual (not auto-applied on import).

### Mac preview (quick)

Needs Python **3.11–3.13**, Homebrew, PortAudio. Copy a Windows `songs/` library first.

```bash
cd /path/to/Karaok
bash scripts/mac/build-app.sh          # → dist/Karaok Preview.app
# or Terminal:
bash scripts/mac/setup.sh
bash scripts/mac/run.sh /path/to/songs
```

Allow **Karaok Preview** (or Terminal) microphone access when macOS asks.

## Demo packs

Four ready packs ship as a **[GitHub Release](https://github.com/harrrisbc/Karaok/releases)** asset (`karaok-demo-packs.zip`), not in git.

1. Download from the latest release.
2. Extract so you have `…/<pack_id>/meta.json` (+ `instrumental.wav`).
3. Windows: put under repo `songs/` and refresh Live.  
   Mac: point the app / `run.sh` at that library folder.

Rebuild after Prep:

```powershell
.\.venv\Scripts\python.exe scripts\pack_demo.py
```

## Layout

```text
engine/     packs, stems, melody, lyrics, live scoring
server/     app.py (full) · preview_app.py (Mac/live-only)
web/        prep · live · show overlay
scripts/    run.ps1 · mac/ (setup, run, build-app)
docs/       install guides · intent/
songs/      local packs (audio gitignored)
```

| Requirements file | Use |
|-------------------|-----|
| `requirements.txt` | Full app (FastAPI, sounddevice, yt-dlp, …) |
| `requirements-ml.txt` | Prep models (Demucs / Whisper / librosa) |
| `requirements-preview.txt` | Mac Live+Show only |

## Status

**Done:** Prep pipeline, manual LRCLIB, live scoring, Show MV/camera, dual-window operator UX, Mac preview + `.app` build.

**Not yet:** notarized Mac DMG, Prep-on-Mac, public score-reveal polish.
