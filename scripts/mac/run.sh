#!/usr/bin/env bash
# Start Mac preview (control + overlay + live scoring). Pass a song-pack library folder.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

SONGS="${1:-}"
if [[ -z "$SONGS" ]]; then
  echo "Usage: bash scripts/mac/run.sh /path/to/songs-library" >&2
  echo "Each subfolder needs meta.json + instrumental.wav (copy from Windows Prep)." >&2
  exit 1
fi
if [[ ! -d "$SONGS" ]]; then
  echo "Not a folder: $SONGS" >&2
  exit 1
fi

packs=0
shopt -s nullglob
for dir in "$SONGS"/*/; do
  [[ -f "${dir}meta.json" ]] || continue
  packs=$((packs + 1))
done
shopt -u nullglob
if [[ "$packs" -eq 0 ]]; then
  echo "No song packs in $SONGS (need subfolders with meta.json)." >&2
  exit 1
fi

if [[ ! -x .venv-preview/bin/python ]]; then
  echo "Run bash scripts/mac/setup.sh first." >&2
  exit 1
fi

export KARAOK_SONGS_DIR="$(cd "$SONGS" && pwd)"
HOST="${KARAOK_HOST:-127.0.0.1}"
PORT="${KARAOK_PORT:-8000}"

echo "Library: $KARAOK_SONGS_DIR ($packs packs)"
echo "Control: http://${HOST}:${PORT}/live"
echo "Overlay: http://${HOST}:${PORT}/show?preview=1"
echo "Allow Terminal / Python microphone access if macOS asks."
echo "Stop with Ctrl+C."
echo "Tip: bash scripts/mac/build-app.sh → double-click dist/Karaok Preview.app"

(
  sleep 1
  open "http://${HOST}:${PORT}/live" >/dev/null 2>&1 || true
  open "http://${HOST}:${PORT}/show?preview=1" >/dev/null 2>&1 || true
) &

exec .venv-preview/bin/python -m uvicorn server.preview_app:app --host "$HOST" --port "$PORT"
