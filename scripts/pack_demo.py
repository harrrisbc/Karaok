"""Build a portable demo zip of ready song packs for GitHub Releases.

Default: every pack under songs/ that has instrumental + lyrics + melody.
Excludes source audio and lrclib cache to keep the archive smaller.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\pack_demo.py
  .\\.venv\\Scripts\\python.exe scripts\\pack_demo.py --no-mv
  .\\.venv\\Scripts\\python.exe scripts\\pack_demo.py --out dist\\karaok-demo.zip
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.pack import list_packs
from engine.paths import SONGS_DIR

KEEP_NAMES = {
    "meta.json",
    "instrumental.wav",
    "vocals.wav",
    "melody.json",
    "lyrics.json",
    "mv.mp4",
}


def pack_files(pack_root: Path, *, include_mv: bool) -> list[Path]:
    names = set(KEEP_NAMES)
    if not include_mv:
        names.discard("mv.mp4")
    out: list[Path] = []
    for name in sorted(names):
        path = pack_root / name
        if path.is_file() and path.stat().st_size > 0:
            out.append(path)
    return out


def build_demo_zip(out: Path, *, include_mv: bool) -> dict:
    packs = []
    for pack in list_packs():
        meta = pack.load_meta()
        if not pack.instrumental.exists():
            continue
        if not pack.melody.exists() or not pack.lyrics.exists():
            continue
        files = pack_files(pack.root, include_mv=include_mv)
        if not any(f.name == "instrumental.wav" for f in files):
            continue
        packs.append((pack, meta, files))

    if not packs:
        raise SystemExit("No ready packs found under songs/")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    total = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        readme = (
            "Karaok demo song packs\n"
            f"Built: {datetime.now(timezone.utc).isoformat()}\n"
            f"Library: {SONGS_DIR}\n\n"
            "Extract so you get songs/<pack_id>/meta.json\n"
            "Then point Karaok at that songs folder (or copy into repo songs/).\n\n"
            "Only use packs you have the right to perform / redistribute.\n\n"
            "Included:\n"
        )
        for pack, meta, files in packs:
            readme += f"- {meta.id} — {meta.title}\n"
            for path in files:
                arc = Path("songs") / pack.root.name / path.name
                zf.write(path, arcname=str(arc).replace("\\", "/"))
                total += path.stat().st_size
        zf.writestr("README-DEMO.txt", readme)

    return {
        "out": str(out),
        "packs": len(packs),
        "bytes": total,
        "zip_bytes": out.stat().st_size,
        "titles": [m.title for _, m, _ in packs],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack demo song packs into a zip")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist" / "karaok-demo-packs.zip",
        help="Output zip path",
    )
    parser.add_argument(
        "--no-mv",
        action="store_true",
        help="Omit mv.mp4 (smaller; Live still works, Show MV disabled)",
    )
    args = parser.parse_args()
    info = build_demo_zip(args.out, include_mv=not args.no_mv)
    print(f"wrote {info['out']}")
    print(f"packs {info['packs']} · payload {info['bytes']/1e6:.1f} MB · zip {info['zip_bytes']/1e6:.1f} MB")
    for title in info["titles"]:
        print(f"  - {title}")


if __name__ == "__main__":
    main()
