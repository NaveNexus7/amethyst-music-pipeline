/**
 * app.js (Renderer)
 * - UI wiring
 * - Playback logic (audio)
 * - Library rendering (search/sort)
 * - Shuffle/Repeat
 * - Visualizer (Web Audio API)
 * - Lucide icon injection (offline)
 */

/* =========================================================
   1) DOM REFERENCES
========================================================= */
const audio = document.getElementById("audio");

const btnPick = document.getElementById("btnPick");
const btnPlay = document.getElementById("btnPlay");
const btnPrev = document.getElementById("btnPrev");
const btnNext = document.getElementById("btnNext");
const btnShuffle = document.getElementById("btnShuffle");
const btnRepeat = document.getElementById("btnRepeat");

const seekBar = document.getElementById("seekBar");
const volBar = document.getElementById("volBar");
const curTimeEl = document.getElementById("curTime");
const durTimeEl = document.getElementById("durTime");

const nowTitle = document.getElementById("nowTitle");
const nowMeta = document.getElementById("nowMeta");
const countEl = document.getElementById("count");
const searchEl = document.getElementById("search");
const sortEl = document.getElementById("sort");
const trackListEl = document.getElementById("trackList");

const lyricsContent = document.getElementById("lyricsContent");
const lyricsStatus = document.getElementById("lyricsStatus");

const albumArtwork = document.getElementById("albumArtwork");
const visualizerEl = document.getElementById("visualizer");

const repeatLabel = document.getElementById("repeatLabel");

/* =========================================================
   2) STATE
========================================================= */
let folderPath = "";
let tracks = [];     // [{id,title,folder,fullPath,filename}]
let order = [];      // indices into tracks
let currentPos = -1; // position in "order" array

let shuffleOn = false;
let repeatMode = "off"; // 'off' | 'one' | 'all'

/* Web Audio (Visualizer) */
let audioCtx = null;
let analyser = null;
let sourceNode = null;
let vizBars = [];
let vizTimer = null;

/* =========================================================
   3) LUCIDE ICON HELPERS (Electron-safe)
   We inject SVG into <span class="iconSlot" data-icon="...">
========================================================= */
function lucideReady() {
  return !!(window.amethyst && typeof window.amethyst.iconSvg === "function");
}

function toSvgSafe(iconName, fallback = "music") {
  const map = window.ICONS || {};
  return map[iconName] || map[fallback] || "";
}

function injectLucideIntoSlots() {
  document.querySelectorAll(".iconSlot").forEach(slot => {
    const name = slot.getAttribute("data-icon");
    if (!name) return;
    const svg = toSvgSafe(name, "music");
    if (svg) slot.innerHTML = svg;
  });
}

function setSlotIcon(slotEl, iconName) {
  if (!slotEl) return;
  slotEl.setAttribute("data-icon", iconName);
  const svg = toSvgSafe(iconName, "music");
  if (svg) slotEl.innerHTML = svg;
}

function setButtonMainIcon(buttonEl, iconName) {
  const slot = buttonEl.querySelector(".iconSlot");
  if (slot) setSlotIcon(slot, iconName);
}

function renderLucideNow() {
  injectLucideIntoSlots();
}

/* =========================================================
   4) UTILITIES
========================================================= */
function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function safeFileUrl(fullPath) {
  const p = fullPath.replaceAll("\\", "/");
  return `file://${p}`;
}

function hashToGradient(seed) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;

  const hue1 = h % 360;
  const hue2 = (hue1 + 40 + (h % 30)) % 360;

  const c1 = `hsl(${hue1}, 50%, 30%)`;
  const c2 = `hsl(${hue2}, 50%, 28%)`;
  const c3 = `hsl(${(hue1 + 320) % 360}, 45%, 24%)`;

  return `linear-gradient(135deg, ${c1}, ${c2}, ${c3})`;
}

function setArtworkForTrack(t) {
  const imageUrl = t?.artworkUrl || t?.youtubeThumbnail || null;
  const img = document.getElementById("artworkImg");
  const placeholder = document.getElementById("artworkPlaceholder");

  if (imageUrl && img) {
    img.src = imageUrl;
    img.style.display = "block";
    if (placeholder) placeholder.style.display = "none";
    albumArtwork.style.background = "linear-gradient(135deg, #2a1853, #1a1030)";
    return;
  }

  // No image — show placeholder
  if (img) img.style.display = "none";
  if (placeholder) placeholder.style.display = "block";
  const seed = `${t?.title || "Amethyst"}-${t?.folder || ""}`;
  albumArtwork.style.background = hashToGradient(seed);
}

/* =========================================================
   5) LIBRARY: ORDER / FILTER / RENDER
========================================================= */
function updateCount() {
  countEl.textContent = `${tracks.length} tracks`;
}

function rebuildOrder() {
  order = tracks.map((_, idx) => idx);

  const mode = sortEl.value;
  if (mode === "name") {
    order.sort((a, b) => tracks[a].title.localeCompare(tracks[b].title));
  } else if (mode === "folder") {
    order.sort((a, b) =>
      (tracks[a].folder || "").localeCompare(tracks[b].folder || "") ||
      tracks[a].title.localeCompare(tracks[b].title)
    );
  }
  // "added" = keep scan order
}

function filteredOrder() {
  const q = (searchEl.value || "").trim().toLowerCase();
  if (!q) return order.slice();

  return order.filter(i => {
    const t = tracks[i];
    return (t.title || "").toLowerCase().includes(q) || (t.folder || "").toLowerCase().includes(q);
  });
}

function renderList() {
  trackListEl.innerHTML = "";
  const visible = filteredOrder();

  for (const idx of visible) {
    const t = tracks[idx];

    const item = document.createElement("div");
    item.className = "trackItem";

    // "active" = current track (even paused), "playing" = active + not paused
    const isActive = currentPos >= 0 && order[currentPos] === idx;
    const isPlaying = isActive && audio.src && !audio.paused;

    if (isActive) item.classList.add("active");
    if (isPlaying) item.classList.add("playing");

    const icon = document.createElement("div");
    icon.className = "trackIcon";
    // Use Lucide music-2 icon (pulse via CSS when playing)
    const svg = toSvgSafe("music-2", "music");
    icon.innerHTML = svg || "♪";

    const content = document.createElement("div");
    content.className = "trackContent";

    const name = document.createElement("div");
    name.className = "trackName";
    name.textContent = t.title;

    const folder = document.createElement("div");
    folder.className = "trackFolder";
    // Show artist if available, otherwise show folder name
    folder.textContent = t.artist || t.folder || "Local folder";

    content.appendChild(name);
    content.appendChild(folder);

    item.appendChild(icon);
    item.appendChild(content);

    item.addEventListener("click", () => {
      const pos = order.indexOf(idx);
      playAt(pos);
    });

    trackListEl.appendChild(item);
  }
  renderLucideNow();
}

/* =========================================================
   6) MODES UI (Shuffle / Repeat / Volume Icon)
========================================================= */
function setModeUI() {
  btnShuffle.classList.toggle("active", shuffleOn);

  btnRepeat.classList.toggle("active", repeatMode !== "off");

  // repeat icon: repeat / repeat-1
  const repeatIconSlot = document.getElementById("repeatIconSlot");
  const iconName = repeatMode === "one" ? "repeat-1" : "repeat";
  setSlotIcon(repeatIconSlot, iconName);

  // label: Off / One / All
  if (repeatLabel) {
    repeatLabel.textContent = repeatMode === "off" ? "Off" : repeatMode === "one" ? "One" : "All";
  }
}

function updateVolumeIcon() {
  const v = audio.volume;
  const slot = document.getElementById("volIconSlot");
  const icon =
    v === 0 ? "volume-x" :
    v < 0.35 ? "volume-1" :
    "volume-2";
  setSlotIcon(slot, icon);
}

/* =========================================================
   7) VISUALIZER (Web Audio API)
========================================================= */
function ensureAudioGraph() {
  if (audioCtx) return;

  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;

  sourceNode = audioCtx.createMediaElementSource(audio);
  sourceNode.connect(analyser);
  analyser.connect(audioCtx.destination);
}

function initVisualizer() {
  visualizerEl.innerHTML = "";
  vizBars = [];

  for (let i = 0; i < 32; i++) {
    const bar = document.createElement("div");
    bar.className = "vbar";
    visualizerEl.appendChild(bar);
    vizBars.push(bar);
  }
}

function startVisualizer() {
  ensureAudioGraph();
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }

  if (!analyser || !vizBars.length) return;

  if (!analyser || !vizBars.length) return;

  if (vizTimer) clearInterval(vizTimer);

  const data = new Uint8Array(analyser.frequencyBinCount);

  vizTimer = setInterval(() => {
    analyser.getByteFrequencyData(data);

    for (let i = 0; i < vizBars.length; i++) {
      const bin = Math.floor((i / vizBars.length) * data.length);
      const v = data[bin] / 255;

      const minH = 0.2;
      const h = minH + v * 0.8;
      vizBars[i].style.height = `${Math.round(h * 100)}%`;

      const opacity = audio.paused ? 0.15 : (0.3 + v * 0.4);
      vizBars[i].style.opacity = String(opacity);
    }
  }, 100);
}

function stopVisualizer() {
  if (vizTimer) clearInterval(vizTimer);
  vizTimer = null;

  for (const b of vizBars) {
    b.style.height = "18%";
    b.style.opacity = "0.15";
  }
}

/* =========================================================
   8) PLAYBACK CORE
========================================================= */
function updatePlayUI() {
  const playing = !!(audio.src && !audio.paused);

  // play/pause icon swap
  const playSlot = document.getElementById("playIconSlot");
  setSlotIcon(playSlot, playing ? "pause" : "play");

  // art pulse + visualizer
  albumArtwork.classList.toggle("playing", playing);
  if (playing) startVisualizer();
  else stopVisualizer();

  renderList();
}

async function loadLyricsForTrack(t) {
  if (!lyricsContent) return;

  lyricsContent.textContent = "♪ Loading lyrics…";
  if (lyricsStatus) lyricsStatus.textContent = "Loading";

  if (!window.amethyst?.getLyrics) {
    lyricsContent.textContent = "Lyrics engine not available.";
    if (lyricsStatus) lyricsStatus.textContent = "Unavailable";
    return;
  }

  // Pass all info — Genius works even without audio file!
  // Whisper needs fullPath, Genius only needs title + artist
  const res = await window.amethyst.getLyrics(
    t.fullPath || null,
    t.title,
    t.artist,
    t.language || "en"
  );

  if (!res?.ok) {
    lyricsContent.textContent = "Lyrics not found.\n" + (res?.error || "");
    if (lyricsStatus) lyricsStatus.textContent = "Not found";
    return;
  }

  const original = String(res.text || "").trim();
const romanised = String(res.romanised || "").trim();
const language = res.language || "";

// Show both if romanised is different from original
if (original && romanised && original !== romanised) {
    lyricsContent.innerHTML = `
        <div style="margin-bottom:12px; opacity:0.6; font-size:11px; text-transform:uppercase; letter-spacing:1px;">
            ${language.toUpperCase()} • Original
        </div>
        <div style="margin-bottom:16px; line-height:1.8;">${original}</div>
        <div style="margin-bottom:12px; opacity:0.6; font-size:11px; text-transform:uppercase; letter-spacing:1px;">
            Romanised
        </div>
        <div style="line-height:1.8; opacity:0.85;">${romanised}</div>
    `;
} else {
    lyricsContent.textContent = original || "No vocals detected / empty transcription.";
}

  // ⭐ THIS IS THE IMPORTANT ADDITION
  if (lyricsStatus) {
    lyricsStatus.textContent = res.cached ? "Cached" : "Generated";
  }
}

function playAt(pos) {
  if (pos < 0 || pos >= order.length) return;

  currentPos = pos;
  const t = tracks[order[currentPos]];

  setArtworkForTrack(t);

  nowTitle.textContent = t.title || "—";
  // Show artist name if available, otherwise show folder
  nowMeta.textContent = t.artist
    ? `${t.artist}${t.album ? " • " + t.album : ""}`
    : t.folder || "Local folder";
  loadLyricsForTrack(t);

  if (!t.fullPath) {
    lyricsContent.textContent = "No audio file available for this song.";
    if (lyricsStatus) lyricsStatus.textContent = "No file";
    return;  // don't try to play
  }

  audio.src = safeFileUrl(t.fullPath);
  audio.play().catch(() => {});

  // reset seek UI until metadata arrives
  seekBar.value = 0;
  curTimeEl.textContent = "0:00";
  durTimeEl.textContent = "0:00";

  updatePlayUI();
}

function nextTrack(auto = false) {
  if (!order.length) return;

  // Repeat One
  if (repeatMode === "one" && auto) {
    audio.currentTime = 0;
    audio.play().catch(() => {});
    return;
  }

  // Shuffle
  if (shuffleOn) {
    const choices = order.map((_, i) => i).filter(i => i !== currentPos);
    currentPos = choices.length ? choices[Math.floor(Math.random() * choices.length)] : currentPos;
    playAt(currentPos);
    return;
  }

  // Normal
  if (currentPos + 1 < order.length) playAt(currentPos + 1);
  else {
    if (repeatMode === "all") playAt(0);
    else {
      audio.pause();
      updatePlayUI();
    }
  }
}

function prevTrack() {
  if (!order.length) return;

  // restart track if already progressed
  if (audio.currentTime > 3) {
    audio.currentTime = 0;
    return;
  }

  // Shuffle backwards (random pick)
  if (shuffleOn) {
    const choices = order.map((_, i) => i).filter(i => i !== currentPos);
    currentPos = choices.length ? choices[Math.floor(Math.random() * choices.length)] : currentPos;
    playAt(currentPos);
    return;
  }

  // Normal
  if (currentPos > 0) playAt(currentPos - 1);
  else if (repeatMode === "all") playAt(order.length - 1);
  else playAt(0);
}

/* =========================================================
   9) EVENTS: BUTTONS / AUDIO / INPUTS
========================================================= */
btnPick.addEventListener("click", async () => {
  if (!window.amethyst || !window.amethyst.pickFolder) {
    console.error("❌ amethyst API not available");
    alert("Internal error: preload bridge not loaded");
    return;
  }

  console.log("📂 Pick folder clicked");

  const res = await window.amethyst.pickFolder();
  console.log("📂 Folder response:", res);

  if (!res?.ok) {
    console.warn("⚠️ Folder selection cancelled or failed");
    return;
  }

  folderPath = res.folderPath || "";

  tracks = (res.tracks || []).map(t => ({
    ...t,
    title: t.title || t.filename || "Unknown",
    folder: t.folder || ""
  }));

  rebuildOrder();
  updateCount();
  renderList();
  renderLucideNow();

  nowMeta.textContent = tracks.length
    ? `Loaded ${tracks.length} tracks`
    : "No audio files found in that folder";
});

btnPlay.addEventListener("click", async () => {
  if (!audio.src) {
    if (order.length) playAt(0);
    return;
  }

  if (audio.paused) {
    // Resume AudioContext after user gesture (required in some environments)
    try { await audioCtx?.resume?.(); } catch {}
    audio.play().catch(() => {});
  } else {
    audio.pause();
  }

  updatePlayUI();
});

btnNext.addEventListener("click", () => nextTrack(false));
btnPrev.addEventListener("click", () => prevTrack());

btnShuffle.addEventListener("click", () => {
  shuffleOn = !shuffleOn;
  setModeUI();
});

btnRepeat.addEventListener("click", () => {
  repeatMode = repeatMode === "off" ? "one" : repeatMode === "one" ? "all" : "off";
  setModeUI();
});

sortEl.addEventListener("change", () => {
  rebuildOrder();
  renderList();
});

searchEl.addEventListener("input", () => {
  renderList();
});

volBar.addEventListener("input", () => {
  audio.volume = Number(volBar.value);
  updateVolumeIcon();
});

/* Audio element events */
audio.addEventListener("loadedmetadata", () => {
  durTimeEl.textContent = fmtTime(audio.duration);
});

audio.addEventListener("timeupdate", () => {
  if (isFinite(audio.duration) && audio.duration > 0) {
    seekBar.value = Math.floor((audio.currentTime / audio.duration) * 1000);
  }
  curTimeEl.textContent = fmtTime(audio.currentTime);
});

audio.addEventListener("ended", () => nextTrack(true));
audio.addEventListener("play", () => updatePlayUI());
audio.addEventListener("pause", () => updatePlayUI());
audio.addEventListener("playing", () => updatePlayUI());

seekBar.addEventListener("input", () => {
  if (isFinite(audio.duration) && audio.duration > 0) {
    audio.currentTime = (Number(seekBar.value) / 1000) * audio.duration;
  }
});

/* Keyboard shortcuts (disabled while typing in inputs) */
window.addEventListener("keydown", (e) => {
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

  if (e.code === "Space") {
    e.preventDefault();
    btnPlay.click();
  } else if (e.code === "ArrowRight") {
    audio.currentTime = Math.min((audio.currentTime || 0) + 5, audio.duration || 999999);
  } else if (e.code === "ArrowLeft") {
    audio.currentTime = Math.max((audio.currentTime || 0) - 5, 0);
  } else if (e.code === "ArrowUp") {
    audio.volume = Math.min((audio.volume || 0) + 0.05, 1);
    volBar.value = audio.volume;
    updateVolumeIcon();
  } else if (e.code === "ArrowDown") {
    audio.volume = Math.max((audio.volume || 0) - 0.05, 0);
    volBar.value = audio.volume;
    updateVolumeIcon();
  }
});

/* =========================================================
   10) INIT (runs once)
========================================================= */
function init() {
  // 1) Inject lucide SVG into icon slots
  injectLucideIntoSlots();
  renderLucideNow();

  // 2) Visualizer scaffolding
  initVisualizer();

  // ✅ SET INITIAL BUTTON ICONS
setButtonMainIcon(btnPlay, "play");
setButtonMainIcon(btnPrev, "skip-back");
setButtonMainIcon(btnNext, "skip-forward");

//setSlotIcon(document.getElementById("shuffleIconSlot"), "shuffle");
setSlotIcon(document.getElementById("repeatIconSlot"), "repeat");
setSlotIcon(document.getElementById("volIconSlot"), "volume-2");

  // 3) Initial audio state
  audio.volume = Number(volBar.value);
  updateVolumeIcon();

  // 4) UI state
  setModeUI();
  setArtworkForTrack({ title: "Amethyst" });

  // 5) Library — load from database first
  updateCount();
  renderList();
  updatePlayUI();

  // 6) Auto-load songs from database on startup
  loadSongsFromDatabase();
}

// Load songs from PostgreSQL database
async function loadSongsFromDatabase() {
  if (!window.amethyst?.getSongsFromDb) {
    console.warn("getSongsFromDb not available");
    return;
  }

  console.log("Loading songs from database...");
  nowMeta.textContent = "Loading library...";

  const res = await window.amethyst.getSongsFromDb();
  console.log("First track:", JSON.stringify(res.tracks[0])); // ← ADD THIS LINE

  if (!res?.ok || !res.tracks?.length) {
    console.warn("No songs from DB:", res?.error);
    nowMeta.textContent = "Pick a folder to begin";
    return;
  }

  // Map DB tracks to player format
  tracks = res.tracks.map(t => ({
    ...t,
    title: t.title || "Unknown",
    folder: t.artist || "Database",
    artworkUrl: t.artworkUrl || null,
    youtubeThumbnail: t.youtubeThumbnail || null,  // ← add this
}));

  rebuildOrder();
  updateCount();
  renderList();
  renderLucideNow();

  nowMeta.textContent = `${tracks.length} songs loaded from library`;
  console.log(`Loaded ${tracks.length} songs from database!`);
}

window.addEventListener("DOMContentLoaded", () => {
  init();
});
