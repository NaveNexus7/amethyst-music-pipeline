# 🎵 Amethyst Music Pipeline

> A full data engineering capstone project built in 30 days — a multi-source music data pipeline that powers a local desktop music player with lyrics, karaoke, and rich metadata.

---

## 📖 Project Story

This project started with a simple problem — I had a music player (Amethyst) that I built myself, but it couldn't show lyrics or karaoke properly. Instead of just fixing a bug, I decided to build a proper **data engineering pipeline** around it — pulling data from multiple sources, cleaning it, and making it accessible to the player in a structured way.

The result is a complete DE portfolio project that demonstrates real-world skills: multi-source ingestion, data transformation, quality testing, and connecting a data pipeline to a real application.

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
│                        fct_songs                            │
│        43 songs | 0 duplicates | all sources merged         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   AMETHYST PLAYER                            │
│     Reads from fct_songs | Shows lyrics from DB             │
│     Karaoke cues synced to playback | Album artwork         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Database | PostgreSQL | Store all pipeline data |
| Ingestion | Python + psycopg2 | Load data from sources |
| Spreadsheet | pandas + openpyxl | Read Excel playlist |
| Spotify | spotipy | Fetch track metadata |
| YouTube | google-api-python-client | Fetch video data |
| Transformation | dbt (Data Build Tool) | Clean and unify data |
| Lyrics | OpenAI Whisper (faster-whisper) | Transcribe audio |
| Romanisation | indic-transliteration | Convert scripts to Roman |
| Player | Electron + Node.js | Desktop music player |
| Player DB | pg (node-postgres) | Connect player to DB |

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
    │   ├── fct_songs.sql          ← Gold: unified songs table
    │   └── schema.yml             ← dbt test definitions
    └── tests/
        └── assert_duration_positive.sql  ← Custom quality test

amethyst-desktop-player/
└── player/
    ├── main.js                    ← Electron main process
    ├── preload.js                 ← IPC bridge
    ├── package.json
    ├── python/
    │   └── whisper_lyrics.py      ← Lyrics + karaoke generation
    └── renderer/
        ├── app.js                 ← UI logic
        ├── index.html             ← UI structure
        └── styles/
            └── main.css           ← Styling
```

---

## 🗄️ Database Schema

```sql
-- BRONZE LAYER
raw_local_tracks      -- spreadsheet songs + audio file paths
raw_spotify_tracks    -- Spotify metadata (artwork, release date)
raw_youtube_tracks    -- YouTube video IDs and thumbnails

-- GOLD LAYER (built by dbt)
fct_songs             -- unified clean table read by player
lyrics                -- transcribed lyrics per song
karaoke_cues          -- timestamped lyric lines for karaoke

-- SILVER LAYER (dbt views)
stg_local             -- cleaned local tracks
stg_spotify           -- cleaned Spotify tracks  
stg_youtube           -- cleaned YouTube tracks
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

### Day 3 — Whisper Lyrics Pipeline (Pending)
**What:** Planned the lyrics generation pipeline using OpenAI Whisper.

**Problem identified:** `whisper_lyrics.py` was hardcoded to Telugu (`language="te"`) for ALL songs.

**Planned fix:** Auto language detection + romanisation for all Indic scripts.

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

**Key decision:** Store `youtube_video_id` so player can link to official music video.

---

### Day 6 — dbt Pipeline
**What:** Set up dbt and wrote SQL models for Bronze → Silver → Gold transformation.

**Key concept learned:** dbt manages dependencies between models automatically. `{{ ref('stg_spotify') }}` tells dbt to run stg_spotify before fct_songs.

**Key decision:** Use `DISTINCT ON` in all CTEs to prevent duplicates at every layer.

**Key insight:** `REGEXP_REPLACE(title, '\(.*?\)', '', 'g')` to strip everything in () from filenames — this was a generic solution vs a hardcoded one. Generic is always better.

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

**Proudest moment:** Suggested stripping `()` generically from filenames — "shouldn't it be more generic like anything within () must be excluded?" This is exactly how real DEs think.

---

### Day 8 — dbt Tests (Data Quality)
**What:** Added 15 automated data quality tests using `schema.yml` and custom SQL tests.

**Tests added:**
- `not_null` on all critical fields
- `unique` on all ID fields  
- `accepted_values` for source column
- Custom `assert_duration_positive.sql`

**Key concept learned:** Data quality tests run automatically. If bad data gets in, tests catch it before it reaches the player.

**Interesting finding:** A NULL title inserted into `raw_local_tracks` was filtered by `stg_local.sql` before dbt tests even ran — showing two layers of protection working correctly.

---

### Day 9 — Connecting to Player (In Progress)
**What:** Installing `pg` library, connecting Amethyst player to PostgreSQL database.

**Planned changes:**
- Player reads song list from `fct_songs` instead of scanning folder
- Album artwork from Spotify displayed
- Lyrics loaded from database (instant, no re-transcription)
- Karaoke cues synced to audio playback

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
Instead of hardcoding `AND filename NOT LIKE '%time for africa%'`, we wrote `REGEXP_REPLACE(title, '\(.*?\)', '', 'g')` which strips ALL parenthetical content generically. This handles any future edge case automatically.

### 4. Silver layer is where cleaning happens
```
Bronze → raw, messy, as-is (never touch)
Silver → clean, standardized, filtered
Gold   → unified, joined, ready for use
```

---

## 🔄 How to Run the Pipeline

### First time setup:
```bash
# Install Python dependencies
pip install -r requirements.txt

# Set up database (run schema SQL in pgAdmin)
# See database/schema.sql

# Install Node dependencies for player
cd amethyst-desktop-player/player
npm install
```

### Running the pipeline:
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

# Step 6: Start the player
cd amethyst-desktop-player/player
npm start
```

---

## 📊 Current Pipeline Stats

```
raw_local_tracks:    43 spreadsheet + 20 audio file rows
raw_spotify_tracks:  43 songs enriched
raw_youtube_tracks:  47 unique videos

stg_local:   42 clean songs (18 with audio file)
fct_songs:   43 songs, 0 duplicates

dbt tests:   15 passing, 0 failing
```

---

## 🚀 Whats Next

- [ ] Day 9: Connect player to database
- [ ] Day 10: Fix Whisper lyrics with language detection
- [ ] Day 11: Add karaoke cue display in player
- [ ] Day 12: Orchestrate pipeline with Prefect
- [ ] Day 13: Dockerize everything

---

## 👩‍💻 About

Built by Vaasanthi as a 30-day data engineering capstone project.
Background: Product Owner in EdTech → transitioning to Data Engineering.

This project demonstrates: multi-source data ingestion, ETL pipeline design, 
data quality testing, API integration, and connecting a data pipeline to a 
real-world application.
