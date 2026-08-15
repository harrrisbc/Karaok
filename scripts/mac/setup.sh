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
  # Prefer 3.11–3.13. Skip bare `python3` if it is 3.14+ (preview stack not validated there).
  for bin in python3.11 python3.12 python3.13; do
    if command -v "$bin" >/dev/null 2>&1; then
      echo "$bin"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    if python3 - <<'PY'
import sys
raise SystemExit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)
PY
    then
      echo python3
      return 0
    fi
  fi
  return 1
}

PYTHON="$(pick_python)" || {
  echo "Need Python 3.11–3.13 (not 3.14). Example: brew install python@3.12" >&2
  exit 1
}

"$PYTHON" - <<'PY'
import sys
if not ((3, 11) <= sys.version_info < (3, 14)):
    raise SystemExit(f"Python 3.11–3.13 required, found {sys.version}")
print(f"Using {sys.executable} ({sys.version.split()[0]})")
PY

"$PYTHON" -m venv .venv-preview
.venv-preview/bin/python -m pip install -U pip
.venv-preview/bin/python -m pip install -r requirements-preview.txt
echo "Mac preview venv ready: $ROOT/.venv-preview"
echo "Next: bash scripts/mac/run.sh /path/to/songs-library"
