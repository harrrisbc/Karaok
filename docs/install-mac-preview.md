# Install — Mac preview (control + overlay)

Live demo only: play packs, mic scoring, operator desk `/live`, overlay `/show`.
**No** Prep, YouTube import, Demucs, or Whisper on Mac.

Analyze songs on a Windows machine first, then copy the song library folder here.

## What you need

| Item | Notes |
|------|--------|
| macOS | Apple Silicon or Intel |
| Homebrew | https://brew.sh |
| Python 3.11+ | `brew install python@3.11` if missing |
| Mic + speakers/headphones | Allow Terminal microphone access when macOS asks |
| Song library folder | Copied from Windows — see pack layout below |

## 1. Get the code

Clone or copy this repo onto the Mac.

```bash
cd /path/to/Karaok
```

## 2. One-time setup

```bash
bash scripts/mac/setup.sh
```

This installs PortAudio (via Homebrew) and creates `.venv-preview` with lightweight deps only (`requirements-preview.txt`).

## 3. Copy song packs

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

Do **not** point the runner at a folder of raw MP3s.

## 4. Run

```bash
bash scripts/mac/run.sh ~/karaok-songs
```

The script:

1. Sets `KARAOK_SONGS_DIR` to your library
2. Starts `server.preview_app` on `http://127.0.0.1:8000`
3. Opens **Control** (`/live`) and **Overlay** (`/show?preview=1`) in the browser

Stop with **Ctrl+C** in the Terminal.

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

## 5. First-run checklist

1. System Settings → Privacy & Security → **Microphone** → allow Terminal (or Python).
2. On `/live`, pick **Output** (speakers) and **Input** (mic).
3. Pick a pack that has instrumental → **Start**.
4. Confirm overlay moves (lyrics / pitch / HP).
5. If Start errors on sample rate, pick another CoreAudio device and retry.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No song packs` | Library must contain subfolders with `meta.json` |
| `Run setup first` | `bash scripts/mac/setup.sh` |
| No mic devices | Grant mic permission; unplug/replug interface; restart Terminal |
| Prep link / analyze missing | Expected — preview build has no Prep |
| Want full analyze on Mac | Not supported; use Windows full install |

## Relation to Windows

| | Windows full | Mac preview |
|--|--------------|-------------|
| Entry | `server.app` | `server.preview_app` |
| Venv | `.venv` | `.venv-preview` |
| Analyze / Prep | Yes | No |
| Live scoring | Yes | Yes |
| Song source | Local Prep or copy | Copy ready packs only |
