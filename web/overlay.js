const params = new URLSearchParams(location.search);
const preview = params.has("preview");
if (params.has("transparent")) document.body.classList.add("transparent");
if (preview) {
  document.documentElement.classList.add("preview-fit");
  const fitPreview = () => {
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080, 1);
    document.documentElement.style.setProperty("--preview-scale", String(scale));
  };
  fitPreview();
  window.addEventListener("resize", fitPreview);
}

const $ = (id) => document.getElementById(id);
const MV_DRIFT_SEC = 0.1;
let bgMode = params.get("bg") || "none";
let bgPackId = "";
let bgCameraId = "";
let cameraStarting = false;

function mvNeedsSeek(currentTime, playbackT, threshold = MV_DRIFT_SEC) {
  if (playbackT == null || !Number.isFinite(playbackT) || !Number.isFinite(currentTime)) {
    return false;
  }
  return Math.abs(currentTime - playbackT) > threshold;
}

function stopCamera() {
  const el = $("bgCamera");
  const stream = el?.srcObject;
  if (stream && typeof stream.getTracks === "function") {
    stream.getTracks().forEach((t) => t.stop());
  }
  if (el) {
    el.srcObject = null;
    el.hidden = true;
  }
}

function pauseMv() {
  const v = $("bgVideo");
  if (!v) return;
  v.pause();
}

function hideBgLayers() {
  const mv = $("bgVideo");
  const cam = $("bgCamera");
  if (mv) mv.hidden = true;
  if (cam) cam.hidden = true;
}

function loadMv(packId) {
  const v = $("bgVideo");
  if (!v || !packId) return;
  const url = `/api/songs/${encodeURIComponent(packId)}/mv`;
  if (v.dataset.pack !== packId) {
    v.src = url;
    v.dataset.pack = packId;
    v.load();
  }
}

async function ensureCamera(deviceId) {
  const el = $("bgCamera");
  if (!el || !navigator.mediaDevices?.getUserMedia) return;
  if (el.srcObject && bgCameraId === (deviceId || "") && !el.hidden) return;
  if (cameraStarting) return;
  cameraStarting = true;
  stopCamera();
  const video = deviceId ? { deviceId: { exact: deviceId } } : true;
  try {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    }
    el.srcObject = stream;
    el.muted = true;
    el.hidden = false;
    bgCameraId = deviceId || "";
    await el.play().catch(() => {});
  } catch {
    el.hidden = true;
  } finally {
    cameraStarting = false;
  }
}

function syncMvClock(playbackT, running) {
  const v = $("bgVideo");
  if (!v || bgMode !== "mv" || v.hidden) return;
  if (!running) {
    pauseMv();
    return;
  }
  const play = v.play();
  if (play) play.catch(() => {});
  if (mvNeedsSeek(v.currentTime, playbackT)) {
    try {
      v.currentTime = playbackT;
    } catch {
      /* not seekable yet */
    }
  }
}

async function applyBg(bg, running) {
  if (document.body.classList.contains("transparent")) {
    hideBgLayers();
    stopCamera();
    pauseMv();
    bgMode = "none";
    return;
  }
  const mode = (bg && bg.mode) || "none";
  const packId = (bg && bg.pack_id) || bgPackId;
  const cameraId = (bg && bg.camera_id) || "";
  bgMode = mode;
  if (packId) bgPackId = packId;

  const mv = $("bgVideo");
  const cam = $("bgCamera");
  if (mode === "mv" && (bg?.has_mv !== false) && packId) {
    stopCamera();
    if (cam) cam.hidden = true;
    loadMv(packId);
    if (mv) mv.hidden = false;
    if (running) {
      mv?.play()?.catch(() => {});
    } else {
      pauseMv();
    }
    return;
  }
  if (mode === "camera") {
    pauseMv();
    if (mv) mv.hidden = true;
    await ensureCamera(cameraId);
    return;
  }
  pauseMv();
  stopCamera();
  hideBgLayers();
}

const NOW_X_RATIO = 0.4;
const LANE_H = 224;
const NOTE_H = 24;
const PX_PER_SEC = 160;
const TRAIL_WINDOW_SEC = 1.6;
/** |cents| under this while on the note counts as a hit sample */
const HIT_CENTS = 50;
const MIDI_PAD = 2;
const MIDI_MIN_SPAN = 12;

/** @type {{ id: number, start: number, dur: number, midi: number, el: HTMLDivElement, hitSamples: number, missSamples: number, verdict: null | "hit" | "miss" }[]} */
let notePool = [];
let noteId = 0;
let songStartedAt = performance.now();
let timerTotalSec = 0;
let lyricChars = [];
let lyricProgress = 0;
/** @type {{ t: number, midi: number }[]} */
let pitchTrail = [];
let midiLo = 48;
let midiHi = 72;

function setBadges(active) {
  document.querySelectorAll(".badge").forEach((el) => {
    el.classList.toggle("on", active.includes(el.dataset.kind));
  });
}

function hzToMidi(hz) {
  const f = Number(hz);
  if (!Number.isFinite(f) || f <= 0) return null;
  return 69 + 12 * Math.log2(f / 440);
}

function setMidiRange(notes) {
  const midis = (notes || [])
    .map((n) => Number(n.midi ?? n))
    .filter((m) => Number.isFinite(m));
  if (!midis.length) {
    midiLo = 48;
    midiHi = 72;
    return;
  }
  let lo = Math.min(...midis);
  let hi = Math.max(...midis);
  lo -= MIDI_PAD;
  hi += MIDI_PAD;
  if (hi - lo < MIDI_MIN_SPAN) {
    const mid = (lo + hi) / 2;
    lo = mid - MIDI_MIN_SPAN / 2;
    hi = mid + MIDI_MIN_SPAN / 2;
  }
  midiLo = lo;
  midiHi = hi;
}

function midiToY(midi) {
  const span = Math.max(1, midiHi - midiLo);
  const t = (Number(midi) - midiLo) / span;
  const pct = 1 - Math.max(0, Math.min(1, t));
  return 12 + pct * (LANE_H - 40);
}

function midiToCenterY(midi) {
  return midiToY(midi) + NOTE_H / 2;
}

function midiToTopPct(midi) {
  return (midiToCenterY(midi) / LANE_H) * 100;
}

function sungMidiFromState(state) {
  const fromHz = hzToMidi(state.f0);
  if (fromHz != null) return fromHz;
  const expected = hzToMidi(state.expected_hz);
  if (expected != null && Number.isFinite(state.cents)) {
    return expected + Number(state.cents) / 100;
  }
  if (Number.isFinite(state.cents)) {
    // Preview / cents-only fallback: keep motion around mid lane.
    return (midiLo + midiHi) / 2 + Number(state.cents) / 100;
  }
  return null;
}

function setPitchMidi(midi, cents) {
  if (!Number.isFinite(midi)) return;
  const top = midiToTopPct(midi);
  const sung = $("sungBar");
  if (sung) sung.style.top = `${top}%`;
  const playhead = $("playhead");
  if (playhead) playhead.style.top = `${top}%`;
  const onPitch = Number.isFinite(cents) ? Math.abs(cents) < 35 : false;
  $("hitStar")?.classList.toggle("on", onPitch);
}

/** @deprecated cents-centered path — kept for any external callers */
function setPitch(cents) {
  const midi = (midiLo + midiHi) / 2 + Number(cents) / 100;
  setPitchMidi(midi, cents);
}

function clearPitchTrail() {
  pitchTrail = [];
  const canvas = $("pitchTrail");
  const ctx = canvas?.getContext("2d");
  if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function recordPitchTrail(nowSec, midi) {
  if (!Number.isFinite(nowSec)) return;
  if (Number.isFinite(midi)) {
    pitchTrail.push({ t: Number(nowSec), midi: Number(midi) });
  }
  const cutoff = Number(nowSec) - TRAIL_WINDOW_SEC;
  while (pitchTrail.length && pitchTrail[0].t < cutoff) pitchTrail.shift();
}

function sizeTrailCanvas(canvas) {
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  const pixelW = Math.round(width * ratio);
  const pixelH = Math.round(height * ratio);
  if (canvas.width !== pixelW || canvas.height !== pixelH) {
    canvas.width = pixelW;
    canvas.height = pixelH;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width, height };
}

function drawPitchTrail(nowSec) {
  const canvas = $("pitchTrail");
  if (!canvas || !Number.isFinite(nowSec)) return;
  const { ctx, width, height } = sizeTrailCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  if (pitchTrail.length < 2) return;

  const nowX = width * NOW_X_RATIO;
  const gradient = ctx.createLinearGradient(
    Math.max(0, nowX - TRAIL_WINDOW_SEC * PX_PER_SEC),
    0,
    nowX,
    0,
  );
  gradient.addColorStop(0, "rgba(94, 240, 255, 0)");
  gradient.addColorStop(0.22, "rgba(94, 240, 255, 0.35)");
  gradient.addColorStop(1, "rgba(94, 240, 255, 0.95)");

  ctx.strokeStyle = gradient;
  ctx.lineWidth = 8;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.shadowColor = "rgba(94, 240, 255, 0.75)";
  ctx.shadowBlur = 12;

  const yScale = height / LANE_H;
  let drawing = false;
  let previousT = null;
  for (const sample of pitchTrail) {
    const age = Number(nowSec) - sample.t;
    const x = nowX - age * PX_PER_SEC;
    const y = midiToCenterY(sample.midi) * yScale;
    if (x < 0 || x > nowX + 2) continue;
    if (!drawing || previousT == null || sample.t - previousT > 0.22) {
      if (drawing) ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x, y);
      drawing = true;
    } else {
      ctx.lineTo(x, y);
    }
    previousT = sample.t;
  }
  if (drawing) ctx.stroke();
}

function paintHpBar(barId, valId, n) {
  const v = Math.max(0, Math.min(100, Number(n) || 0));
  const el = $(barId);
  if (!el) return;
  el.style.width = `${v}%`;
  el.classList.toggle("mid", v <= 40 && v > 15);
  el.classList.toggle("low", v <= 15);
  const val = $(valId);
  if (val) val.textContent = String(Math.round(v));
}

function setHP(pitch, rhythm) {
  paintHpBar("mPitch", "hpPitchVal", pitch);
  paintHpBar("mRhythm", "hpRhythmVal", rhythm);
}

function setFail(failed, reason) {
  const banner = $("failBanner");
  if (!banner) return;
  if (!failed) {
    banner.hidden = true;
    return;
  }
  setSuccess(null);
  banner.hidden = false;
  $("failReason").textContent = reason === "rhythm" ? "拍子 HP 0" : "音準 HP 0";
}

function setSuccess(result) {
  const banner = $("successBanner");
  const stage = $("stage");
  if (!banner) return;
  if (!result || result.outcome !== "clear") {
    banner.hidden = true;
    if (stage) stage.classList.remove("clear-result");
    return;
  }
  const fail = $("failBanner");
  if (fail) fail.hidden = true;
  banner.hidden = false;
  if (stage) stage.classList.add("clear-result");
  const stars = Number(result.stars) || 0;
  $("successStars").textContent = stars ? "★".repeat(stars) : "";
  $("successTitle").textContent = result.title || "";
  $("successSinger").textContent = result.singer || "—";
  $("successScore").textContent = Number(result.score).toFixed(1);
  $("successHpPitch").textContent = String(result.hp?.pitch ?? "—");
  $("successHpRhythm").textContent = String(result.hp?.rhythm ?? "—");
  $("successPitch").textContent = String(result.pitch ?? "—");
  $("successRhythm").textContent = String(result.rhythm ?? "—");
  $("successStable").textContent = String(result.stable ?? "—");
  $("successDiff").textContent = String(result.difficulty || "normal").toUpperCase();
}

function setStable(stable) {
  const el = $("mStable");
  if (el) el.style.width = `${Math.max(8, Math.min(100, stable))}%`;
}

function formatTimer(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function setTimer(remainingSec) {
  $("timer").textContent = formatTimer(remainingSec);
}

function setLyricLine(text, progress) {
  const el = $("lyricNow");
  const str = text || "";
  lyricChars = [...str];
  if (!str) {
    el.className = "lyric-line";
    el.textContent = "";
    el.style.removeProperty("--ktv-p");
    return;
  }

  const esc = (s) =>
    s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  // Rebuild DOM only when the line text changes (wipe updates via CSS var).
  if (el.dataset.ktvText !== str) {
    el.dataset.ktvText = str;
    el.className = "lyric-line ktv";
    el.innerHTML =
      `<span class="ktv-base">${esc(str)}</span>` +
      `<span class="ktv-fill" aria-hidden="true">${esc(str)}</span>`;
  } else {
    el.classList.add("ktv");
  }

  if (progress == null || Number.isNaN(progress)) {
    lyricProgress = 0;
    el.classList.add("is-plain");
    el.style.setProperty("--ktv-p", "0");
    return;
  }

  lyricProgress = Math.max(0, Math.min(1, Number(progress)));
  el.classList.remove("is-plain");
  el.style.setProperty("--ktv-p", String(lyricProgress));
}

function clearNotes() {
  notePool.forEach((n) => n.el.remove());
  notePool = [];
}

function spawnNote(startSec, durSec, midi) {
  const el = document.createElement("div");
  el.className = "note-bar";
  el.style.height = `${NOTE_H}px`;
  el.style.width = `${Math.max(24, durSec * PX_PER_SEC)}px`;
  el.style.top = `${midiToY(midi)}px`;
  $("notesLayer").appendChild(el);
  const note = {
    id: ++noteId,
    start: startSec,
    dur: durSec,
    midi,
    el,
    hitSamples: 0,
    missSamples: 0,
    verdict: null,
  };
  notePool.push(note);
  return note;
}

function paintNoteVerdict(n) {
  n.el.classList.toggle("hit", n.verdict === "hit");
  n.el.classList.toggle("miss", n.verdict === "miss");
}

function gradeNotes(nowSec, state) {
  const cents = state.cents;
  const voiced = cents != null && Number.isFinite(cents);
  const inTune = voiced && Math.abs(cents) < HIT_CENTS;

  for (const n of notePool) {
    if (n.verdict) continue;
    const end = n.start + n.dur;
    const active = nowSec >= n.start && nowSec <= end;
    n.el.classList.toggle("active", active);
    if (active && voiced) {
      if (inTune) n.hitSamples += 1;
      else n.missSamples += 1;
    }
    if (nowSec > end) {
      const total = n.hitSamples + n.missSamples;
      n.verdict = total === 0 ? "miss" : n.hitSamples >= n.missSamples ? "hit" : "miss";
      n.el.classList.remove("active");
      paintNoteVerdict(n);
    }
  }
}

function syncNotes(nowSec) {
  const lane = $("pitchLane");
  const laneW = lane?.clientWidth || 1400;
  const nowX = laneW * NOW_X_RATIO;
  for (const n of notePool) {
    const startX = nowX + (n.start - nowSec) * PX_PER_SEC;
    const endX = startX + n.dur * PX_PER_SEC;
    n.el.style.transform = `translateX(${startX}px)`;
    const visible = endX > -40 && startX < laneW + 40;
    n.el.style.display = visible ? "block" : "none";
  }
}

function seedDemoMelody(fromSec = 0) {
  clearNotes();
  const pattern = [60, 62, 64, 65, 67, 65, 64, 62, 60, 59, 57, 55, 57, 59, 60, 64];
  const planned = [];
  let t = fromSec;
  for (let i = 0; i < 48; i++) {
    const midi = pattern[i % pattern.length] + (i % 7 === 0 ? 5 : 0);
    const dur = 0.28 + (i % 3) * 0.12;
    planned.push({ t, dur, midi });
    t += dur + (i % 4 === 3 ? 0.22 : 0.05);
  }
  setMidiRange(planned);
  for (const n of planned) spawnNote(n.t, n.dur, n.midi);
}

function applyState(state) {
  if (state.title) $("songTitle").textContent = state.title;
  if (state.singer != null) $("singerName").textContent = state.singer || "—";
  if (state.score != null) $("score").textContent = Number(state.score).toFixed(1);
  if (state.lyricNow != null) {
    setLyricLine(state.lyricNow, state.lyricProgress);
  }
  if (state.lyricNext != null) {
    const nextEl = $("lyricNext");
    if (nextEl) nextEl.textContent = state.lyricNext;
  }
  setBadges(state.badges || []);
  const sungMidi = sungMidiFromState(state);
  if (sungMidi != null) setPitchMidi(sungMidi, state.cents);
  if (state.hp) setHP(state.hp.pitch, state.hp.rhythm);
  if (state.stable != null) setStable(state.stable);
  setFail(Boolean(state.failed), state.fail_reason);
  if (state.remaining != null) setTimer(state.remaining);
  if (state.bg) applyBg(state.bg, Boolean(state.running) && !state.failed && !state.cleared);
  const playbackT = state.playback_t;
  if (playbackT != null) {
    syncMvClock(playbackT, Boolean(state.running) && !state.failed);
  }
  if (state.nowSec != null) {
    recordPitchTrail(state.nowSec, sungMidi);
    drawPitchTrail(state.nowSec);
    gradeNotes(state.nowSec, state);
    syncNotes(state.nowSec);
  }
}

window.KaraokOverlay = {
  applyState,
  applyBg,
  mvNeedsSeek,
  setBadges,
  setPitch,
  setPitchMidi,
  setMidiRange,
  hzToMidi,
  setHP,
  setFail,
  setTimer,
  setLyricLine,
  spawnNote,
  clearNotes,
  seedDemoMelody,
  syncNotes,
};

if (preview) {
  const lines = [
    "夜空に歌が流れて",
    "Keep the tempo hold it",
    "拍子跟住音準唔好掉",
    "星が聴いているよ",
  ];
  let lineIdx = 0;
  let progress = 0;
  timerTotalSec = 95;
  songStartedAt = performance.now();
  seedDemoMelody(0);

  let hpPitch = 100;
  let hpRhythm = 100;
  let failed = false;
  let failHoldUntil = 0;
  let lastTick = performance.now();

  function tick() {
    const now = performance.now();
    const dt = Math.min(0.05, (now - lastTick) / 1000);
    lastTick = now;
    const elapsed = (now - songStartedAt) / 1000;
    const remaining = Math.max(0, timerTotalSec - elapsed);
    const cents = Math.sin(now / 420) * 80;
    const late = cents < -50;
    const sharp = cents > 55;
    // Demo absolute pitch wanders across the fitted MIDI lane.
    const demoMidi = 60 + Math.sin(now / 900) * 8 + cents / 100;
    const demoHz = 440 * 2 ** ((demoMidi - 69) / 12);
    progress += 0.012;
    if (progress >= 1) {
      progress = 0;
      lineIdx = (lineIdx + 1) % lines.length;
    }
    const last = notePool[notePool.length - 1];
    if (last && elapsed > last.start + last.dur - 2) {
      seedDemoMelody(elapsed + 0.3);
    }
    if (failed) {
      if (now >= failHoldUntil) {
        failed = false;
        hpPitch = 100;
        hpRhythm = 100;
      }
    } else {
      if (sharp) hpPitch = Math.max(0, hpPitch - 10 * dt);
      if (late) hpRhythm = Math.max(0, hpRhythm - 10 * dt);
      if (hpPitch <= 0 || hpRhythm <= 0) {
        failed = true;
        failHoldUntil = now + 2500;
      }
    }
    applyState({
      title: "PREVIEW MODE",
      singer: "DEMO",
      score: 92.4 + Math.sin(now / 900),
      lyricNow: lines[lineIdx],
      lyricNext: lines[(lineIdx + 1) % lines.length],
      lyricProgress: progress,
      badges: [late ? "late" : "", sharp ? "sharp" : ""].filter(Boolean),
      cents,
      f0: demoHz,
      expected_hz: 440 * 2 ** ((60 - 69) / 12),
      hp: { pitch: hpPitch, rhythm: hpRhythm },
      failed,
      fail_reason: hpPitch <= 0 ? "pitch" : hpRhythm <= 0 ? "rhythm" : null,
      stable: 70,
      remaining,
      nowSec: elapsed,
    });
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

if (!preview) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "chart") {
      clearNotes();
      clearPitchTrail();
      setMidiRange(msg.notes || []);
      (msg.notes || []).forEach((n) => spawnNote(n.t, n.duration, n.midi || 60));
      if (msg.title) $("songTitle").textContent = msg.title;
      if (msg.singer != null) $("singerName").textContent = msg.singer || "—";
      setHP(100, 100);
      setFail(false);
      setSuccess(null);
      if (msg.pack_id) bgPackId = msg.pack_id;
      applyBg(msg.bg || { mode: "mv", pack_id: msg.pack_id, has_mv: msg.has_mv }, true);
      return;
    }
    if (msg.type === "idle") {
      clearPitchTrail();
      setFail(false);
      setSuccess(null);
      applyBg(msg.bg || { mode: bgMode, pack_id: bgPackId }, false);
      pauseMv();
      return;
    }
    if (msg.type === "result") {
      clearPitchTrail();
      setSuccess(msg);
      applyBg(msg.bg || { mode: bgMode, pack_id: bgPackId }, false);
      pauseMv();
      return;
    }
    if (msg.type === "frame") {
      applyState(msg);
    }
  };
}
