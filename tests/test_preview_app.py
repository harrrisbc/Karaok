from __future__ import annotations

import os
import subprocess
import sys

from fastapi.testclient import TestClient

import pytest

from engine.pack import create_pack
from engine.paths import ROOT, configure_songs_dir


BANNED_ANALYSIS = (
    "engine.jobs",
    "engine.lyrics",
    "engine.melody",
    "engine.stems",
    "engine.ingest",
    "engine.lyrics_align",
    "engine.lrclib",
)


@pytest.fixture(autouse=True)
def restore_songs_dir():
    import engine.paths as paths_mod

    original = paths_mod.SONGS_DIR
    try:
        yield
    finally:
        configure_songs_dir(str(original))


class FakeSession:
    def __init__(self) -> None:
        self.running = False
        self.pack_id = None
        self.trim_ms = 0.0
        self.vocal_mix = 0.0
        self.difficulty = "normal"
        self.cents_limit = 50.0
        self.timing_limit = 0.09
        self.healed = None
        self.god_mode = False
        self.bg_mode = "none"
        self.bg_camera_id = ""
        self.has_mv = False

    def start(self, pack_id, **kwargs):
        self.running = True
        self.pack_id = pack_id
        self.trim_ms = float(kwargs.get("trim_ms") or 0)
        self.vocal_mix = float(kwargs.get("vocal_mix") or 0)
        return self.status()

    def stop(self):
        self.running = False
        return self.status()

    def status(self):
        return {
            "running": self.running,
            "calibrating": False,
            "god_mode": self.god_mode,
            "failed": False,
            "cleared": False,
            "pack_id": self.pack_id,
            "trim_ms": self.trim_ms,
            "vocal_mix": self.vocal_mix,
            "difficulty": self.difficulty,
            "cents_limit": round(self.cents_limit, 1),
            "timing_limit": round(self.timing_limit, 3),
            "bg": {
                "mode": self.bg_mode,
                "camera_id": self.bg_camera_id,
                "has_mv": self.has_mv,
                "pack_id": self.pack_id,
            },
            "frame": {"type": "idle"},
        }

    def set_trim(self, trim_ms):
        self.trim_ms = float(trim_ms)

    def set_vocal_mix(self, mix):
        self.vocal_mix = float(mix)

    def set_difficulty(self, name):
        self.difficulty = name.strip().lower()
        from engine.score import difficulty_params

        params = difficulty_params(self.difficulty)
        self.cents_limit = float(params["cents_limit"])
        self.timing_limit = float(params["timing_limit"])

    def set_thresholds(self, *, cents_limit=None, timing_limit=None):
        from engine.score import clamp_cents_limit, clamp_timing_limit

        if cents_limit is not None:
            self.cents_limit = clamp_cents_limit(cents_limit)
        if timing_limit is not None:
            self.timing_limit = clamp_timing_limit(timing_limit)
        return {
            "cents_limit": self.cents_limit,
            "timing_limit": self.timing_limit,
        }
    def heal_hp(self, amount=10.0):
        self.healed = {"pitch": 100.0, "rhythm": 100.0}
        return self.healed

    def set_god_mode(self, enabled):
        self.god_mode = bool(enabled)
        return {"god_mode": self.god_mode, "hp": {"pitch": 100.0, "rhythm": 100.0}}

    def set_bg(self, mode, camera_id=None):
        key = (mode or "none").strip().lower()
        if key not in {"mv", "camera", "none"}:
            raise ValueError(f"unknown bg mode: {mode}")
        self.bg_mode = key
        if camera_id is not None:
            self.bg_camera_id = str(camera_id)
        return {
            "mode": self.bg_mode,
            "camera_id": self.bg_camera_id,
            "has_mv": self.has_mv,
            "pack_id": self.pack_id,
        }

    def calibrate(self, **kwargs):
        return {"ok": True, "proposed_trim_ms": 12.0}

    def chart(self):
        return {"type": "chart", "pack_id": self.pack_id, "notes": [], "lines": []}


def test_preview_app_does_not_import_analysis_stack():
    script = (
        "import sys\n"
        "import server.preview_app\n"
        f"banned = {BANNED_ANALYSIS!r}\n"
        "loaded = [name for name in banned if name in sys.modules]\n"
        "assert loaded == [], loaded\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_preview_serves_control_and_overlay_not_prep(tmp_path):
    configure_songs_dir(str(tmp_path))
    from server.preview_app import app

    client = TestClient(app)
    home = client.get("/")
    live = client.get("/live")
    show = client.get("/show")
    assert home.status_code == 200
    assert "OPERATOR DESK" in home.text
    assert live.status_code == 200
    assert "OPERATOR DESK" in live.text
    assert show.status_code == 200
    assert "Show Overlay" in show.text or "stage" in show.text
    assert client.get("/prep").status_code == 404
    assert client.get("/api/jobs/active").status_code == 404
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["preview"] is True


def test_preview_lists_packs_from_configured_library(tmp_path):
    configure_songs_dir(str(tmp_path))
    pack = create_pack("Boss Demo", source="copy", singer="Haris")
    (pack.root / "instrumental.wav").write_bytes(b"fake-wav")
    from server.preview_app import app

    client = TestClient(app)
    songs = client.get("/api/songs").json()["songs"]
    assert any(row["title"] == "Boss Demo" and row["has_instrumental"] for row in songs)
    one = client.get(f"/api/songs/{pack.load_meta().id}")
    assert one.status_code == 200
    assert one.json()["singer"] == "Haris"


def test_preview_live_api_contract(tmp_path, monkeypatch):
    # Import app first — preview_app.configure_songs_dir() runs at import time.
    from server.preview_app import app

    configure_songs_dir(str(tmp_path))
    pack = create_pack("Live Contract", source="copy")
    (pack.root / "instrumental.wav").write_bytes(b"fake-wav")
    fake = FakeSession()
    monkeypatch.setattr("server.live_api.session", fake)
    monkeypatch.setattr(
        "server.live_api.list_devices",
        lambda: [
            {
                "index": 0,
                "name": "Mic",
                "hostapi": "Core Audio",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 48000,
                "default_low_input_latency": 0.01,
                "default_low_output_latency": 0.0,
                "is_default_input": True,
                "is_default_output": False,
            }
        ],
    )
    monkeypatch.setattr("server.live_api.default_device_indices", lambda: (0, None))

    client = TestClient(app)
    devices = client.get("/api/devices").json()
    assert devices["default_input"] == 0
    assert devices["devices"][0]["name"] == "Mic"

    pack_id = pack.load_meta().id
    started = client.post("/api/live/start", json={"pack_id": pack_id, "difficulty": "easy"})
    assert started.status_code == 200
    assert started.json()["running"] is True
    assert fake.pack_id == pack_id
    assert fake.difficulty == "easy"

    trimmed = client.post("/api/live/trim", json={"trim_ms": 8})
    assert trimmed.json()["trim_ms"] == 8.0
    mixed = client.post("/api/live/vocal-mix", json={"vocal_mix": 0.4})
    assert mixed.json()["vocal_mix"] == 0.4
    healed = client.post("/api/live/heal", json={"amount": 10})
    assert healed.json()["healed"] == {"pitch": 100.0, "rhythm": 100.0}
    god = client.post("/api/live/god", json={"enabled": True})
    assert god.status_code == 200
    assert god.json()["god_mode"] is True
    assert fake.god_mode is True
    stopped = client.post("/api/live/stop")
    assert stopped.json()["running"] is False

    missing = client.post("/api/live/start", json={"pack_id": "no-such-pack"})
    assert missing.status_code == 404

    bg = client.post("/api/live/bg", json={"mode": "camera", "camera_id": "dev-1"})
    assert bg.status_code == 200
    assert bg.json()["bg"]["mode"] == "camera"
    assert bg.json()["bg"]["camera_id"] == "dev-1"

    thresholds = client.post(
        "/api/live/thresholds",
        json={"cents_limit": 70, "timing_limit_ms": 120},
    )
    assert thresholds.status_code == 200
    body = thresholds.json()
    assert body["cents_limit"] == 70.0
    assert abs(body["timing_limit"] - 0.12) < 1e-9
    assert fake.cents_limit == 70.0
    assert abs(fake.timing_limit - 0.12) < 1e-9


def test_pack_mv_route_404_and_200(tmp_path):
    configure_songs_dir(str(tmp_path))
    pack = create_pack("MV Demo", source="copy")
    pack_id = pack.load_meta().id
    from server.preview_app import app

    client = TestClient(app)
    missing = client.get(f"/api/songs/{pack_id}/mv")
    assert missing.status_code == 404
    listed = client.get("/api/songs").json()["songs"]
    row = next(s for s in listed if s["id"] == pack_id)
    assert row["has_mv"] is False

    pack.mv.write_bytes(b"fake-mp4")
    ok = client.get(f"/api/songs/{pack_id}/mv")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("video/mp4")
    assert ok.content == b"fake-mp4"

    uploaded = client.post(
        f"/api/songs/{pack_id}/mv",
        files={"file": ("clip.mp4", b"new-mp4", "video/mp4")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["has_mv"] is True
    assert pack.mv.read_bytes() == b"new-mp4"

    bad = client.post(
        f"/api/songs/{pack_id}/mv",
        files={"file": ("clip.mov", b"x", "video/quicktime")},
    )
    assert bad.status_code == 404 or bad.status_code == 400


def test_full_app_keeps_prep_and_live_routes():
    from server.app import app

    client = TestClient(app)
    assert client.get("/prep").status_code == 200
    assert client.get("/live").status_code == 200
    assert client.get("/show").status_code == 200
    assert client.get("/api/jobs/active").status_code == 200
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert "preview" not in health or health.get("preview") is not True
