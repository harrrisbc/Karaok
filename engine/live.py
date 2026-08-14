from __future__ import annotations

import json
import threading
from typing import Any

import numpy as np

from engine.pack import SongPack, get_pack
from engine.pitch import yin_f0
from engine.score import HealthPoints, RunningSkill, score_snapshot


TARGET_SR = 48000
BLOCK = 1024
YIN_FRAME = 2048


def _latency_ms(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (tuple, list)):
        value = value[-1]
    try:
        return max(0.0, float(value) * 1000.0)
    except (TypeError, ValueError):
        return 0.0


def _load_audio(path, sr: int) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, file_sr = sf.read(str(path), always_2d=True, dtype="float32")
    if file_sr != sr:
        audio = resample_poly(audio, sr, file_sr, axis=0).astype(np.float32)
    return audio


def blend_guide(inst: np.ndarray, voc: np.ndarray, mix: float) -> np.ndarray:
    """inst + mix * vocals, clipped. mix 0 = karaoke, 1 = full guide vocal."""
    mix = float(max(0.0, min(1.0, mix)))
    if mix <= 0.0 or voc.size == 0:
        return inst
    n = min(len(inst), len(voc))
    out = inst.copy()
    if n == 0:
        return out
    v = voc[:n]
    if v.shape[1] != out.shape[1]:
        if v.shape[1] == 1:
            v = np.repeat(v, out.shape[1], axis=1)
        else:
            v = v[:, : out.shape[1]]
    out[:n] = np.clip(out[:n] + mix * v, -1.0, 1.0)
    return out


def _load_instrumental(path, sr: int) -> np.ndarray:
    return _load_audio(path, sr)


class LiveSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.failed = False
        self.pack_id: str | None = None
        self.title = ""
        self.singer = ""
        self.duration = 0.0
        self.notes: list[dict] = []
        self.lines: list[dict] = []
        self.words: list[dict] = []
        self.trim_ms = 0.0
        self.vocal_mix = 0.0
        self.input_ms = 0.0
        self.output_ms = 0.0
        self.input_device: int | None = None
        self.output_device: int | None = None
        self.input_channel = 0
        self.playback_pos = 0.0
        self.latest: dict[str, Any] = {"type": "idle"}
        self._streams: list[Any] = []
        self._cursor = 0
        self._instrumental: np.ndarray | None = None
        self._vocals: np.ndarray | None = None
        self._in_buf = np.zeros(YIN_FRAME, dtype=np.float32)
        self._skill = RunningSkill()
        self._hp = HealthPoints()
        self._sr = TARGET_SR
        self.calibrating = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "calibrating": self.calibrating,
                "failed": self.failed,
                "pack_id": self.pack_id,
                "title": self.title,
                "singer": self.singer,
                "playback_t": round(self.playback_pos, 3),
                "duration": self.duration,
                "input_device": self.input_device,
                "output_device": self.output_device,
                "input_channel": self.input_channel,
                "trim_ms": self.trim_ms,
                "vocal_mix": round(self.vocal_mix, 3),
                "input_ms": round(self.input_ms, 1),
                "output_ms": round(self.output_ms, 1),
                "foh_vocal_delay_ms": round(self.output_ms, 1),
                "frame": self.latest,
            }

    def chart(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": "chart",
                "pack_id": self.pack_id,
                "title": self.title,
                "singer": self.singer,
                "duration": self.duration,
                "notes": [
                    {
                        "t": n["t"],
                        "duration": n["duration"],
                        "midi": n.get("midi"),
                    }
                    for n in self.notes
                ],
            }

    def set_trim(self, trim_ms: float) -> None:
        with self._lock:
            self.trim_ms = float(max(-80.0, min(80.0, trim_ms)))

    def set_vocal_mix(self, mix: float) -> None:
        with self._lock:
            self.vocal_mix = float(max(0.0, min(1.0, mix)))

    def calibrate(
        self,
        *,
        input_device: int | None,
        output_device: int | None,
        input_channel: int = 0,
    ) -> dict[str, Any]:
        """Measure click-to-mic loopback while the session is idle."""
        with self._lock:
            if self.running:
                return {"ok": False, "error": "busy", "message": "Stop the live take before calibrating."}
            if self.calibrating:
                return {"ok": False, "error": "busy", "message": "Calibration is already running."}
            self.calibrating = True
        try:
            from engine.latency_calibrate import measure_loop_latency_ms

            return measure_loop_latency_ms(
                input_device=input_device,
                output_device=output_device,
                input_channel=input_channel,
                sr=TARGET_SR,
            )
        finally:
            with self._lock:
                self.calibrating = False

    def start(
        self,
        pack_id: str,
        *,
        input_device: int | None,
        output_device: int | None,
        input_channel: int = 0,
        trim_ms: float = 0.0,
        singer: str | None = None,
        vocal_mix: float = 0.0,
    ) -> dict[str, Any]:
        self.stop()
        from engine.lyrics import drop_model_cache

        drop_model_cache()
        pack = get_pack(pack_id)
        if not pack.instrumental.exists():
            raise FileNotFoundError("instrumental.wav missing")
        melody = json.loads(pack.melody.read_text(encoding="utf-8")) if pack.melody.exists() else {}
        lyrics = json.loads(pack.lyrics.read_text(encoding="utf-8")) if pack.lyrics.exists() else {}
        audio = _load_instrumental(pack.instrumental, TARGET_SR)
        vocals = _load_audio(pack.vocals, TARGET_SR) if pack.vocals.exists() else None

        import sounddevice as sd

        extra_in: dict = {}
        extra_out: dict = {}
        # Prefer WASAPI on Windows when the selected device uses it
        try:
            if input_device is not None:
                api = sd.query_hostapis()[int(sd.query_devices(input_device)["hostapi"])]["name"]
                if "WASAPI" in api:
                    extra_in = {"wasapi_exclusive": False}
            if output_device is not None:
                api = sd.query_hostapis()[int(sd.query_devices(output_device)["hostapi"])]["name"]
                if "WASAPI" in api:
                    extra_out = {"wasapi_exclusive": False}
        except Exception:
            extra_in, extra_out = {}, {}

        with self._lock:
            meta = pack.load_meta()
            self.pack_id = pack_id
            self.title = meta.title
            self.singer = (singer if singer is not None else meta.singer) or ""
            self.failed = False
            self.notes = list(melody.get("notes") or [])
            self.lines = list(lyrics.get("lines") or [])
            self.words = list(lyrics.get("words") or [])
            self.duration = float(len(audio) / TARGET_SR)
            self.trim_ms = float(trim_ms)
            self.vocal_mix = float(max(0.0, min(1.0, vocal_mix)))
            self.input_device = input_device
            self.output_device = output_device
            self.input_channel = max(0, int(input_channel))
            self.playback_pos = 0.0
            self._cursor = 0
            self._instrumental = audio
            self._vocals = vocals
            self._skill = RunningSkill()
            self._hp = HealthPoints()
            self.running = True
            self._in_buf[:] = 0

        out_ch = 2 if audio.shape[1] >= 2 else 1

        def out_cb(outdata, frames, time_info, status):  # noqa: ARG001
            self._on_out(outdata, frames)

        def in_cb(indata, frames, time_info, status):  # noqa: ARG001
            self._on_in(indata)

        extra_settings_out = None
        extra_settings_in = None
        try:
            if hasattr(sd, "WasapiSettings"):
                if extra_out:
                    extra_settings_out = sd.WasapiSettings(exclusive=False)
                if extra_in:
                    extra_settings_in = sd.WasapiSettings(exclusive=False)
        except Exception:
            extra_settings_out = extra_settings_in = None

        out_stream = sd.OutputStream(
            samplerate=TARGET_SR,
            blocksize=BLOCK,
            device=output_device,
            channels=out_ch,
            dtype="float32",
            callback=out_cb,
            extra_settings=extra_settings_out,
        )
        in_ch = max(1, self.input_channel + 1)
        try:
            max_in = int(sd.query_devices(input_device)["max_input_channels"]) if input_device is not None else 2
            in_ch = min(max(in_ch, 1), max(1, max_in))
        except Exception:
            in_ch = 1
        in_stream = sd.InputStream(
            samplerate=TARGET_SR,
            blocksize=BLOCK,
            device=input_device,
            channels=in_ch,
            dtype="float32",
            callback=in_cb,
            extra_settings=extra_settings_in,
        )
        try:
            out_stream.start()
            in_stream.start()
        except Exception:
            try:
                out_stream.close()
            except Exception:
                pass
            try:
                in_stream.close()
            except Exception:
                pass
            out_stream = sd.OutputStream(
                samplerate=TARGET_SR,
                blocksize=BLOCK,
                device=output_device,
                channels=out_ch,
                dtype="float32",
                callback=out_cb,
            )
            in_stream = sd.InputStream(
                samplerate=TARGET_SR,
                blocksize=BLOCK,
                device=input_device,
                channels=in_ch,
                dtype="float32",
                callback=in_cb,
            )
            out_stream.start()
            in_stream.start()
        with self._lock:
            self._streams = [out_stream, in_stream]
            self.output_ms = _latency_ms(getattr(out_stream, "latency", 0))
            self.input_ms = _latency_ms(getattr(in_stream, "latency", 0))
            if self.output_ms <= 0:
                self.output_ms = 20.0
            if self.input_ms <= 0:
                self.input_ms = 10.0
        return self.status()

    def _on_out(self, outdata, frames: int) -> None:
        with self._lock:
            audio = self._instrumental
            voc = self._vocals
            mix = self.vocal_mix
            if audio is None or not self.running:
                outdata.fill(0)
                return
            start = self._cursor
            end = start + frames
            chunk = audio[start:end]
            if voc is not None and mix > 0 and len(chunk):
                vchunk = voc[start:end]
                if len(vchunk) < len(chunk):
                    pad = np.zeros((len(chunk) - len(vchunk), vchunk.shape[1] if len(vchunk) else chunk.shape[1]), dtype=np.float32)
                    vchunk = np.vstack([vchunk, pad]) if len(vchunk) else pad
                chunk = blend_guide(chunk, vchunk, mix)
            n = len(chunk)
            ch = outdata.shape[1]
            outdata.fill(0)
            if n:
                if chunk.shape[1] == 1 and ch == 2:
                    outdata[:n, 0] = chunk[:, 0]
                    outdata[:n, 1] = chunk[:, 0]
                else:
                    use = min(ch, chunk.shape[1])
                    outdata[:n, :use] = chunk[:, :use]
            self._cursor = end
            self.playback_pos = self._cursor / float(self._sr)
            if self._cursor >= len(audio):
                self.running = False

    def _on_in(self, indata) -> None:
        with self._lock:
            if not self.running:
                return
            ch = min(self.input_channel, indata.shape[1] - 1)
            mono = indata[:, ch]
            n = len(mono)
            self._in_buf = np.roll(self._in_buf, -n)
            self._in_buf[-n:] = mono
            hz, conf = yin_f0(self._in_buf, self._sr)
            voiced = hz is not None and conf > 0.35
            self.latest = score_snapshot(
                playback_pos=self.playback_pos,
                duration=self.duration,
                output_ms=self.output_ms,
                input_ms=self.input_ms,
                trim_ms=self.trim_ms,
                sung_hz=hz if voiced else None,
                voiced=voiced,
                notes=self.notes,
                lines=self.lines,
                words=self.words,
                skill=self._skill,
                hp=self._hp,
                dt=n / float(self._sr),
                title=self.title,
                singer=self.singer,
            )
            if self._hp.dead:
                self.running = False
                self.failed = True

    def stop(self) -> None:
        streams = []
        with self._lock:
            self.running = False
            self.failed = False
            streams = list(self._streams)
            self._streams = []
            self._instrumental = None
            self._vocals = None
            self.latest = {"type": "idle"}
        for stream in streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass


session = LiveSession()
