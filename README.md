# 🎵 Amethyst Music Pipeline

> A full data engineering capstone project built in 30 days — a multi-source music data pipeline that powers a local desktop music player with lyrics, karaoke, and rich metadata.

---

## 📖 Project Story

This project started with a simple problem — I had a music player (Amethyst) that I built myself, but it couldn't show lyrics or karaoke properly. Instead of just fixing a bug, I decided to build a proper **data engineering pipeline** around it — pulling data from multiple sources, cleaning it, and making it accessible to the player in a structured way.

The result is a complete DE portfolio project that demonstrates real-world skills: multi-source ingestion, data transformation, quality testing, AI-powered data quality agents, and connecting a data pipeline to a real application.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                          │
├──────────────┬──────────────────┬───────────────────────────┤
│ Local Files  │   Spotify API    │      YouTube API          │
│ (Excel +     │ (metadata,       │ (video IDs,               │
│  MP3 folder) │  artwork, dates) │  thumbnails)              │
└──────┬───────┴────────┬─────────┴──────────┬────────────────┘
       │                │                    │
       ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                    BRONZE LAYER (Raw)                        │
│  raw_local_tracks | raw_spotify_tracks | raw_youtube_tracks │
│         Never modified — source of truth                     │
└─────────────────────────┬───────────────────────────────────┘
                          │  dbt run
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    SILVER LAYER (Clean)                      │
│       stg_local | stg_spotify | stg_youtube                 │
│   Filtering, standardizing, deduplication, matching          │
└─────────────────────────┬───────────────────────────────────┘
                          │  dbt run
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     GOLD LAYER (Final)                       │
│              fct_songs_with_lyrics                          │
│   43 songs | 0 duplicates | lyrics + romanisation included  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   LYRICS AI AGENT                            │
│  Claude API brain | Genius + YouTube Captions + Whisper      │
│  Self-evaluating feedback loop | Strategy memory             │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   AMETHYST PLAYER                            │
│     Reads from fct_songs_with_lyrics | Shows lyrics         │
│     Album artwork from Spotify | Karaoke-ready cues         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Database | PostgreSQL | Store all pipeline data |
| Ingestion | Python + psycopg2 | Load data from sources |
| Spreadsheet | pandas + openpyxl | Read Excel playlist |
| Spotify | spotipy | Fetch track metadata + artwork |
| YouTube | google-api-python-client | Fetch video IDs + thumbnails |
| Transformation | dbt (Data Build Tool) | Clean and unify data |
| Lyrics - Genius | lyricsgenius | Fetch English lyrics via API |
| Lyrics - Whisper | faster-whisper | Transcribe audio to lyrics |
| Lyrics - YouTube | youtube-transcript-api | Fetch captions instantly |
| Lyrics - YouTube DL | yt-dlp | Download audio when no local file |
| Romanisation | indic-transliteration | Convert Indic scripts to Roman |
| Romanisation (other) | Claude API | Phonetic romanisation for Spanish, Korean etc |
| AI Agent Brain | Claude API (claude-sonnet-4-6) | Evaluate + fix lyrics quality |
| Player | Electron + Node.js | Desktop music player |
| Player DB | pg (node-postgres) | Connect player to PostgreSQL |

---

## 📁 Project Structure

```
music_pipeline/                    ← Main pipeline folder
│
├── my_playlist.xlsx               ← Source playlist (43 songs)
│
├── load_sources.ipynb             ← Day 2: Load raw data
├── spotify.ipynb                  ← Day 4: Fetch Spotify data
├── youtube.ipynb                  ← Day 5: Fetch YouTube data
├── duplicates.ipynb               ← Day 7: Quality checks
│
└── music_pipeline/                ← dbt project
    ├── dbt_project.yml
    ├── profiles.yml
    ├── models/
    │   ├── stg_local.sql          ← Silver: clean local data
    │   ├── stg_spotify.sql        ← Silver: clean Spotify data
    │   ├── stg_youtube.sql        ← Silver: clean YouTube data
    │   ├── fct_songs.sql          ← Gold: unified songs view
    │   └── schema.yml             ← dbt test definitions
    └── tests/
        └── assert_duration_positive.sql  ← Custom quality test

amethyst-desktop-player/
└── player/
    ├── main.js                    ← Electron main process + DB connection
    ├── preload.js                 ← IPC bridge (renderer ↔ main)
    ├── package.json
    ├── python/
    │   ├── genius_lyrics.py       ← Genius API lyrics fetcher
    │   ├── whisper_lyrics.py      ← Whisper audio transcription
    │   └── lyrics_ai_agent.py     ← AI agent with feedback loop
    └── renderer/
        ├── app.js                 ← UI logic
        ├── index.html             ← UI structure
        └── styles/
            └── main.css           ← Styling
```

---

## 🗄️ Database Schema

```
-- BRONZE LAYER (raw, never modified)
raw_local_tracks      -- spreadsheet songs + audio file paths
raw_spotify_tracks    -- Spotify metadata (artwork, release date)
raw_youtube_tracks    -- YouTube video IDs and thumbnails

-- SILVER LAYER (dbt views — cleaned)
stg_local             -- cleaned local tracks
stg_spotify           -- cleaned Spotify tracks
stg_youtube           -- cleaned YouTube tracks

-- GOLD LAYER (single source of truth)
fct_songs             -- unified clean view (base)
fct_songs_with_lyrics -- real table: all song data + lyrics + romanisation
                      -- this is what the player reads from

-- LEGACY (kept for reference)
lyrics                -- original lyrics table (migrated to fct_songs_with_lyrics)
```

---

## 📅 Day by Day Journey

### Day 1 — Database Design

**What:** Designed the full database schema in PostgreSQL before writing any code.

**Why:** A data engineer always designs the data model first — like an architect drawing blueprints before building.

**Key concept learned:** Bronze → Silver → Gold pattern. Raw data is stored as-is, cleaned in Silver, unified in Gold.

**Key decision:** Separate raw tables per source so if one API breaks, only that table is affected.

---

### Day 2 — Loading Raw Data

**What:** Wrote Python scripts to load spreadsheet and local music folder into `raw_local_tracks`.

**Problem faced:** Local audio files had messy filenames used as song titles (e.g. `angga-renggana-t_the-chainsmokers-closer.mp3`).

**Key concept learned:** `pandas` for reading Excel, `psycopg2` for inserting into PostgreSQL, `mutagen` for reading audio metadata.

---

### Day 3 — Whisper Lyrics Pipeline

**What:** Built `whisper_lyrics.py` — auto language detection + romanisation for all scripts.

**Problem identified:** Original Whisper setup was hardcoded to Telugu for ALL songs.

**Fix:** Auto language detection with `faster-whisper`, romanisation for Indic scripts via `indic_transliteration`, timestamped karaoke cues output.

---

### Day 4 — Spotify API

**What:** Connected to Spotify Developer API and fetched metadata for all 43 songs.

**Problem faced:** Spotify removed `popularity` and `preview_url` from search results in 2024. Had to adapt schema.

**Key concept learned:** APIs change over time — data engineers must handle breaking changes gracefully. Rate limiting — why we add `time.sleep(0.5)` between requests.

**Key decision:** Store `artwork_url` and `release_date` — these power the player UI later.

---

### Day 5 — YouTube API

**What:** Connected to YouTube Data API v3 and fetched video data for all songs.

**Problem faced:** YouTube gives duration in ISO 8601 format (`PT3M33S`) — had to write converter.

**Key concept learned:** Every API has its own quirks and formats. The conversion `PT3M33S → 213 seconds` is a real-world data transformation.

**Key decision:** Store `youtube_video_id` so player can download audio or fetch captions later.

---

### Day 6 — dbt Pipeline

**What:** Set up dbt and wrote SQL models for Bronze → Silver → Gold transformation.

**Key concept learned:** dbt manages dependencies between models automatically. `{{ ref('stg_spotify') }}` tells dbt to run stg_spotify before fct_songs.

**Key decision:** Use `DISTINCT ON` in all CTEs to prevent duplicates at every layer.

**Key insight:** `REGEXP_REPLACE(title, '\(.*?\)', '', 'g')` to strip everything in () from filenames — generic solution vs hardcoded. Generic is always better.

---

### Day 7 — Duplicate Detection and Cleaning

**What:** Found and fixed 24 duplicate songs in `fct_songs`.

**Root causes:**
1. Audio filenames used as song titles
2. YouTube API fetched same video twice (58 rows, 47 unique)
3. Spreadsheet loaded multiple times

**Most important lesson learned:**
> Always fix data at the SOURCE (Bronze layer), not at Gold layer. If you fix at Gold, duplicates come back next `dbt run`.

**Key decision:** Never DELETE from raw tables. Filter bad data in `stg_local.sql` instead. Raw data is sacred.

---

### Day 8 — dbt Tests (Data Quality)

**What:** Added 15 automated data quality tests using `schema.yml` and custom SQL tests.

**Tests added:**
- `not_null` on all critical fields
- `unique` on all ID fields
- `accepted_values` for source column
- Custom `assert_duration_positive.sql`

**Key concept learned:** Data quality tests run automatically. If bad data gets in, tests catch it before it reaches the player.

---

### Day 9 — Connecting Player to Database

**What:** Connected Amethyst Electron player to PostgreSQL. Player now reads songs, artwork, and lyrics directly from `fct_songs_with_lyrics` instead of scanning a local folder.

**Problem faced:** `fct_songs` is a VIEW — couldn't add lyrics columns to it directly.

**Solution:** Created `fct_songs_with_lyrics` as a real table combining all song metadata + lyrics columns. This became the single source of truth for both the agent and the player.

**Key concept learned:** Views are read-only — if you need to write to the gold layer, you need a real table. This is a common real-world DE decision.

**Key decision:** The player and the AI agent both read and write to the same gold table — one source of truth, no sync needed between layers.

---

### Day 10 — Smart Lyrics System + AI Agent

**What:** Built a full multi-source lyrics system and an AI agent with a self-evaluating feedback loop to ensure lyrics quality across all 43 songs.

#### Lyrics System Architecture

Three-tier lyrics fetching with intelligent fallback:

```
1. Genius API (English songs) → accurate, instant
2. YouTube Captions (any song with video ID) → instant, no download
3. Whisper transcription → local file or YouTube download via yt-dlp
```

**Problems faced and fixed:**
- Genius returning Turkish translations instead of English originals → added language detection + result validation via Claude
- Whisper hallucinating garbage lyrics ("I want to serve the Senate") → hallucination detection
- Songs with no local audio file → YouTube audio download via `yt-dlp`
- Non-English lyrics not romanised (Spanish Despacito, Korean Golden) → three-tier romanisation system

**Three-tier romanisation:**
- Indic scripts (Telugu, Hindi, Tamil etc.) → `indic_transliteration` library (fast, offline)
- Korean, Japanese, Arabic → Claude API phonetic romanisation
- Spanish, French, Portuguese → Claude API phonetic transliteration (so users can sing along)

#### AI Agent (`lyrics_ai_agent.py`)

A proper agentic system using Claude as the reasoning brain:

```
For each song:
  1. Claude evaluates lyrics quality → score 0-100
  2. Score < 75? Claude diagnoses WHY it's bad
  3. Claude decides next strategy based on diagnosis
  4. Execute strategy → Claude scores the result
  5. Repeat up to 2 attempts
  6. Still bad? Flag for manual review
```

**Strategies the agent can choose:**
- `genius_search` — search by title + artist
- `genius_with_language_filter` — reject non-English results
- `genius_title_only` — title-only search when artist causes wrong results
- `youtube_captions` — instant caption fetch via video ID
- `whisper_retry` — re-transcribe local audio
- `whisper_youtube` — download audio from YouTube then transcribe
- `romanise_only` — romanise existing correct lyrics
- `clean_headers` — remove [Verse]/[Chorus] tags
- `manual_review` — flag for human

**Strategy memory (`agent_memory.json`):**
The agent remembers what strategies worked for similar songs across runs. For example, after learning that `genius_with_language_filter` scores 92 on average for `en:WRONG_LANGUAGE` issues, it will suggest that strategy first next time. Gets smarter every run.

**Results:**
```
Total songs:    43
Already OK:     40  (93%)
Fixed by agent:  1
Flagged:         2  (manually handled)
```

**Key concept learned:** A real AI agent is not just a script that tries things — it evaluates its own output, learns from failures, and adjusts strategy. The feedback loop is what makes it agentic.

**Key decision:** Save fixes to a `lyrics_review/` folder first before committing to DB — human oversight before any data change. This is the correct data engineering approach: never blindly overwrite production data.

---

## 🧠 Key Design Decisions

### 1. Raw data is never modified

```
WRONG: DELETE FROM raw_local_tracks WHERE title IS NULL
RIGHT: Filter NULLs in stg_local.sql WHERE title IS NOT NULL
```

Raw tables are your source of truth. If you delete from them, you lose the ability to debug and replay.

### 2. Fix data at the source, not the destination

When duplicates appeared in `fct_songs`, the temptation was to delete from `fct_songs`. Instead we traced duplicates back to `raw_youtube_tracks` and fixed them there. This means the fix persists across all future `dbt run` executions.

### 3. Generic rules over specific ones

Instead of hardcoding `AND filename NOT LIKE '%time for africa%'`, we wrote `REGEXP_REPLACE(title, '\(.*?\)', '', 'g')` which strips ALL parenthetical content generically.

### 4. Silver layer is where cleaning happens

```
Bronze → raw, messy, as-is (never touch)
Silver → clean, standardized, filtered
Gold   → unified, joined, ready for use
```

### 5. Single source of truth at the gold layer

`fct_songs_with_lyrics` is the only table the player and agent interact with. No syncing between tables, no risk of inconsistency.

### 6. Human review before production writes

The AI agent never writes directly to the DB on first run. It saves fixes to `lyrics_review/` first. Only after human approval does `--commit` push to the gold layer. This prevents bad automated changes from reaching production.

---

## 🔄 How to Run the Pipeline

### First time setup

```bash
# Install Python dependencies
pip install -r requirements.txt
pip install python-dotenv lyricsgenius faster-whisper yt-dlp youtube-transcript-api psycopg2-binary

# Create .env file with your API keys
ANTHROPIC_API_KEY=your_key_here
GENIUS_TOKEN=your_key_here

# Set up database (run schema SQL in pgAdmin)
# Install Node dependencies for player
cd amethyst-desktop-player/player
npm install
```

### Running the pipeline

```bash
# Step 1: Load raw data
# Run load_sources.ipynb in Jupyter

# Step 2: Fetch Spotify data
# Run spotify.ipynb in Jupyter

# Step 3: Fetch YouTube data
# Run youtube.ipynb in Jupyter

# Step 4: Transform with dbt
cd music_pipeline/music_pipeline
dbt run

# Step 5: Run quality tests
dbt test

# Step 6: Run AI lyrics agent (dry run first)
cd amethyst-desktop-player/player
python python/lyrics_ai_agent.py --dry-run

# Step 7: Full agent run + review
python python/lyrics_ai_agent.py
# Review lyrics_review/ folder, then:
python python/lyrics_ai_agent.py --commit

# Step 8: Start the player
npm start
```

---

## 📊 Current Pipeline Stats

```
raw_local_tracks:        43 spreadsheet + 20 audio file rows
raw_spotify_tracks:      43 songs enriched
raw_youtube_tracks:      47 unique videos

stg_local:               42 clean songs (18 with audio file)
fct_songs:               43 songs, 0 duplicates
fct_songs_with_lyrics:   43 songs, 40 with verified lyrics

dbt tests:               15 passing, 0 failing
AI agent runs:           88 total processed, 10 fixed, 93% quality rate
```

---

## 🚀 What's Next

- Day 11: Karaoke cue syncing to playback
- Day 12: Orchestrate pipeline with Prefect
- Day 13: Dockerize everything

---

## 👩‍💻 About

Built by Vaasanthi as a 30-day data engineering capstone project.
Background: Product Owner in EdTech → transitioning to Data Engineering.

This project demonstrates: multi-source data ingestion, ETL pipeline design, data quality testing, API integration, AI-powered data quality agents, and connecting a data pipeline to a real-world application.
