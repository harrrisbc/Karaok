"""Mac Preview .app / CLI launcher.

Sets KARAOK_SONGS_DIR, starts uvicorn on server.preview_app, opens Live + Show,
and shuts down cleanly on quit / SIGINT / SIGTERM.

Usage (dev):
  .venv-preview/bin/python -m scripts.mac.app_main /path/to/songs
  .venv-preview/bin/python -m scripts.mac.app_main   # folder picker / prefs
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "Karaok Preview"
BUNDLE_ID = "com.harrrisbc.karaok.preview"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PREFS_NAME = "prefs.json"


def support_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Karaok"
    else:
        base = Path.home() / ".karaok"
    base.mkdir(parents=True, exist_ok=True)
    return base


def prefs_path() -> Path:
    return support_dir() / PREFS_NAME


def load_prefs() -> dict:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_prefs(data: dict) -> None:
    path = prefs_path()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def count_packs(library: Path) -> int:
    if not library.is_dir():
        return 0
    n = 0
    for child in library.iterdir():
        if child.is_dir() and (child / "meta.json").is_file():
            n += 1
    return n


def is_valid_library(library: Path) -> bool:
    return count_packs(library) > 0


def pick_folder_macos(prompt: str = "Choose Karaok song library") -> Path | None:
    """Native macOS folder picker via osascript. Returns None if cancelled."""
    script = f'''
set theFolder to choose folder with prompt "{prompt}"
POSIX path of theFolder
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def pick_folder_tk(prompt: str = "Choose Karaok song library") -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    chosen = filedialog.askdirectory(title=prompt)
    root.destroy()
    if not chosen:
        return None
    return Path(chosen).expanduser().resolve()


def pick_songs_library(initial: Path | None = None) -> Path | None:
    if initial is not None:
        if is_valid_library(initial):
            chosen = initial.resolve()
            prefs = load_prefs()
            prefs["songs_dir"] = str(chosen)
            save_prefs(prefs)
            return chosen
        print(
            f"{APP_NAME}: not a valid library: {initial} (need subfolders with meta.json).",
            file=sys.stderr,
        )

    prefs = load_prefs()
    saved = prefs.get("songs_dir")
    if isinstance(saved, str) and saved.strip():
        candidate = Path(saved).expanduser()
        if is_valid_library(candidate):
            return candidate.resolve()

    while True:
        if sys.platform == "darwin":
            chosen = pick_folder_macos() or pick_folder_tk()
        else:
            chosen = pick_folder_tk()
        if chosen is None:
            return None
        if is_valid_library(chosen):
            prefs["songs_dir"] = str(chosen)
            save_prefs(prefs)
            return chosen
        print(
            f"{APP_NAME}: no packs in {chosen} (need subfolders with meta.json). Pick again.",
            file=sys.stderr,
        )


def find_free_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port near {preferred}")


def prepare_portaudio_env() -> None:
    """Prefer PortAudio dylibs vendored in the .app Resources/lib."""
    from engine.paths import ROOT

    lib_dir = ROOT / "lib"
    if not lib_dir.is_dir():
        return
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    parts = [str(lib_dir)]
    if existing:
        parts.append(existing)
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(parts)


def open_browser(host: str, port: int) -> None:
    live = f"http://{host}:{port}/live"
    show = f"http://{host}:{port}/show?preview=1"
    if sys.platform == "darwin":
        subprocess.Popen(["open", live], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["open", show], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(live)
        webbrowser.open(show)


def wait_then_open(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                open_browser(host, port)
                return
        except OSError:
            time.sleep(0.2)
    open_browser(host, port)


def run_server(host: str, port: int) -> None:
    # Import only after KARAOK_SONGS_DIR is set.
    import uvicorn
    from server.preview_app import app

    config = uvicorn.Config(app, host=host, port=port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)

    def _stop(*_args) -> None:
        server.should_exit = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    server.run()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    host = os.environ.get("KARAOK_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    preferred_port = int(os.environ.get("KARAOK_PORT", str(DEFAULT_PORT)))

    cli_songs: Path | None = None
    if args:
        cli_songs = Path(args[0]).expanduser()

    library = pick_songs_library(cli_songs)
    if library is None:
        print(f"{APP_NAME}: cancelled — no song library selected.", file=sys.stderr)
        return 1

    packs = count_packs(library)
    os.environ["KARAOK_SONGS_DIR"] = str(library)
    # Ensure configure_songs_dir sees the new env if modules were imported early.
    from engine.paths import configure_songs_dir

    configure_songs_dir(str(library))
    prepare_portaudio_env()

    port = find_free_port(host, preferred_port)
    print(f"{APP_NAME}")
    print(f"  Library: {library} ({packs} packs)")
    print(f"  Control: http://{host}:{port}/live")
    print(f"  Overlay: http://{host}:{port}/show?preview=1")
    print("  Quit this app (or Ctrl+C) to stop the server.")

    opener = threading.Thread(target=wait_then_open, args=(host, port), daemon=True)
    opener.start()
    try:
        run_server(host, port)
    except KeyboardInterrupt:
        pass
    print(f"{APP_NAME}: stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
