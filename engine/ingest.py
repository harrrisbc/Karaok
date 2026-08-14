from __future__ import annotations

from pathlib import Path

import shutil
import sys

from engine.pack import SongPack, create_pack
from engine.tools import ffmpeg_required, find_ffmpeg, run


AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".webm"}
VIDEO_SUFFIXES = {".mp4"}
# Prefer ≤720p MP4 — enough for show bg, smaller disk/decode than 1080.
YT_MV_FORMAT = (
    "bv*[height<=720][ext=mp4]+ba[ext=m4a]/"
    "b[height<=720][ext=mp4]/"
    "bv*[height<=720]+ba/"
    "b[height<=720]"
)


def import_local_audio(
    src: Path,
    title: str | None = None,
    lyrics_lang: str = "cantonese",
    singer: str = "",
) -> SongPack:
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError(f"不支援嘅音訊格式: {src.suffix}")

    pack = create_pack(
        title or src.stem,
        source="mp3" if src.suffix.lower() == ".mp3" else "file",
        lyrics_lang=lyrics_lang,
        singer=singer,
    )
    dest = pack.root / f"source{src.suffix.lower()}"
    dest.write_bytes(src.read_bytes())
    return pack


def find_js_runtime() -> tuple[str, str] | None:
    """Return (runtime_name, executable_path) for yt-dlp EJS, or None."""
    for name in ("node", "deno", "qjs"):
        path = shutil.which(name)
        if path:
            runtime = "quickjs" if name == "qjs" else name
            return runtime, path
    node_guess = Path(r"C:\Program Files\nodejs\node.exe")
    if node_guess.exists():
        return "node", str(node_guess)
    return None


def _yt_dlp_base() -> list[str]:
    return [sys.executable, "-m", "yt_dlp"]


def _yt_dlp_js_args() -> list[str]:
    """YouTube needs an external JS runtime (EJS). Deno is default-only; enable Node explicitly."""
    found = find_js_runtime()
    if not found:
        raise RuntimeError(
            "YouTube 下載需要 JavaScript runtime（Node ≥22 或 Deno）。"
            " 已裝 Node 嘅話請確認 node 喺 PATH；"
            " 見 https://github.com/yt-dlp/yt-dlp/wiki/EJS"
        )
    name, path = found
    return ["--js-runtimes", f"{name}:{path}"]


def _yt_dlp() -> list[str]:
    return _yt_dlp_base() + _yt_dlp_js_args()


def youtube_mv_flags(out_tmpl: str) -> list[str]:
    """yt-dlp flags for pack mv.mp4 (no JS runtime — testable)."""
    return [
        "-f",
        YT_MV_FORMAT,
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "--newline",
        "-o",
        out_tmpl,
    ]


def attach_mv(pack: SongPack, src: Path) -> Path:
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f"不支援嘅影片格式: {src.suffix}（要 .mp4）")
    dest = pack.mv
    dest.write_bytes(src.read_bytes())
    return dest


def download_youtube_mv(pack: SongPack, url: str) -> bool:
    """Best-effort MV. Audio import still succeeds if this fails."""
    out_tmpl = str(pack.root / "mv.%(ext)s")
    try:
        run(_yt_dlp() + youtube_mv_flags(out_tmpl) + [url])
    except Exception:
        return False
    if pack.mv.exists() and pack.mv.stat().st_size > 0:
        return True
    for cand in pack.root.glob("mv.*"):
        if cand.suffix.lower() == ".mp4" and cand.stat().st_size > 0:
            if cand != pack.mv:
                cand.replace(pack.mv)
            return pack.mv.exists()
    return False


def import_youtube(url: str, lyrics_lang: str = "cantonese", singer: str = "") -> SongPack:
    ffmpeg_required()
    title = _youtube_title(url) or "youtube"
    pack = create_pack(
        title, source="youtube", source_url=url, lyrics_lang=lyrics_lang, singer=singer
    )
    pack.update_status("downloading")

    out_tmpl = str(pack.root / "source.%(ext)s")
    run(
        _yt_dlp()
        + [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--no-playlist",
            "--newline",
            "-o",
            out_tmpl,
            url,
        ]
    )

    if not pack.source_audio.exists():
        raise RuntimeError("yt-dlp 完成但搵唔到 source audio")
    download_youtube_mv(pack, url)
    return pack


def _youtube_title(url: str) -> str | None:
    try:
        result = run(_yt_dlp() + ["--no-playlist", "--print", "%(title)s", url])
        title = result.stdout.strip().splitlines()[0].strip()
        return title or None
    except Exception:
        return None


def has_youtube_tools() -> dict:
    yt = True
    try:
        run(_yt_dlp_base() + ["--version"])
    except Exception:
        yt = False
    js = find_js_runtime()
    return {
        "yt_dlp": yt,
        "ffmpeg": bool(find_ffmpeg()),
        "js_runtime": js[0] if js else None,
    }
