from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from engine.ingest import import_local_audio, import_youtube
from engine.lyrics import extract_lyrics, normalize_lang, release_cuda
from engine.lyrics_align import align_lyrics_from_text, apply_lrc_to_pack
from engine.lrclib import (
    cache_raw,
    fetch_record_by_id,
    line_count_sane,
    lyrics_locked,
    pack_duration_sec,
    prepare_record,
    record_by_id,
    search_lrclib,
)
from engine.melody import extract_melody, refine_melody_with_lyrics
from engine.pack import (
    STATUS_ANALYZING,
    STATUS_ERROR,
    STATUS_READY,
    STATUS_SPLITTING,
    STATUS_STEMS_READY,
    SongPack,
    get_pack,
)
from engine.stems import split_stems


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    step: str = "queued"
    pack_id: str | None = None
    error: str = ""
    log: list[str] = field(default_factory=list)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "step": self.step,
            "pack_id": self.pack_id,
            "error": self.error,
            "log": self.log[-20:],
        }


class BusyError(RuntimeError):
    """Another prep job is already using the GPU."""


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active_id: str | None = None

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> Job | None:
        with self._lock:
            return self._active_unlocked()

    def _active_unlocked(self) -> Job | None:
        if not self._active_id:
            return None
        job = self._jobs.get(self._active_id)
        if job and job.status in ("queued", "running"):
            return job
        self._active_id = None
        return None

    def recent(self, limit: int = 8) -> list[Job]:
        jobs = list(self._jobs.values())
        return list(reversed(jobs[-limit:]))

    def submit(self, kind: str, fn: Callable[[Job], None]) -> Job:
        with self._lock:
            current = self._active_unlocked()
            if current is not None:
                raise BusyError(
                    f"已有 job 進行中: {current.id} · {current.step} "
                    f"(pack={current.pack_id or '-'})。等佢完先再開。"
                )
            job = Job(id=uuid.uuid4().hex[:12], kind=kind, status="queued")
            self._jobs[job.id] = job
            self._active_id = job.id

        def run() -> None:
            try:
                job.status = "running"
                fn(job)
                job.status = "done"
            except Exception as exc:
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log.append(traceback.format_exc(limit=8))
                if job.pack_id:
                    try:
                        get_pack(job.pack_id).update_status(STATUS_ERROR, job.error)
                    except Exception:
                        pass
            finally:
                with self._lock:
                    if self._active_id == job.id:
                        self._active_id = None

        threading.Thread(target=run, daemon=True).start()
        return job


runner = JobRunner()


def start_local_import(
    path,
    title: str | None = None,
    lyrics_lang: str = "cantonese",
    whisper_model: str | None = None,
    singer: str = "",
) -> Job:
    source = Path(path)
    lang = normalize_lang(lyrics_lang)

    def work(job: Job) -> None:
        try:
            job.step = "import"
            job.status = "running"
            pack = import_local_audio(source, title=title, lyrics_lang=lang, singer=singer)
            job.pack_id = pack.load_meta().id
            _prep_full(job, pack, lang, whisper_model)
        finally:
            source.unlink(missing_ok=True)

    return runner.submit("local", work)


def start_youtube_import(
    url: str,
    lyrics_lang: str = "cantonese",
    whisper_model: str | None = None,
    singer: str = "",
) -> Job:
    lang = normalize_lang(lyrics_lang)

    def work(job: Job) -> None:
        job.step = "download"
        job.status = "running"
        pack = import_youtube(url, lyrics_lang=lang, singer=singer)
        job.pack_id = pack.load_meta().id
        _prep_full(job, pack, lang, whisper_model)

    return runner.submit("youtube", work)


def start_analyze(
    pack_id: str,
    lyrics_lang: str | None = None,
    whisper_model: str | None = None,
    prefer_whisper: bool = False,
) -> Job:
    """Re-run melody + lyrics on an existing pack."""

    def work(job: Job) -> None:
        job.status = "running"
        job.pack_id = pack_id
        pack = get_pack(pack_id)
        lang = normalize_lang(lyrics_lang or pack.load_meta().lyrics_lang)
        meta = pack.load_meta()
        meta.lyrics_lang = lang
        pack.save_meta(meta)
        _analyze(job, pack, lang, whisper_model, prefer_whisper=prefer_whisper)

    return runner.submit("analyze", work)


def start_lyrics_whisper(
    pack_id: str,
    *,
    lyrics_lang: str | None = None,
    whisper_model: str | None = None,
) -> Job:
    """Force Whisper ASR lyrics — skip LRCLIB. Overwrites even locked lyrics."""

    def work(job: Job) -> None:
        job.status = "running"
        job.pack_id = pack_id
        pack = get_pack(pack_id)
        if not pack.vocals.exists():
            raise FileNotFoundError("vocals.wav missing — run stem split first")
        lang = normalize_lang(lyrics_lang or pack.load_meta().lyrics_lang)
        meta = pack.load_meta()
        meta.lyrics_lang = lang
        pack.save_meta(meta)
        job.step = f"lyrics-whisper ({whisper_model or 'default'})"
        pack.update_status(STATUS_ANALYZING)
        lyrics = _fill_lyrics(
            job,
            pack,
            lang,
            whisper_model,
            prefer_whisper=True,
            force=True,
        )
        job.log.append(
            f"whisper lines={len(lyrics.get('lines') or [])} "
            f"method={lyrics.get('method')} model={lyrics.get('model')}"
        )
        refined = refine_melody_with_lyrics(pack)
        if refined is not None:
            job.log.append(
                f"melody refined to lyrics: {refined.get('notes_before_refine')} → {refined.get('note_count')}"
            )
        pack.update_status(STATUS_READY)
        job.step = "ready"

    return runner.submit("lyrics-whisper", work)


def start_lyrics_align(
    pack_id: str,
    text: str,
    *,
    lyrics_lang: str | None = None,
    whisper_model: str | None = None,
    prefer_remap: bool = False,
) -> Job:
    """Align a user lyric txt onto vocals timing (overwrite lyrics.json)."""

    def work(job: Job) -> None:
        job.status = "running"
        job.pack_id = pack_id
        pack = get_pack(pack_id)
        if not pack.vocals.exists():
            raise FileNotFoundError("vocals.wav missing — run stem split first")
        lang = normalize_lang(lyrics_lang or pack.load_meta().lyrics_lang)
        meta = pack.load_meta()
        meta.lyrics_lang = lang
        pack.save_meta(meta)
        job.step = f"lyrics-align ({whisper_model or 'default'})"
        pack.update_status(STATUS_ANALYZING)
        lyrics = align_lyrics_from_text(
            pack,
            text,
            language=lang,
            model_name=whisper_model,
            prefer_remap=prefer_remap,
        )
        job.log.append(
            f"aligned lines: {len(lyrics.get('lines') or [])} "
            f"method={lyrics.get('method')} model={lyrics.get('model')}"
        )
        refined = refine_melody_with_lyrics(pack)
        if refined is not None:
            job.log.append(
                f"melody refined to lyrics: {refined.get('notes_before_refine')} → {refined.get('note_count')}"
            )
        pack.update_status(STATUS_READY)
        job.step = "ready"

    return runner.submit("lyrics-align", work)


def start_lyrics_lrclib(
    pack_id: str,
    *,
    lrclib_id: int | None = None,
    lrc_text: str | None = None,
    mode: str = "align",
    lyrics_lang: str | None = None,
    whisper_model: str | None = None,
    force: bool = False,
    matched_by: str = "apply",
) -> Job:
    """Apply LRCLIB or pasted LRC onto a pack (explicit Prep action)."""

    def work(job: Job) -> None:
        job.status = "running"
        job.pack_id = pack_id
        pack = get_pack(pack_id)
        if not pack.vocals.exists():
            raise FileNotFoundError("vocals.wav missing — run stem split first")
        if lyrics_locked(pack) and not force:
            raise RuntimeError("lyrics.json 已手動對齊 — 要覆蓋請 force")
        lang = normalize_lang(lyrics_lang or pack.load_meta().lyrics_lang)
        job.step = f"lyrics-lrclib ({mode})"
        pack.update_status(STATUS_ANALYZING)
        extra = None
        source = "paste-lrc"
        locked = True
        raw_lrc = (lrc_text or "").strip()
        if lrclib_id is not None:
            rec = record_by_id(pack, int(lrclib_id))
            if rec is None:
                from engine.lrclib import _http_get, _url

                status, body = _http_get(_url("/api/get", {"id": int(lrclib_id)}))
                rec = body if status == 200 and isinstance(body, dict) else None
            if rec is None:
                raise FileNotFoundError(f"lrclib id {lrclib_id} 唔喺 cache，請先 Search")
            prepared = prepare_record(rec, lang=lang, title=pack.load_meta().title, matched_by=matched_by)
            raw_lrc = rec.get("syncedLyrics") or ""
            extra = {"lrclib": prepared["lrclib"]}
            source = "lrclib"
            locked = False
        if not raw_lrc:
            raise ValueError("冇 LRC 文字")
        lyrics = apply_lrc_to_pack(
            pack,
            raw_lrc,
            mode=mode,
            language=lang,
            model_name=whisper_model,
            source=source,
            locked=locked,
            extra=extra,
        )
        job.log.append(
            f"lrclib applied lines={len(lyrics.get('lines') or [])} method={lyrics.get('method')}"
        )
        refined = refine_melody_with_lyrics(pack)
        if refined is not None:
            job.log.append(
                f"melody refined to lyrics: {refined.get('notes_before_refine')} → {refined.get('note_count')}"
            )
        pack.update_status(STATUS_READY)
        job.step = "ready"

    return runner.submit("lyrics-lrclib", work)


def analyze_pack(
    pack: SongPack,
    lyrics_lang: str | None = None,
    whisper_model: str | None = None,
) -> None:
    """Synchronous analyze for CLI."""
    job = Job(id="cli", kind="analyze", status="running")
    lang = normalize_lang(lyrics_lang or pack.load_meta().lyrics_lang)
    meta = pack.load_meta()
    meta.lyrics_lang = lang
    pack.save_meta(meta)
    _analyze(job, pack, lang, whisper_model)


def _prep_full(
    job: Job,
    pack: SongPack,
    lyrics_lang: str,
    whisper_model: str | None = None,
) -> None:
    job.step = "split"
    pack.update_status(STATUS_SPLITTING)
    release_cuda()
    split_stems(pack)
    pack.update_status(STATUS_STEMS_READY)
    job.step = "stems_ready"
    job.log.append(f"stems ready: {pack.root}")
    _analyze(job, pack, lyrics_lang, whisper_model)


def _analyze(
    job: Job,
    pack: SongPack,
    lyrics_lang: str,
    whisper_model: str | None = None,
    prefer_whisper: bool = False,
) -> None:
    if not pack.vocals.exists():
        raise FileNotFoundError("vocals.wav missing — run stem split first")
    job.step = "melody"
    pack.update_status(STATUS_ANALYZING)
    melody = extract_melody(pack)
    job.log.append(f"melody notes: {melody.get('note_count', 0)}")

    job.step = f"lyrics ({whisper_model or 'default'})"
    lyrics = _fill_lyrics(
        job, pack, lyrics_lang, whisper_model, prefer_whisper=prefer_whisper
    )
    job.log.append(
        f"lyrics lines: {len(lyrics.get('lines') or [])} "
        f"lang={lyrics.get('lang_preset')} model={lyrics.get('model')}"
    )
    refined = refine_melody_with_lyrics(pack)
    if refined is not None:
        job.log.append(
            f"melody refined to lyrics: {refined.get('notes_before_refine')} → {refined.get('note_count')}"
        )

    pack.update_status(STATUS_READY)
    job.step = "ready"
    job.log.append(f"ready: {pack.root}")


def _fill_lyrics(
    job: Job,
    pack: SongPack,
    lyrics_lang: str,
    whisper_model: str | None,
    *,
    prefer_whisper: bool = False,
    force: bool = False,
) -> dict:
    if lyrics_locked(pack) and not force:
        job.log.append("lyrics locked (hand-corrected) — skip overwrite")
        import json

        return json.loads(pack.lyrics.read_text(encoding="utf-8"))

    if prefer_whisper:
        job.log.append("prefer_whisper — skip LRCLIB")
        return extract_lyrics(pack, language=lyrics_lang, model_name=whisper_model)

    meta = pack.load_meta()
    duration = pack_duration_sec(pack)
    try:
        # SongMeta has no artist field yet — LRCLIB parses "Artist - Title" from title when empty.
        found = search_lrclib(title=meta.title, artist="", duration=duration)
        cache_raw(pack, found)
        n_cand = len(found.get("candidates") or [])
        job.log.append(f"lrclib attempts={found.get('attempts')} candidates={n_cand}")
    except Exception as exc:
        job.log.append(f"lrclib skip: {type(exc).__name__}: {exc}")
        found = {"auto": None}

    auto = found.get("auto")
    rec = (auto or {}).get("record") if auto else None
    if rec:
        try:
            import json

            old_n = 0
            if pack.lyrics.exists():
                old_n = len((json.loads(pack.lyrics.read_text(encoding="utf-8")).get("lines") or []))
            prepared = prepare_record(
                rec, lang=lyrics_lang, title=meta.title, matched_by=auto.get("matched_by") or "get"
            )
            new_n = len(prepared["normalized"]["lines"])
            if not line_count_sane(old_n, new_n):
                job.log.append(f"lrclib line count {new_n} vs existing {old_n} — not auto-applied")
            else:
                # Auto-apply only happens when duration already matches (±2s).
                # Trust LRC clocks — stable-ts align often stretches the first
                # line across the instrumental intro (lyric "playing" from t≈0).
                lyrics = apply_lrc_to_pack(
                    pack,
                    rec.get("syncedLyrics") or "",
                    mode="trust-lrc",
                    language=lyrics_lang,
                    model_name=whisper_model,
                    source="lrclib",
                    locked=False,
                    extra={"lrclib": prepared["lrclib"]},
                )
                job.log.append(
                    f"lyrics from lrclib-direct lines={len(lyrics.get('lines') or [])} "
                    f"id={prepared['lrclib'].get('id')} "
                    f"delta={auto.get('duration_delta')} "
                    f"offset={lyrics.get('lrc_offset_sec')}"
                )
                return lyrics
        except Exception as exc:
            job.log.append(f"lrclib apply failed ({type(exc).__name__}: {exc}); fallback ASR")

    lyrics = extract_lyrics(pack, language=lyrics_lang, model_name=whisper_model)
    return lyrics
