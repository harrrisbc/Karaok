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
const diffHint = document.getElementById("diffHint");
const healBtn = document.getElementById("healHp");
const fohMs = document.getElementById("fohMs");
const lat = document.getElementById("lat");
const startBtn = document.getElementById("start");
const calibrateBtn = document.getElementById("calibrate");
const calibrationEl = document.getElementById("calibration");

const DIFF_HINTS = {
  easy: "Easy: pitch damage beyond ±80¢; EARLY/LATE ±150 ms; drain 6 HP/s.",
  normal: "Normal: pitch damage beyond ±50¢; EARLY/LATE ±90 ms; drain 10 HP/s.",
  hard: "Hard: pitch damage beyond ±35¢; EARLY/LATE ±60 ms; drain 14 HP/s.",
  expert: "Expert: pitch damage beyond ±25¢; EARLY/LATE ±45 ms; drain 18 HP/s.",
};

function updateDiffHint() {
  diffHint.textContent = DIFF_HINTS[difficultyEl.value] || DIFF_HINTS.normal;
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
  lat.textContent = s.running
    ? `input ${Number(s.input_ms).toFixed(1)} ms · output ${Number(s.output_ms).toFixed(1)} ms · trim ${s.trim_ms} · guide ${Math.round((s.vocal_mix || 0) * 100)}% · ${s.difficulty || "normal"} · HP ${s.frame?.hp?.pitch ?? "—"}/${s.frame?.hp?.rhythm ?? "—"}`
    : "stopped — pick devices, then Start";
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
        .map((s) => `<option value="${s.id}" data-singer="${s.singer || ""}">${s.title} (${s.status})</option>`)
        .join("")
    : `<option value="">No packs with instrumental</option>`;
  const prefs = loadPrefs();
  if (prefs.pack) packEl.value = prefs.pack;
  fillSingerFromPack(prefs.singer);
}

function fillSingerFromPack(prefSinger) {
  const opt = packEl.selectedOptions[0];
  const fromPack = opt?.getAttribute("data-singer") || "";
  singerEl.value = prefSinger || fromPack;
}

packEl.addEventListener("change", () => fillSingerFromPack(""));

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
    singer: singerEl.value.trim(),
  };
  const status = await jsonFetch("/api/live/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  applyStatus(status);
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
  updateDiffHint();
  savePrefs();
  try {
    applyStatus(
      await jsonFetch("/api/live/difficulty", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ difficulty: difficultyEl.value }),
      }),
    );
  } catch {
    /* idle */
  }
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
poll();
jsonFetch("/api/health")
  .then((health) => {
    if (health.preview) document.getElementById("prepLink")?.setAttribute("hidden", "");
  })
  .catch(() => {});
