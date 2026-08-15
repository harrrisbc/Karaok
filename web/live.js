const packEl = document.getElementById("pack");
const singerEl = document.getElementById("singer");
const inputEl = document.getElementById("input");
const outputEl = document.getElementById("output");
const channelEl = document.getElementById("channel");
const trimEl = document.getElementById("trim");
const trimVal = document.getElementById("trimVal");
const vocalMixEl = document.getElementById("vocalMix");
const vocalMixVal = document.getElementById("vocalMixVal");
const difficultyEl = document.getElementById("difficulty");
const pitchThreshEl = document.getElementById("pitchThresh");
const pitchThreshVal = document.getElementById("pitchThreshVal");
const tempoThreshEl = document.getElementById("tempoThresh");
const tempoThreshVal = document.getElementById("tempoThreshVal");
const bgModeEl = document.getElementById("bgMode");
const bgCameraEl = document.getElementById("bgCamera");
const bgCamWrap = document.getElementById("bgCamWrap");
const diffHint = document.getElementById("diffHint");
const healBtn = document.getElementById("healHp");
const godModeEl = document.getElementById("godMode");
const fohMs = document.getElementById("fohMs");
const lat = document.getElementById("lat");
const startBtn = document.getElementById("start");
const calibrateBtn = document.getElementById("calibrate");
const calibrationEl = document.getElementById("calibration");

const DIFF_PRESETS = {
  easy: { cents: 80, tempoMs: 150, drain: 6 },
  normal: { cents: 50, tempoMs: 90, drain: 10 },
  hard: { cents: 35, tempoMs: 60, drain: 14 },
  expert: { cents: 25, tempoMs: 45, drain: 18 },
};

function setPitchThresh(cents) {
  const v = Math.max(15, Math.min(120, Math.round(Number(cents) || 50)));
  pitchThreshEl.value = String(v);
  pitchThreshVal.textContent = `±${v}¢`;
}

function setTempoThresh(ms) {
  const v = Math.max(30, Math.min(250, Math.round(Number(ms) || 90)));
  tempoThreshEl.value = String(v);
  tempoThreshVal.textContent = `±${v} ms`;
}

function updateDiffHint() {
  const preset = DIFF_PRESETS[difficultyEl.value] || DIFF_PRESETS.normal;
  diffHint.textContent = `Pitch ±${pitchThreshEl.value}¢ · Tempo ±${tempoThreshEl.value} ms · drain ${preset.drain} HP/s (from ${difficultyEl.value} preset).`;
}

function applyPresetToSliders() {
  const preset = DIFF_PRESETS[difficultyEl.value] || DIFF_PRESETS.normal;
  setPitchThresh(preset.cents);
  setTempoThresh(preset.tempoMs);
  updateDiffHint();
}
function setTrim(value) {
  const trim = Math.max(-80, Math.min(80, Number(value) || 0));
  trimEl.value = String(trim);
  trimVal.textContent = String(trim);
}

function savePrefs() {
  localStorage.setItem(
    "karaok-live",
    JSON.stringify({
      input: inputEl.value,
      output: outputEl.value,
      channel: channelEl.value,
      pack: packEl.value,
      singer: singerEl.value,
      vocalMix: vocalMixEl.value,
      difficulty: difficultyEl.value,
      pitchThresh: pitchThreshEl.value,
      tempoThresh: tempoThreshEl.value,
      bgMode: bgModeEl.value,
      bgCamera: bgCameraEl.value,
    }),
  );
}

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem("karaok-live") || "{}");
  } catch {
    return {};
  }
}

async function jsonFetch(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function applyStatus(s) {
  startBtn.disabled = Boolean(s.running || s.calibrating);
  calibrateBtn.disabled = Boolean(s.running || s.calibrating);
  if (s.failed) {
    fohMs.textContent = "FAILED";
    lat.textContent = s.frame?.fail_reason === "rhythm" ? "拍子 HP 0 — playback stopped" : "音準 HP 0 — playback stopped";
    return;
  }
  if (s.cleared) {
    const score = s.frame?.score;
    fohMs.textContent = "CLEAR";
    lat.textContent = `CLEAR · score ${score != null ? Number(score).toFixed(1) : "—"} · ${s.difficulty || "normal"}`;
    return;
  }
  const out = s.output_ms ?? s.foh_vocal_delay_ms;
  if (out != null && s.running) {
    fohMs.textContent = `${Number(out).toFixed(1)} ms`;
  } else {
    fohMs.textContent = "— ms";
  }
  if (godModeEl && typeof s.god_mode === "boolean") {
    godModeEl.checked = s.god_mode;
  }
  const godTag = s.god_mode ? " · GOD" : "";
  lat.textContent = s.running
    ? `input ${Number(s.input_ms).toFixed(1)} ms · output ${Number(s.output_ms).toFixed(1)} ms · trim ${s.trim_ms} · guide ${Math.round((s.vocal_mix || 0) * 100)}% · pitch ±${s.cents_limit ?? pitchThreshEl.value}¢ · tempo ±${Math.round((s.timing_limit ?? Number(tempoThreshEl.value) / 1000) * 1000)} ms · HP ${s.frame?.hp?.pitch ?? "—"}/${s.frame?.hp?.rhythm ?? "—"} · bg ${s.bg?.mode || "none"}${godTag}`
    : `stopped — pick devices, then Start${godTag}`;
  if (s.cents_limit != null && document.activeElement !== pitchThreshEl) {
    setPitchThresh(s.cents_limit);
  }
  if (s.timing_limit != null && document.activeElement !== tempoThreshEl) {
    setTempoThresh(Math.round(Number(s.timing_limit) * 1000));
  }
  updateDiffHint();
  if (s.bg?.mode && document.activeElement !== bgModeEl) {
    if (bgModeEl.value !== s.bg.mode) bgModeEl.value = s.bg.mode;
    updateBgUi();
  }
  if (s.difficulty && difficultyEl.value !== s.difficulty) {
    /* keep operator selection unless server reports mid-take change elsewhere */
  }
}

async function loadDevices() {
  const data = await jsonFetch("/api/devices");
  const prefs = loadPrefs();
  const ins = data.devices.filter((d) => d.max_input_channels > 0);
  const outs = data.devices.filter((d) => d.max_output_channels > 0);
  inputEl.innerHTML = ins
    .map(
      (d) =>
        `<option value="${d.index}">[${d.index}] ${d.hostapi} — ${d.name} (in ${d.max_input_channels})</option>`,
    )
    .join("");
  outputEl.innerHTML = outs
    .map(
      (d) =>
        `<option value="${d.index}">[${d.index}] ${d.hostapi} — ${d.name} (out ${d.max_output_channels})</option>`,
    )
    .join("");
  if (prefs.input) inputEl.value = prefs.input;
  else if (data.default_input != null) inputEl.value = String(data.default_input);
  if (prefs.output) outputEl.value = prefs.output;
  else if (data.default_output != null) outputEl.value = String(data.default_output);
  if (prefs.channel) channelEl.value = prefs.channel;
  if (prefs.vocalMix != null) vocalMixEl.value = prefs.vocalMix;
  if (prefs.difficulty) difficultyEl.value = prefs.difficulty;
  if (prefs.pitchThresh != null || prefs.tempoThresh != null) {
    setPitchThresh(prefs.pitchThresh ?? pitchThreshEl.value);
    setTempoThresh(prefs.tempoThresh ?? tempoThreshEl.value);
  } else {
    applyPresetToSliders();
  }
  if (localStorage.getItem("karaok-trim-ms") != null) {
    setTrim(localStorage.getItem("karaok-trim-ms"));
  }
  vocalMixVal.textContent = `${vocalMixEl.value}%`;
  updateDiffHint();
}

async function loadPacks() {
  const data = await jsonFetch("/api/songs");
  const ready = data.songs.filter((s) => s.has_instrumental);
  packEl.innerHTML = ready.length
    ? ready
        .map(
          (s) =>
            `<option value="${s.id}" data-singer="${s.singer || ""}" data-has-mv="${s.has_mv ? "1" : "0"}">${s.title}${s.has_mv ? " · MV" : ""}</option>`,
        )
        .join("")
    : `<option value="">No packs with instrumental</option>`;
  const prefs = loadPrefs();
  if (prefs.pack) packEl.value = prefs.pack;
  fillSingerFromPack(prefs.singer);
  if (prefs.bgMode) bgModeEl.value = prefs.bgMode;
  updateBgUi();
}

function fillSingerFromPack(prefSinger) {
  const opt = packEl.selectedOptions[0];
  const fromPack = opt?.getAttribute("data-singer") || "";
  singerEl.value = prefSinger || fromPack;
}

packEl.addEventListener("change", () => {
  fillSingerFromPack("");
  updateBgUi();
  pushBg();
});
bgModeEl.addEventListener("change", () => pushBg());
bgCameraEl.addEventListener("change", () => pushBg());

function selectedHasMv() {
  return packEl.selectedOptions[0]?.getAttribute("data-has-mv") === "1";
}

function updateBgUi() {
  const hasMv = selectedHasMv();
  const mvOpt = bgModeEl.querySelector('option[value="mv"]');
  if (mvOpt) mvOpt.disabled = !hasMv;
  if (!hasMv && bgModeEl.value === "mv") bgModeEl.value = "none";
  bgCamWrap.hidden = bgModeEl.value !== "camera";
}

async function pushBg() {
  updateBgUi();
  savePrefs();
  try {
    applyStatus(
      await jsonFetch("/api/live/bg", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: bgModeEl.value,
          camera_id: bgCameraEl.value || "",
        }),
      }),
    );
  } catch {
    /* idle */
  }
}

async function loadCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cams = devices.filter((d) => d.kind === "videoinput");
    bgCameraEl.innerHTML = cams.length
      ? cams
          .map(
            (d) =>
              `<option value="${d.deviceId}">${d.label || "Camera"} </option>`,
          )
          .join("")
      : `<option value="">No camera (grant permission on /show)</option>`;
    const prefs = loadPrefs();
    if (prefs.bgCamera) bgCameraEl.value = prefs.bgCamera;
  } catch {
    bgCameraEl.innerHTML = `<option value="">Camera list unavailable</option>`;
  }
}

startBtn.addEventListener("click", async () => {
  savePrefs();
  const body = {
    pack_id: packEl.value,
    input_device: Number(inputEl.value),
    output_device: Number(outputEl.value),
    input_channel: Number(channelEl.value || 0),
    trim_ms: Number(trimEl.value),
    vocal_mix: Number(vocalMixEl.value || 0) / 100,
    difficulty: difficultyEl.value || "normal",
    cents_limit: Number(pitchThreshEl.value),
    timing_limit_ms: Number(tempoThreshEl.value),
    singer: singerEl.value.trim(),
  };
  try {
    const status = await jsonFetch("/api/live/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    applyStatus(status);
  } catch (err) {
    lat.textContent = String(err.message || err);
  }
});

document.getElementById("stop").addEventListener("click", async () => {
  applyStatus(await jsonFetch("/api/live/stop", { method: "POST" }));
});

calibrateBtn.addEventListener("click", async () => {
  calibrateBtn.disabled = true;
  calibrationEl.hidden = false;
  calibrationEl.textContent = "Playing click… keep the mic pointed at the speaker.";
  try {
    const result = await jsonFetch("/api/live/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input_device: Number(inputEl.value),
        output_device: Number(outputEl.value),
        input_channel: Number(channelEl.value || 0),
      }),
    });
    if (!result.ok) {
      calibrationEl.textContent =
        result.error === "weak_signal"
          ? "Mic 冇收到 click。開大喇叭、對準 mic，或者檢查 input device。"
          : result.message || "Calibration failed.";
      return;
    }
    calibrationEl.textContent = `${result.message} `;
    const apply = document.createElement("button");
    apply.type = "button";
    apply.textContent = "Apply";
    apply.addEventListener("click", async () => {
      setTrim(result.proposed_trim_ms);
      const status = await jsonFetch("/api/live/trim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trim_ms: Number(trimEl.value) }),
      });
      localStorage.setItem("karaok-trim-ms", trimEl.value);
      calibrationEl.textContent = `Applied trim ${trimEl.value} ms.`;
      applyStatus(status);
    });
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.addEventListener("click", () => {
      calibrationEl.hidden = true;
      calibrationEl.textContent = "";
    });
    calibrationEl.append(apply, dismiss);
  } catch (err) {
    calibrationEl.textContent = String(err.message || err);
  } finally {
    calibrateBtn.disabled = false;
  }
});

trimEl.addEventListener("input", () => {
  trimVal.textContent = trimEl.value;
});
trimEl.addEventListener("change", async () => {
  trimVal.textContent = trimEl.value;
  try {
    applyStatus(
      await jsonFetch("/api/live/trim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trim_ms: Number(trimEl.value) }),
      }),
    );
  } catch {
    /* idle */
  }
});

async function pushVocalMix() {
  vocalMixVal.textContent = `${vocalMixEl.value}%`;
  savePrefs();
  try {
    applyStatus(
      await jsonFetch("/api/live/vocal-mix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vocal_mix: Number(vocalMixEl.value || 0) / 100 }),
      }),
    );
  } catch {
    /* idle */
  }
}

vocalMixEl.addEventListener("input", () => {
  vocalMixVal.textContent = `${vocalMixEl.value}%`;
  pushVocalMix();
});

difficultyEl.addEventListener("change", async () => {
  applyPresetToSliders();
  savePrefs();
  try {
    applyStatus(
      await jsonFetch("/api/live/difficulty", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ difficulty: difficultyEl.value }),
      }),
    );
    await pushThresholds();
  } catch {
    /* idle */
  }
});

async function pushThresholds() {
  updateDiffHint();
  savePrefs();
  try {
    applyStatus(
      await jsonFetch("/api/live/thresholds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cents_limit: Number(pitchThreshEl.value),
          timing_limit_ms: Number(tempoThreshEl.value),
        }),
      }),
    );
  } catch {
    /* idle */
  }
}

pitchThreshEl.addEventListener("input", () => {
  setPitchThresh(pitchThreshEl.value);
  updateDiffHint();
});
pitchThreshEl.addEventListener("change", () => {
  setPitchThresh(pitchThreshEl.value);
  pushThresholds();
});
tempoThreshEl.addEventListener("input", () => {
  setTempoThresh(tempoThreshEl.value);
  updateDiffHint();
});
tempoThreshEl.addEventListener("change", () => {
  setTempoThresh(tempoThreshEl.value);
  pushThresholds();
});

healBtn.addEventListener("click", async () => {
  try {
    const status = await jsonFetch("/api/live/heal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: 10 }),
    });
    applyStatus(status);
    const hp = status.healed || status.frame?.hp;
    if (hp) {
      lat.textContent = `${lat.textContent} · healed → ${hp.pitch}/${hp.rhythm}`;
    }
  } catch (err) {
    lat.textContent = String(err.message || err);
  }
});

godModeEl?.addEventListener("change", async () => {
  try {
    const status = await jsonFetch("/api/live/god", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: godModeEl.checked }),
    });
    applyStatus(status);
  } catch (err) {
    godModeEl.checked = !godModeEl.checked;
    lat.textContent = String(err.message || err);
  }
});

async function poll() {
  try {
    applyStatus(await jsonFetch("/api/live/status"));
  } catch {
    /* server down */
  }
  setTimeout(poll, 500);
}

loadDevices().catch((err) => {
  lat.textContent = String(err);
});
loadPacks();
loadCameras();
poll();
jsonFetch("/api/health")
  .then((health) => {
    if (health.preview) document.getElementById("prepLink")?.setAttribute("hidden", "");
  })
  .catch(() => {});
