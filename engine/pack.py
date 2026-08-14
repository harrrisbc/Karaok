from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from engine.paths import SONGS_DIR, ensure_dirs

SCHEMA_VERSION = 1

STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_SPLITTING = "splitting"
STATUS_STEMS_READY = "stems_ready"
STATUS_ANALYZING = "analyzing"
STATUS_READY = "ready"
STATUS_ERROR = "error"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    """ASCII-only folder slug — Demucs/Windows cp950 choke on CJK pack paths."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:48] or "song"


@dataclass
class SongMeta:
    id: str
    title: str
    source: str
    status: str = STATUS_QUEUED
    source_url: str = ""
    error: str = ""
    lyrics_lang: str = "cantonese"
    singer: str = ""
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "SongMeta":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


class SongPack:
    def __init__(self, root: Path):
        self.root = root

    @property
    def meta_path(self) -> Path:
        return self.root / "meta.json"

    @property
    def source_audio(self) -> Path:
        for name in ("source.wav", "source.mp3", "source.flac", "source.m4a"):
            path = self.root / name
            if path.exists():
                return path
        return self.root / "source.mp3"

    @property
    def vocals(self) -> Path:
        return self.root / "vocals.wav"

    @property
    def instrumental(self) -> Path:
        return self.root / "instrumental.wav"

    @property
    def melody(self) -> Path:
        return self.root / "melody.json"

    @property
    def lyrics(self) -> Path:
        return self.root / "lyrics.json"

    def load_meta(self) -> SongMeta:
        return SongMeta.from_json(json.loads(self.meta_path.read_text(encoding="utf-8")))

    def save_meta(self, meta: SongMeta) -> None:
        meta.updated_at = utc_now()
        self.meta_path.write_text(
            json.dumps(meta.to_json(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def update_status(self, status: str, error: str = "") -> SongMeta:
        meta = self.load_meta()
        meta.status = status
        meta.error = error
        self.save_meta(meta)
        return meta

    def lyrics_provenance(self) -> dict:
        """Lightweight lyrics source for Prep UI — empty if no lyrics.json."""
        if not self.lyrics.exists():
            return {
                "lyrics_source": None,
                "lyrics_method": None,
                "lyrics_locked": False,
                "lrclib_id": None,
            }
        try:
            payload = json.loads(self.lyrics.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "lyrics_source": None,
                "lyrics_method": None,
                "lyrics_locked": False,
                "lrclib_id": None,
            }
        lrclib = payload.get("lrclib") if isinstance(payload.get("lrclib"), dict) else {}
        source = payload.get("source")
        method = payload.get("method")
        if not source:
            if method and str(method).startswith("lrclib"):
                source = "lrclib"
            elif method == "openai-whisper":
                source = "whisper"
            elif method in ("lyric-txt-correct", "stable-ts-align", "remap-existing-timing"):
                source = "user-txt"
        return {
            "lyrics_source": source,
            "lyrics_method": method,
            "lyrics_locked": bool(payload.get("locked")),
            "lrclib_id": lrclib.get("id"),
        }

    def public_dict(self) -> dict:
        meta = self.load_meta()
        data = meta.to_json()
        data["has_vocals"] = self.vocals.exists()
        data["has_instrumental"] = self.instrumental.exists()
        data["has_melody"] = self.melody.exists()
        data["has_lyrics"] = self.lyrics.exists()
        data.update(self.lyrics_provenance())
        return data


def create_pack(
    title: str,
    source: str,
    source_url: str = "",
    lyrics_lang: str = "cantonese",
    singer: str = "",
) -> SongPack:
    ensure_dirs()
    pack_id = f"{slugify(title)}-{uuid.uuid4().hex[:8]}"
    root = SONGS_DIR / pack_id
    root.mkdir(parents=True, exist_ok=False)
    pack = SongPack(root)
    pack.save_meta(
        SongMeta(
            id=pack_id,
            title=title,
            source=source,
            source_url=source_url,
            lyrics_lang=lyrics_lang,
            singer=singer.strip(),
        )
    )
    return pack


def list_packs() -> list[SongPack]:
    ensure_dirs()
    packs: list[SongPack] = []
    for child in SONGS_DIR.iterdir():
        if child.is_dir() and (child / "meta.json").exists():
            packs.append(SongPack(child))
    # Newest first (created_at), so Prep doesn't hide fresh imports mid-list.
    packs.sort(key=lambda p: p.load_meta().created_at or "", reverse=True)
    return packs


def get_pack(pack_id: str) -> SongPack:
    root = SONGS_DIR / pack_id
    if not (root / "meta.json").exists():
        raise FileNotFoundError(pack_id)
    return SongPack(root)
