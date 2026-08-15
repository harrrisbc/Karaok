# Install — Mac preview (control + overlay)

Live demo only: play packs, mic scoring, operator desk `/live`, overlay `/show`.
**No** Prep, YouTube import, Demucs, or Whisper on Mac.

Analyze songs on a Windows machine first, then copy the song library folder here.

## What you need

| Item | Notes |
|------|--------|
| macOS | Apple Silicon or Intel |
| Homebrew | https://brew.sh (PortAudio) |
| Python **3.11–3.13** | `brew install python@3.12` — do **not** use 3.14 for preview |
| Mic + speakers/headphones | Allow **Karaok Preview** (or Terminal) microphone access when macOS asks |
| Song library folder | Copied from Windows — see pack layout below |

## A. Double-click `.app` (operator path)

Build once on the Mac, then launch without Terminal.

### Build

```bash
cd /path/to/Karaok
bash scripts/mac/build-app.sh
```

Output: `dist/Karaok Preview.app` (or `dist/KaraokPreview.app`).

The build:

1. Creates `.venv-appbuild` and installs `requirements-preview.txt` + **py2app**
2. Bundles `server/` + `engine/` live subset + `web/`
3. Vendors PortAudio dylibs into `Contents/Resources/lib`
4. Ad-hoc codesigns the app (local Mac only — not notarized)

### Install songs library

On Windows, Prep has already built packs under something like `C:\dev\Karaok\songs\`.

Copy that **whole library folder** (or a subset of pack folders) to the Mac, e.g. `~/karaok-songs/`.

Expected layout:

```text
karaok-songs/
  some-song-id/
    meta.json           # required
    instrumental.wav    # required to Start
    vocals.wav          # optional (guide vocal)
    melody.json         # optional (pitch highway)
    lyrics.json         # optional (lyric follow)
```

Do **not** point the app at a folder of raw MP3s.

### Launch

1. Double-click **Karaok Preview.app**
2. First run: pick the song library folder (remembered under `~/Library/Application Support/Karaok/prefs.json`)
3. Browser opens **Control** (`/live`) and **Overlay** (`/show?preview=1`)
4. Quit the app to stop the local server

If macOS blocks an unsigned app: **Right-click → Open**, or:

```bash
xattr -dr com.apple.quarantine "dist/Karaok Preview.app"
```

### Mic / camera privacy

System Settings → Privacy & Security:

- **Microphone** → allow **Karaok Preview**
- **Camera** → allow if you use Show camera background

---

## B. Terminal path (developer)

### 1. Get the code

```bash
cd /path/to/Karaok
```

### 2. One-time setup

```bash
bash scripts/mac/setup.sh
```

This installs PortAudio (via Homebrew) and creates `.venv-preview` with lightweight deps only (`requirements-preview.txt`).

### 3. Run

```bash
bash scripts/mac/run.sh ~/karaok-songs
```

Or the same launcher the `.app` uses:

```bash
.venv-preview/bin/python -m scripts.mac.app_main ~/karaok-songs
```

The script:

1. Sets `KARAOK_SONGS_DIR` to your library
2. Starts `server.preview_app` on `http://127.0.0.1:8000` (or next free port)
3. Opens **Control** (`/live`) and **Overlay** (`/show?preview=1`) in the browser

Stop with **Ctrl+C** in the Terminal (or quit the `.app`).

### URLs

- Control: http://127.0.0.1:8000/live  
- Overlay (window preview): http://127.0.0.1:8000/show?preview=1  
- Show (1920×1080): http://127.0.0.1:8000/show  

### Optional env

```bash
export KARAOK_HOST=127.0.0.1   # or 0.0.0.0 for LAN
export KARAOK_PORT=8000
bash scripts/mac/run.sh ~/karaok-songs
```

## First-run checklist

1. Privacy → **Microphone** → allow Karaok Preview (or Terminal / Python).
2. On `/live`, pick **Output** (speakers) and **Input** (mic).
3. Pick a pack that has instrumental → **Start**.
4. Confirm overlay moves (lyrics / pitch / HP).
5. If Start errors on sample rate, pick another CoreAudio device and retry.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Gatekeeper blocks `.app` | Right-click → Open; or `xattr -dr com.apple.quarantine "…/Karaok Preview.app"` |
| Crash on start mentioning `File` / `multipart` | Re-run setup / rebuild; needs `python-multipart` |
| Setup rejects Python 3.14 | `brew install python@3.12` then re-run setup / build |
| `No song packs` | Library must contain subfolders with `meta.json` |
| `Run setup first` | `bash scripts/mac/setup.sh` (Terminal path) |
| No mic devices | Grant mic permission to **Karaok Preview**; unplug/replug interface |
| Prep link / analyze missing | Expected — preview build has no Prep |
| Want full analyze on Mac | Not supported; use Windows full install |
| Notarized DMG for others | Not yet — ship unsigned/ad-hoc `.app` for your own Macs first |

## Relation to Windows

| | Windows full | Mac preview |
|--|--------------|-------------|
| Entry | `server.app` | `server.preview_app` / **Karaok Preview.app** |
| Venv | `.venv` | `.venv-preview` (dev) / `.venv-appbuild` (bundle) |
| Analyze / Prep | Yes | No |
| Live scoring | Yes | Yes |
| Song source | Local Prep or copy | Copy ready packs only |
