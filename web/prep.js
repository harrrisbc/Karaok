const healthEl = document.getElementById("health");
const songsEl = document.getElementById("songs");
const jobEl = document.getElementById("job");
const langEl = document.getElementById("lang");
const modelEl = document.getElementById("whisperModel");
const fileForm = document.getElementById("fileForm");
const ytForm = document.getElementById("ytForm");

const JOB_KEY = "karaok-active-job";
let busy = false;
let pollTimer = null;

function selectedLang() {
  return langEl.value || "cantonese";
}

function selectedModel() {
  return modelEl.value || "small";
}

function selectedSinger() {
  return (document.getElementById("singer").value || "").trim();
}

async function jsonFetch(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : detail?.msg || res.statusText;
    const err = new Error(msg || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

function setBusy(on, reason = "") {
  busy = on;
  fileForm.querySelector("button").disabled = on;
  ytForm.querySelector("button").disabled = on;
  langEl.disabled = on;
  modelEl.disabled = on;
  songsEl.querySelectorAll("[data-analyze]").forEach((el) => {
    el.disabled = on;
  });
  songsEl.querySelectorAll("[data-whisper]").forEach((el) => {
    el.disabled = on;
  });
  songsEl.querySelectorAll("[data-align]").forEach((el) => {
    el.disabled = on;
  });
  songsEl.querySelectorAll("[data-save-singer]").forEach((el) => {
    el.disabled = on;
  });
  if (on) {
    jobEl.hidden = false;
    if (reason) jobEl.textContent = reason;
  }
}

function assetsLabel(song) {
  const bits = [];
  if (song.has_vocals && song.has_instrumental) bits.push("stems");
  if (song.has_melody) bits.push("melody");
  if (song.has_lyrics) bits.push("lyrics");
  if (song.has_mv) bits.push("mv");
  return bits.length ? bits.join("+") : "empty";
}

function lyricsLabel(song) {
  if (!song.has_lyrics) return "lyrics: —";
  const src = song.lyrics_source;
  const method = song.lyrics_method || "";
  const locked = song.lyrics_locked ? " · locked" : "";
  if (src === "lrclib" || String(method).startsWith("lrclib")) {
    const id = song.lrclib_id != null ? ` #${song.lrclib_id}` : "";
    return `lyrics: LRCLIB${id}${locked}`;
  }
  if (src === "whisper" || method === "openai-whisper") return `lyrics: Whisper${locked}`;
  if (src === "user-txt" || method === "lyric-txt-correct" || method === "stable-ts-align") {
    return `lyrics: txt/align${locked}`;
  }
  if (method) return `lyrics: ${method}${locked}`;
  return `lyrics: yes${locked}`;
}

function formatJob(job) {
  const pack = job.pack_id ? ` · pack ${job.pack_id}` : "";
  const err = job.error ? ` · ${job.error}` : "";
  const last = job.log?.length ? job.log[job.log.length - 1] : "";
  const hint = last && !job.error ? ` · ${String(last).split("\n")[0]}` : "";
  return `${job.status} · ${job.step}${pack}${err}${hint}`;
}

async function loadHealth() {
  try {
    const h = await jsonFetch("/api/health");
    const missing = [];
    if (!h.ffmpeg) missing.push("ffmpeg");
    if (!h.demucs) missing.push("demucs");
    if (!h.melody) missing.push("librosa");
    if (!h.lyrics) missing.push("whisper");
    if (!h.yt_dlp) missing.push("yt-dlp");
    if (!h.js_runtime) missing.push("node/deno (YouTube JS)");
    if (missing.length) {
      healthEl.className = "health bad";
      healthEl.textContent = `缺: ${missing.join(" · ")} · device=${h.device}`;
    } else {
      healthEl.className = "health ok";
      healthEl.textContent = `OK · ffmpeg · demucs · librosa · whisper · yt-dlp · ${h.js_runtime} · device=${h.device}`;
    }
  } catch (err) {
    healthEl.className = "health bad";
    healthEl.textContent = String(err);
  }
}

async function analyzePack(packId) {
  if (busy) return;
  setBusy(true, `starting analyze · ${packId}…`);
  try {
    const body = new FormData();
    body.append("lang", selectedLang());
    body.append("whisper_model", selectedModel());
    const job = await jsonFetch(`/api/jobs/analyze/${packId}`, { method: "POST", body });
    pollJob(job.id);
  } catch (err) {
    setBusy(false);
    jobEl.hidden = false;
    jobEl.textContent = String(err.message || err);
  }
}

async function retryWhisper(packId) {
  if (busy) return;
  setBusy(true, `retry Whisper · ${packId}…`);
  try {
    const body = new FormData();
    body.append("lang", selectedLang());
    body.append("whisper_model", selectedModel());
    const job = await jsonFetch(`/api/jobs/lyrics-whisper/${packId}`, {
      method: "POST",
      body,
    });
    pollJob(job.id);
  } catch (err) {
    setBusy(false);
    jobEl.hidden = false;
    jobEl.textContent = String(err.message || err);
  }
}

async function alignLyrics(packId, file) {
  if (busy) return;
  if (!file) return;
  setBusy(true, `aligning lyrics · ${packId}…`);
  try {
    const body = new FormData();
    body.append("file", file);
    body.append("lang", selectedLang());
    body.append("whisper_model", selectedModel());
    const job = await jsonFetch(`/api/jobs/lyrics-align/${packId}`, { method: "POST", body });
    pollJob(job.id);
  } catch (err) {
    setBusy(false);
    jobEl.hidden = false;
    jobEl.textContent = String(err.message || err);
  }
}

async function loadSongs() {
  const data = await jsonFetch("/api/songs");
  if (!data.songs.length) {
    songsEl.innerHTML = "<li>未有 song pack。Import 一首先。</li>";
    return;
  }
  songsEl.innerHTML = data.songs
    .map((song) => {
      const err = song.error ? `<span class="err">${song.error}</span>` : "";
      const lang = song.lyrics_lang || "?";
      const singer = song.singer
        ? `<input data-singer-input="${song.id}" value="${song.singer}" maxlength="120" ${busy ? "disabled" : ""} />`
        : `<input data-singer-input="${song.id}" placeholder="singer" maxlength="120" ${busy ? "disabled" : ""} />`;
      const canAlign = song.has_vocals;
      const btn = `<button type="button" data-analyze="${song.id}" ${busy ? "disabled" : ""}>Analyze</button>`;
      const whisperBtn = canAlign
        ? `<button type="button" data-whisper="${song.id}" title="Skip LRCLIB, run Whisper ASR" ${busy ? "disabled" : ""}>Retry Whisper</button>`
        : "";
      const align = canAlign
        ? `<button type="button" data-align="${song.id}" ${busy ? "disabled" : ""}>Align lyrics</button>
           <input type="file" accept=".txt,text/plain" data-align-file="${song.id}" hidden />`
        : "";
      const save = `<button type="button" data-save-singer="${song.id}" ${busy ? "disabled" : ""}>Save singer</button>`;
      const mvBtn = `<button type="button" data-mv="${song.id}" ${busy ? "disabled" : ""}>${song.has_mv ? "Replace MV" : "Attach MV"}</button>
           <input type="file" accept="video/mp4,.mp4" data-mv-file="${song.id}" hidden />`;
      return `<li>
        <span>${song.title}</span>
        <span class="status">${song.status} · ${assetsLabel(song)} · ${lyricsLabel(song)} · ${lang}${song.singer ? ` · ${song.singer}` : ""}</span>
        ${singer}
        ${save}
        ${mvBtn}
        ${btn}
        ${whisperBtn}
        ${align}
        ${err}
      </li>`;
    })
    .join("");

  songsEl.querySelectorAll("[data-analyze]").forEach((el) => {
    el.addEventListener("click", () => analyzePack(el.getAttribute("data-analyze")));
  });
  songsEl.querySelectorAll("[data-whisper]").forEach((el) => {
    el.addEventListener("click", () => retryWhisper(el.getAttribute("data-whisper")));
  });
  songsEl.querySelectorAll("[data-align]").forEach((el) => {
    el.addEventListener("click", () => {
      if (busy) return;
      const id = el.getAttribute("data-align");
      const input = songsEl.querySelector(`[data-align-file="${id}"]`);
      input?.click();
    });
  });
  songsEl.querySelectorAll("[data-align-file]").forEach((el) => {
    el.addEventListener("change", () => {
      const id = el.getAttribute("data-align-file");
      const file = el.files?.[0];
      el.value = "";
      if (file) alignLyrics(id, file);
    });
  });
  songsEl.querySelectorAll("[data-save-singer]").forEach((el) => {
    el.addEventListener("click", async () => {
      if (busy) return;
      const id = el.getAttribute("data-save-singer");
      const input = songsEl.querySelector(`[data-singer-input="${id}"]`);
      await jsonFetch(`/api/songs/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ singer: (input?.value || "").trim() }),
      });
      loadSongs();
    });
  });
  songsEl.querySelectorAll("[data-mv]").forEach((el) => {
    el.addEventListener("click", () => {
      if (busy) return;
      const id = el.getAttribute("data-mv");
      songsEl.querySelector(`[data-mv-file="${id}"]`)?.click();
    });
  });
  songsEl.querySelectorAll("[data-mv-file]").forEach((el) => {
    el.addEventListener("change", async () => {
      const id = el.getAttribute("data-mv-file");
      const file = el.files?.[0];
      el.value = "";
      if (!file || !id) return;
      const body = new FormData();
      body.append("file", file);
      try {
        await jsonFetch(`/api/songs/${id}/mv`, { method: "POST", body });
        loadSongs();
      } catch (err) {
        jobEl.hidden = false;
        jobEl.textContent = String(err.message || err);
      }
    });
  });
}

function stopPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function pollJob(id) {
  stopPoll();
  localStorage.setItem(JOB_KEY, id);
  setBusy(true);
  jobEl.hidden = false;

  const tick = async () => {
    try {
      const job = await jsonFetch(`/api/jobs/${id}`);
      jobEl.textContent = formatJob(job);
      if (job.status === "queued" || job.status === "running") {
        // Refresh pack row so status/step feel live without re-enabling buttons.
        loadSongs().catch(() => {});
        pollTimer = setTimeout(tick, 1200);
        return;
      }
      localStorage.removeItem(JOB_KEY);
      setBusy(false);
      await loadSongs();
      await loadHealth();
    } catch (err) {
      jobEl.textContent = `poll error · ${err.message || err}`;
      pollTimer = setTimeout(tick, 2000);
    }
  };
  tick();
}

async function resumeActiveJob() {
  try {
    const data = await jsonFetch("/api/jobs/active");
    if (data.job) {
      pollJob(data.job.id);
      return;
    }
  } catch {
    /* older server */
  }
  const saved = localStorage.getItem(JOB_KEY);
  if (!saved) return;
  try {
    const job = await jsonFetch(`/api/jobs/${saved}`);
    if (job.status === "queued" || job.status === "running") {
      pollJob(saved);
    } else {
      localStorage.removeItem(JOB_KEY);
      jobEl.hidden = false;
      jobEl.textContent = formatJob(job);
    }
  } catch {
    localStorage.removeItem(JOB_KEY);
  }
}

async function startImport(url, body) {
  if (busy) {
    jobEl.hidden = false;
    jobEl.textContent = "已有 job 進行中 — 唔好再撳。等佢完。";
    return;
  }
  setBusy(true, "starting…");
  try {
    const job = await jsonFetch(url, { method: "POST", body });
    pollJob(job.id);
  } catch (err) {
    setBusy(false);
    jobEl.hidden = false;
    jobEl.textContent = String(err.message || err);
  }
}

fileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("file").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  body.append("title", file.name.replace(/\.[^.]+$/, ""));
  body.append("singer", selectedSinger());
  body.append("lang", selectedLang());
  body.append("whisper_model", selectedModel());
  await startImport("/api/jobs/local", body);
});

ytForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData();
  body.append("url", document.getElementById("yt").value.trim());
  body.append("singer", selectedSinger());
  body.append("lang", selectedLang());
  body.append("whisper_model", selectedModel());
  await startImport("/api/jobs/youtube", body);
});

loadHealth();
loadSongs().then(resumeActiveJob);
