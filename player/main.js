/**
 * main.js
 * - Creates the Electron window (fixed 1120x720)
 * - Secure webPreferences (no nodeIntegration)
 * - Provides IPC to pick a folder and return scanned audio tracks
 */
// PostgreSQL connection
const { Pool } = require("pg");

const db = new Pool({
  host: "localhost",
  database: "music_db",
  user: "postgres",
  password: "postgres123",
  port: 5432
});

// Test DB connection on startup
db.connect()
  .then(() => console.log("✅ Connected to music_db!"))
  .catch(err => console.error("❌ DB connection failed:", err.message));

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const crypto = require("crypto");

const AUDIO_EXT = new Set([".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"]);

function createWindow() {
  const win = new BrowserWindow({
    width: 1120,
    height: 720,
    resizable: false,
    backgroundColor: "#0f0a1f",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  // Prevent any window.open popups
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));

  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  // win.webContents.openDevTools({ mode: "detach" });

  win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; img-src 'self' https://i.scdn.co https://i.ytimg.com data: blob:; media-src 'self' file: blob:; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'"
        ]
      }
    });
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

/**
 * Scan a folder recursively and return track objects:
 * { id, title, folder, fullPath, filename }
 */
function scanDirForAudio(rootDir) {
  const results = [];
  let id = 1;

  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });

    for (const e of entries) {
      const full = path.join(dir, e.name);

      if (e.isDirectory()) {
        // Skip hidden folders
        if (e.name.startsWith(".")) continue;
        walk(full);
      } else {
        const ext = path.extname(e.name).toLowerCase();
        if (!AUDIO_EXT.has(ext)) continue;

        const title = path.basename(e.name, ext);
        const folder = path.basename(path.dirname(full));

        results.push({
          id: id++,
          title,
          folder,
          fullPath: full,
          filename: e.name
        });
      }
    }
  }

  walk(rootDir);
  return results;
}

/**
 * IPC handler: pick-folder
 * Renderer calls this via preload (safe bridge)
 */
ipcMain.handle("pick-folder", async () => {
  const res = await dialog.showOpenDialog({ properties: ["openDirectory"] });

  if (res.canceled || !res.filePaths?.[0]) {
    return { ok: false, tracks: [], folderPath: "" };
  }

  const folderPath = res.filePaths[0];

  try {
    const tracks = scanDirForAudio(folderPath);
    return { ok: true, tracks, folderPath };
  } catch (err) {
    return {
      ok: false,
      tracks: [],
      folderPath,
      error: String(err?.message || err)
    };
  }
});

function sha1(s) {
  return crypto.createHash("sha1").update(String(s)).digest("hex");
}

function runWhisperPython(fullPath) {
  return new Promise((resolve) => {
    const py = process.platform === "win32" ? "python.exe" : "python3";
    const script = path.join(__dirname, "python", "whisper_lyrics.py");

    const p = spawn(py, [script, fullPath], {
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" }
    });

    let out = "";
    let err = "";

    p.stdout.setEncoding("utf8");
    p.stderr.setEncoding("utf8");

    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (err += d));

    p.on("error", (e) => {
      resolve({ ok: false, error: "Python spawn error: " + String(e.message || e) });
    });

    p.on("close", (code) => {
      try {
        const json = JSON.parse(out.trim() || "{}");
        if (!json.ok && err) json.error = (json.error || "") + "\n" + err;
        resolve(json.ok ? json : { ok: false, error: json.error || err || "Whisper failed" });
      } catch {
        resolve({
          ok: false,
          error: "Whisper output parse failed",
          extra: { code, out: out.slice(0, 500), err: err.slice(0, 500) }
        });
      }
    });
  });
}

ipcMain.handle("get-lyrics", async (_evt, fullPath, songTitle, songArtist, songLanguage) => {

  // ─────────────────────────────────────────────
  // STEP 0: If artist is missing, look it up from fct_songs
  // ─────────────────────────────────────────────
  if (!songArtist && songTitle) {
    try {
      const artistLookup = await db.query(`
        SELECT artist FROM fct_songs_with_lyrics 
        WHERE LOWER(TRIM(title)) = LOWER(TRIM($1)) 
        AND artist IS NOT NULL AND artist != ''
        LIMIT 1
      `, [songTitle]);

      if (artistLookup.rows.length > 0) {
        songArtist = artistLookup.rows[0].artist;
        console.log(`Looked up artist for "${songTitle}": ${songArtist}`);
      }
    } catch (e) {
      console.warn("Artist lookup failed:", e.message);
    }
  }
  
  // ─────────────────────────────────────────────
  // STEP 1: Check database first — always fastest
  // ─────────────────────────────────────────────
  try {
    const dbResult = await db.query(`
      SELECT 
        l.lyrics_text, 
        l.romanised_text, 
        l.detected_language,
        l.source
      FROM lyrics l
      JOIN songs s ON l.song_id = s.id
      WHERE LOWER(TRIM(s.title)) = LOWER(TRIM($1))
      AND l.lyrics_text IS NOT NULL
      LIMIT 1
    `, [songTitle || ""]);

    if (dbResult.rows.length > 0) {
      const row = dbResult.rows[0];
      console.log(`Lyrics from DB for: ${songTitle}`);
      return {
        ok: true,
        cached: true,
        source: "database",
        text: row.lyrics_text,
        romanised: row.romanised_text || row.lyrics_text,
        language: row.detected_language || "en"
      };
    }
  } catch (dbErr) {
    console.warn("DB lyrics lookup failed:", dbErr.message);
  }

  // ─────────────────────────────────────────────
  // STEP 2: Decide which engine to use
  // English → Genius API (accurate, instant)
  // Other   → Whisper (transcription)
  // ─────────────────────────────────────────────
  let lyricsText = "";
  let romanisedText = "";
  let detectedLanguage = songLanguage || "en";
  let source = "";

  const isEnglish = !songLanguage || songLanguage === "en" || songLanguage === "english";

  if (isEnglish && songTitle) {
    // Try Genius first
    console.log(`Trying Genius for: ${songTitle}`);
    const geniusRes = await runGeniusPython(songTitle, songArtist || "");

    if (geniusRes?.ok && geniusRes.lyrics) {
      lyricsText = geniusRes.lyrics;
      romanisedText = geniusRes.lyrics; // English is already Roman
      detectedLanguage = "en";
      source = "genius";
      console.log(`Got Genius lyrics for: ${songTitle}`);
    } else {
      console.log(`Genius failed, trying Whisper for: ${songTitle}`);
    }
  }

  // If Genius failed or non-English → use Whisper
  if (!lyricsText && fullPath) {
    console.log(`Running Whisper for: ${songTitle}`);
    const whisperRes = await runWhisperPython(fullPath);

    if (whisperRes?.ok) {
      lyricsText = whisperRes.text || "";
      romanisedText = whisperRes.romanised || lyricsText;
      detectedLanguage = whisperRes.language || "unknown";
      source = "whisper";
    } else {
      return { ok: false, error: whisperRes?.error || "Both Genius and Whisper failed" };
    }
  }

  if (!lyricsText) {
    return { ok: false, error: "Could not get lyrics" };
  }

  // ─────────────────────────────────────────────
  // STEP 3: Save to database for next time
  // ─────────────────────────────────────────────
  try {
    const songResult = await db.query(
      "SELECT id FROM songs WHERE LOWER(TRIM(title)) = LOWER(TRIM($1)) LIMIT 1",
      [songTitle || ""]
    );

    if (songResult.rows.length > 0) {
      const songId = songResult.rows[0].id;

      await db.query(`
        INSERT INTO lyrics 
          (song_id, lyrics_text, romanised_text, detected_language, source)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT DO NOTHING
      `, [songId, lyricsText, romanisedText, detectedLanguage, source]);

      console.log(`Saved ${source} lyrics for: ${songTitle}`);
    }
  } catch (saveErr) {
    console.warn("Failed to save lyrics:", saveErr.message);
  }

  return {
    ok: true,
    cached: false,
    source,
    text: lyricsText,
    romanised: romanisedText,
    language: detectedLanguage
  };
});

// ─────────────────────────────────────────────
// Run Genius lyrics fetcher (for English songs)
// ─────────────────────────────────────────────
function runGeniusPython(title, artist) {
  return new Promise((resolve) => {
    const py = process.platform === "win32" ? "python.exe" : "python3";
    const script = path.join(__dirname, "python", "genius_lyrics.py");

    const p = spawn(py, [script, title, artist || ""], {
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" }
    });

    let out = "";
    let err = "";

    p.stdout.setEncoding("utf8");
    p.stderr.setEncoding("utf8");

    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (err += d));

    p.on("error", (e) => {
      resolve({ ok: false, error: "Python spawn error: " + String(e.message) });
    });

    p.on("close", () => {
      try {
        const json = JSON.parse(out.trim() || "{}");
        resolve(json);
      } catch {
        resolve({ ok: false, error: "Genius output parse failed" });
      }
    });
  });
}
// ─────────────────────────────────────────────
// IPC handler: get-songs-from-db
// Returns all songs from fct_songs gold table
// Player uses this instead of scanning folder
// ─────────────────────────────────────────────
ipcMain.handle("get-songs-from-db", async () => {
  try {
    const result = await db.query(`
      SELECT
        song_id,
        title,
        artist,
        album,
        duration_seconds,
        local_file_path,
        spotify_id,
        artwork_url,
        youtube_video_id,
        youtube_thumbnail
      FROM fct_songs_with_lyrics
      WHERE title IS NOT NULL
      ORDER BY title ASC
    `);

    // Map to same format player already expects
    const tracks = result.rows.map((row, index) => ({
      id: row.song_id || index + 1,
      title: row.title,
      artist: row.artist || "Unknown Artist",
      album: row.album || "",
      duration: row.duration_seconds,
      fullPath: row.local_file_path || null,
      filename: row.local_file_path
        ? row.local_file_path.split("\\").pop()
        : row.title,
      artworkUrl: row.artwork_url || null,
      youtubeVideoId: row.youtube_video_id || null,
      youtubeThumbnail: row.youtube_thumbnail || null,
      spotifyId: row.spotify_id || null,
      folder: "Database"
    }));

    return { ok: true, tracks };

  } catch (err) {
    console.error("DB query failed:", err.message);
    return { ok: false, error: err.message, tracks: [] };
  }
});

