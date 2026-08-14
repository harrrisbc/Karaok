from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def which(name: str) -> str | None:
    return shutil.which(name)


def find_ffmpeg() -> str | None:
    found = which("ffmpeg")
    if found:
        return found
    extras = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
    ]
    for path in extras:
        if path.exists():
            return str(path)
    winget = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget.exists():
        matches = sorted(winget.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))
        if matches:
            return str(matches[-1])
    return None


def ffmpeg_required() -> str:
    path = find_ffmpeg()
    if not path:
        raise RuntimeError(
            "ffmpeg 未安裝。Prep（YouTube 同轉檔）需要 ffmpeg。"
            " 可用 winget install --id Gyan.FFmpeg -e"
        )
    return path


def _path_with_ffmpeg() -> str:
    path = os.environ.get("PATH", "")
    ff = find_ffmpeg()
    if ff:
        bin_dir = str(Path(ff).parent)
        if bin_dir.lower() not in path.lower():
            return bin_dir + os.pathsep + path
    return path


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = _path_with_ffmpeg()
    # Demucs prints output paths; Windows default cp950 can't encode CJK pack names.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"command failed: {cmd[0]}")
    return result
