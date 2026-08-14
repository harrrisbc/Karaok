#!/usr/bin/env bash
# One-time Mac preview setup: PortAudio + Python venv (no Demucs/Whisper).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! command -v brew >/dev/null 2>&1; then
  echo "Install Homebrew first: https://brew.sh" >&2
  exit 1
fi

if ! brew list portaudio >/dev/null 2>&1; then
  brew install portaudio
fi

pick_python() {
  local bin
  for bin in python3.11 python3.12 python3.13 python3; do
    if command -v "$bin" >/dev/null 2>&1; then
      echo "$bin"
      return 0
    fi
  done
  return 1
}

PYTHON="$(pick_python)" || {
  echo "Need Python 3.11 or newer (brew install python@3.11)." >&2
  exit 1
}

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ required, found {sys.version}")
PY

"$PYTHON" -m venv .venv-preview
.venv-preview/bin/python -m pip install -U pip
.venv-preview/bin/python -m pip install -r requirements-preview.txt
echo "Mac preview venv ready: $ROOT/.venv-preview"
echo "Next: bash scripts/mac/run.sh /path/to/songs-library"
