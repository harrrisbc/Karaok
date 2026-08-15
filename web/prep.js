const healthEl = document.getElementById("health");
const songsEl = document.getElementById("songs");
const jobEl = document.getElementById("job");
const langEl = document.getElementById("lang");
const modelEl = document.getElementById("whisperModel");
const fileForm = document.getElementById("fileForm");
const ytForm = document.getElementById("ytForm");
const fileInput = document.getElementById("file");
const fileNameEl = document.getElementById("fileName");

const JOB_KEY = "karaok-active-job";
const PACK_HANDOFF_KEY = "karaok-latest-pack";
let busy = false;
let pollTimer = null;
let packHandoffChannel = null;
try {
  packHandoffChannel = new BroadcastChannel("karaok-pack-handoff");
} catch {
  packHandoffChannel = null;
}

function publishPackHandoff(packId) {
  if (!packId) return;
  const payload = { packId, ts: Date.now() };
  try {
    localStorage.setItem(PACK_HANDOFF_KEY, JSON.stringify(payload));
  } catch {
    /* ignore quota */
  }
  try {
    packHandoffChannel?.postMessage(payload);
  } catch {
    /* ignore */
  }
}

fileInput?.addEventListener("change", () => {
  const f = fileInput.files?.[0];
  if (fileNameEl) fileNameEl.textContent = f ? f.name : "No file";
});

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
  songsEl.querySelectorAll("[data-lrclib]").forEach((el) => {
    el.disabled = on;
  });
  songsEl.querySelectorAll("[data-lrclib-search]").forEach((el) => {
    el.disabled = on;
  });
  songsEl.querySelectorAll("[data-lrclib-apply]").forEach((el) => {
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

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function splitTitleHint(title) {
  const raw = String(title || "");
  const parts = raw.split(/\s[-–—]\s/);
  if (parts.length >= 2) {
    return { artist: parts[0].trim(), track: parts.slice(1).join(" - ").trim() };
  }
  return { artist: "", track: raw };
}

function formatDuration(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderLrclibHits(packId, data) {
  const panel = songsEl.querySelector(`[data-lrclib-panel="${packId}"]`);
  if (!panel) return;
  const box = panel.querySelector(".results");
  const candidates = data.candidates || [];
  if (data.error) {
    box.innerHTML = `<p class="lrclib-empty err">${escapeHtml(data.error)}</p>`;
    return;
  }
  if (!candidates.length) {
    box.innerHTML = `<p class="lrclib-empty">搵唔到 synced lyrics。試下改 artist / track 再 Search。</p>`;
    return;
  }
  box.innerHTML = candidates
    .map((c) => {
      const delta =
        c.duration_delta == null ? "Δ—" : `Δ${Number(c.duration_delta).toFixed(1)}s`;
      const auto = c.auto_apply ? " · auto" : "";
      return `<div class="lrclib-hit">
        <div>
          <strong>${escapeHtml(c.track_name || "?")}</strong>
          <div class="meta">${escapeHtml(c.artist_name || "—")} · ${escapeHtml(c.album_name || "—")} · ${formatDuration(c.duration)} · ${delta}${auto} · #${c.id}</div>
        </div>
        <div class="actions">
          <button type="button" data-lrclib-apply="${packId}" data-id="${c.id}" data-mode="align" title="用 LRCLIB 正確文字，對齊我哋 vocals（建議）">Align</button>
          <button type="button" class="secondary" data-lrclib-apply="${packId}" data-id="${c.id}" data-mode="trust-lrc" title="直接用 LRCLIB 時間（唔重新對齊）">Use LRC</button>
        </div>
      </div>`;
    })
    .join("");
  box.querySelectorAll("[data-lrclib-apply]").forEach((el) => {
    el.addEventListener("click", () => {
      applyLrclib(
        el.getAttribute("data-lrclib-apply"),
        Number(el.getAttribute("data-id")),
        el.getAttribute("data-mode") || "trust-lrc",
      );
    });
  });
}

async function openLrclibBrowser(packId, song) {
  const panel = songsEl.querySelector(`[data-lrclib-panel="${packId}"]`);
  if (!panel) return;
  const open = panel.hasAttribute("hidden");
  songsEl.querySelectorAll("[data-lrclib-panel]").forEach((el) => el.setAttribute("hidden", ""));
  songsEl.querySelectorAll("[data-lrclib]").forEach((el) => {
    el.classList.remove("btn-active");
    el.setAttribute("aria-expanded", "false");
  });
  if (!open) return;
  panel.removeAttribute("hidden");
  const toggle = songsEl.querySelector(`[data-lrclib="${packId}"]`);
  toggle?.classList.add("btn-active");
  toggle?.setAttribute("aria-expanded", "true");
  const hint = splitTitleHint(song.title);
  const artistEl = panel.querySelector("[data-lrclib-artist]");
  const titleEl = panel.querySelector("[data-lrclib-title]");
  if (artistEl && !artistEl.value) artistEl.value = song.singer || hint.artist || "";
  if (titleEl && !titleEl.value) titleEl.value = hint.track || song.title || "";
  await searchLrclib(packId);
}

async function searchLrclib(packId) {
  const panel = songsEl.querySelector(`[data-lrclib-panel="${packId}"]`);
  if (!panel) return;
  const artist = panel.querySelector("[data-lrclib-artist]")?.value?.trim() || "";
  const title = panel.querySelector("[data-lrclib-title]")?.value?.trim() || "";
  const box = panel.querySelector(".results");
  box.innerHTML = `<p class="lrclib-empty">Searching lrclib.net…</p>`;
  try {
    const qs = new URLSearchParams();
    if (title) qs.set("title", title);
    if (artist) qs.set("artist", artist);
    const data = await jsonFetch(`/api/lyrics/lrclib/search/${encodeURIComponent(packId)}?${qs}`);
    renderLrclibHits(packId, data);
  } catch (err) {
    box.innerHTML = `<p class="lrclib-empty err">${escapeHtml(err.message || err)}</p>`;
  }
}

async function applyLrclib(packId, lrclibId, mode) {
  if (busy) return;
  setBusy(true, `Applying LRCLIB #${lrclibId} (${mode})…`);
  try {
    const job = await jsonFetch(`/api/lyrics/lrclib/apply/${encodeURIComponent(packId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: lrclibId,
        mode,
        force: true,
        whisper_model: selectedModel(),
      }),
    });
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
    songsEl.innerHTML = "<li class=\"song-row\">未有 song pack。Import 一首先。</li>";
    return;
  }
  songsEl.innerHTML = data.songs
    .map((song) => {
      const err = song.error ? `<span class="err">${escapeHtml(song.error)}</span>` : "";
      const lang = song.lyrics_lang || "?";
      const singerVal = escapeHtml(song.singer || "");
      const canAlign = song.has_vocals;
      const lrclibBtn = canAlign
        ? `<button type="button" data-lrclib="${song.id}" aria-expanded="false" ${busy ? "disabled" : ""}>LRCLIB</button>`
        : "";
      const save = `<button type="button" class="secondary" data-save-singer="${song.id}" ${busy ? "disabled" : ""}>Save</button>`;
      const moreActions = canAlign
        ? `<button type="button" class="secondary" data-analyze="${song.id}" ${busy ? "disabled" : ""}>Analyze</button>
           <button type="button" class="secondary" data-whisper="${song.id}" title="Force Whisper ASR" ${busy ? "disabled" : ""}>Retry Whisper</button>
           <button type="button" class="secondary" data-align="${song.id}" ${busy ? "disabled" : ""}>Align .txt</button>
           <input type="file" accept=".txt,text/plain" data-align-file="${song.id}" hidden />
           <button type="button" class="secondary" data-mv="${song.id}" ${busy ? "disabled" : ""}>${song.has_mv ? "Replace MV" : "Attach MV"}</button>
           <input type="file" accept="video/mp4,.mp4" data-mv-file="${song.id}" hidden />`
        : `<button type="button" class="secondary" data-analyze="${song.id}" ${busy ? "disabled" : ""}>Analyze</button>`;
      const hint = splitTitleHint(song.title);
      const lrclibPanel = canAlign
        ? `<div class="lrclib-panel" data-lrclib-panel="${song.id}" hidden>
            <p class="panel-kicker">LRCLIB · Align = 用正確字對齊 vocals（建議）</p>
            <div class="fields">
              <label>Artist
                <input type="text" data-lrclib-artist value="${escapeHtml(song.singer || hint.artist || "")}" maxlength="120" />
              </label>
              <label>Track
                <input type="text" data-lrclib-title value="${escapeHtml(hint.track || song.title || "")}" maxlength="200" />
              </label>
              <button type="button" data-lrclib-search="${song.id}">Search</button>
            </div>
            <div class="results"><p class="lrclib-empty">Search lrclib.net</p></div>
          </div>`
        : "";
      return `<li class="song-row">
        <div class="song-head">
          <div class="song-meta">
            <strong class="song-title">${escapeHtml(song.title)}</strong>
            <span class="song-chips">${assetsLabel(song)} · ${lyricsLabel(song)} · ${lang} · <span class="song-status">${escapeHtml(song.status)}</span></span>
          </div>
          <div class="song-primary">
            ${lrclibBtn}
            <label class="singer-field">
              <input data-singer-input="${song.id}" value="${singerVal}" placeholder="singer" maxlength="120" ${busy ? "disabled" : ""} />
            </label>
            ${save}
            <details class="song-more">
              <summary>More</summary>
              <div class="song-more-actions">${moreActions}</div>
            </details>
          </div>
        </div>
        ${lrclibPanel}
        ${err}
      </li>`;
    })
    .join("");

  const songById = Object.fromEntries(data.songs.map((s) => [s.id, s]));

  songsEl.querySelectorAll("[data-analyze]").forEach((el) => {
    el.addEventListener("click", () => analyzePack(el.getAttribute("data-analyze")));
  });
  songsEl.querySelectorAll("[data-whisper]").forEach((el) => {
    el.addEventListener("click", () => retryWhisper(el.getAttribute("data-whisper")));
  });
  songsEl.querySelectorAll("[data-lrclib]").forEach((el) => {
    el.addEventListener("click", () => {
      if (busy) return;
      const id = el.getAttribute("data-lrclib");
      openLrclibBrowser(id, songById[id] || { title: "", singer: "" });
    });
  });
  songsEl.querySelectorAll("[data-lrclib-search]").forEach((el) => {
    el.addEventListener("click", () => {
      if (busy) return;
      searchLrclib(el.getAttribute("data-lrclib-search"));
    });
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
      if (job.status === "done" && job.pack_id) {
        publishPackHandoff(job.pack_id);
      }
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
