#!/usr/bin/env bash
# Build dist/Karaok Preview.app on macOS (Apple Silicon or Intel).
# Requires: Homebrew, Python 3.11–3.13, PortAudio.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build-app.sh must run on macOS." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Install Homebrew first: https://brew.sh" >&2
  exit 1
fi

if ! brew list portaudio >/dev/null 2>&1; then
  brew install portaudio
fi

pick_python() {
  local bin
  for bin in python3.12 python3.11 python3.13; do
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
  echo "Need Python 3.11–3.13. Example: brew install python@3.12" >&2
  exit 1
}

BUILD_VENV="$ROOT/.venv-appbuild"
if [[ ! -x "$BUILD_VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$BUILD_VENV"
fi
# Pin setuptools: py2app breaks on newer setuptools (File exists / collect errors).
"$BUILD_VENV/bin/python" -m pip install -U pip wheel
"$BUILD_VENV/bin/python" -m pip install 'setuptools==70.3.0'
"$BUILD_VENV/bin/python" -m pip install -r requirements-preview.txt
"$BUILD_VENV/bin/python" -m pip install py2app sniffio

# Fresh build dirs
rm -rf "$ROOT/build/py2app" "$ROOT/dist/Karaok Preview.app" "$ROOT/dist/Karaok Preview"
mkdir -p "$ROOT/build/py2app"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$BUILD_VENV/bin/python" scripts/mac/setup_app.py py2app \
  --dist-dir "$ROOT/dist" \
  --bdist-base "$ROOT/build/py2app"

APP="$ROOT/dist/Karaok Preview.app"
if [[ ! -d "$APP" ]]; then
  # py2app may emit alias without space depending on setup name
  if [[ -d "$ROOT/dist/KaraokPreview.app" ]]; then
    APP="$ROOT/dist/KaraokPreview.app"
  else
    echo "py2app did not produce an .app under dist/" >&2
    ls -la "$ROOT/dist" >&2 || true
    exit 1
  fi
fi

# Vendor PortAudio dylibs so double-click works without Terminal DYLD hacks.
LIB_DIR="$APP/Contents/Resources/lib"
mkdir -p "$LIB_DIR"
PA_PREFIX="$(brew --prefix portaudio)"
copied=0
for f in "$PA_PREFIX"/lib/libportaudio*.dylib; do
  [[ -f "$f" ]] || continue
  cp -f "$f" "$LIB_DIR/"
  copied=$((copied + 1))
done
if [[ "$copied" -eq 0 ]]; then
  echo "Warning: no PortAudio dylibs found under $PA_PREFIX/lib — mic may fail until brew link." >&2
else
  echo "Vendored $copied PortAudio dylib(s) into Resources/lib"
fi

# Ad-hoc sign so Gatekeeper is slightly happier on the build Mac.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" 2>/dev/null || true
fi

echo
echo "Built: $APP"
echo "First launch tip: Right-click → Open if macOS blocks an unsigned app."
echo "Songs: copy a Windows songs library, then double-click the app and pick that folder."
echo "Dev path still works: bash scripts/mac/run.sh ~/karaok-songs"
