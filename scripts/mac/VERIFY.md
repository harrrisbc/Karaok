# Mac .app verify checklist

Run on a Mac after `bash scripts/mac/build-app.sh`.

1. **Build** — `dist/Karaok Preview.app` (or `KaraokPreview.app`) exists; PortAudio dylibs under `Contents/Resources/lib`.
2. **Launch** — double-click app → folder picker (first run) → `/live` and `/show?preview=1` open.
3. **Packs** — `/live` song list shows copied packs with instrumental.
4. **Audio** — pick Output + Input → Start plays; mic scores; overlay updates.
5. **Preview gate** — `GET /api/health` returns `"preview": true`; no Prep UI.
6. **Quit** — quitting the app frees the port (`lsof -i :8000` empty).

Dev smoke (no `.app`):

```bash
bash scripts/mac/setup.sh
.venv-preview/bin/python -m scripts.mac.app_main ~/karaok-songs
```
