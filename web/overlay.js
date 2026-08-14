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

const NOW_X = 118; // matches CSS .now-line left
const LANE_H = 148;
const PX_PER_SEC = 160;
/** |cents| under this while on the note counts as a hit sample */
const HIT_CENTS = 50;

/** @type {{ id: number, start: number, dur: number, midi: number, el: HTMLDivElement, hitSamples: number, missSamples: number, verdict: null | "hit" | "miss" }[]} */
let notePool = [];
let noteId = 0;
let songStartedAt = performance.now();
let timerTotalSec = 0;
let lyricChars = [];
let lyricProgress = 0;

function setBadges(active) {
  document.querySelectorAll(".badge").forEach((el) => {
    el.classList.toggle("on", active.includes(el.dataset.kind));
  });
}

function centsToTop(cents) {
  const clamped = Math.max(-200, Math.min(200, cents));
  return 50 - clamped / 8;
}

function setPitch(cents) {
  const top = centsToTop(cents);
  $("sungBar").style.top = `${top}%`;
  const playhead = $("playhead");
  if (playhead) playhead.style.top = `${top}%`;
  const onPitch = Math.abs(cents) < 35;
  $("hitStar")?.classList.toggle("on", onPitch);
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
  banner.hidden = false;
  $("failReason").textContent = reason === "rhythm" ? "拍子 HP 0" : "音準 HP 0";
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
    el.textContent = "";
    return;
  }
  // No timing yet → plain readable line (white)
  if (progress == null || Number.isNaN(progress)) {
    lyricProgress = 0;
    el.textContent = str;
    return;
  }
  lyricProgress = Math.max(0, Math.min(1, progress));
  const cut = Math.floor(lyricChars.length * lyricProgress);
  el.innerHTML = lyricChars
    .map((ch, i) => {
      const cls = i < cut ? "ch done" : i === cut ? "ch on" : "ch";
      const safe = ch === " " ? "&nbsp;" : ch;
      return `<span class="${cls}">${safe}</span>`;
    })
    .join("");
}

function midiToY(midi) {
  // Map MIDI ~48–72 into lane
  const lo = 48;
  const hi = 72;
  const t = (midi - lo) / (hi - lo);
  const pct = 1 - Math.max(0, Math.min(1, t));
  return 12 + pct * (LANE_H - 40);
}

function clearNotes() {
  notePool.forEach((n) => n.el.remove());
  notePool = [];
}

function spawnNote(startSec, durSec, midi) {
  const el = document.createElement("div");
  el.className = "note-bar";
  el.style.height = "16px";
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
  for (const n of notePool) {
    const startX = NOW_X + (n.start - nowSec) * PX_PER_SEC;
    const endX = startX + n.dur * PX_PER_SEC;
    n.el.style.transform = `translateX(${startX}px)`;
    const visible = endX > -40 && startX < laneW + 40;
    n.el.style.display = visible ? "block" : "none";
  }
}

function seedDemoMelody(fromSec = 0) {
  clearNotes();
  const pattern = [60, 62, 64, 65, 67, 65, 64, 62, 60, 59, 57, 55, 57, 59, 60, 64];
  let t = fromSec;
  for (let i = 0; i < 48; i++) {
    const midi = pattern[i % pattern.length] + (i % 7 === 0 ? 5 : 0);
    const dur = 0.28 + (i % 3) * 0.12;
    spawnNote(t, dur, midi);
    t += dur + (i % 4 === 3 ? 0.22 : 0.05);
  }
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
  if (state.cents != null) setPitch(state.cents);
  if (state.hp) setHP(state.hp.pitch, state.hp.rhythm);
  if (state.stable != null) setStable(state.stable);
  setFail(Boolean(state.failed), state.fail_reason);
  if (state.remaining != null) setTimer(state.remaining);
  if (state.nowSec != null) {
    gradeNotes(state.nowSec, state);
    syncNotes(state.nowSec);
  }
}

window.KaraokOverlay = {
  applyState,
  setBadges,
  setPitch,
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
      (msg.notes || []).forEach((n) => spawnNote(n.t, n.duration, n.midi || 60));
      if (msg.title) $("songTitle").textContent = msg.title;
      if (msg.singer != null) $("singerName").textContent = msg.singer || "—";
      setHP(100, 100);
      setFail(false);
      return;
    }
    if (msg.type === "idle") {
      setFail(false);
      return;
    }
    if (msg.type === "frame") {
      applyState(msg);
    }
  };
}
