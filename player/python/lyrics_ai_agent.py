#!/usr/bin/env python3
"""
lyrics_ai_agent.py
Amethyst Lyrics AI Agent — Proper Agentic Loop

Uses Claude as the brain to:
  1. Evaluate lyrics quality (0-100 score)
  2. Diagnose WHY lyrics are bad
  3. Decide WHAT strategy to try next
  4. Remember what worked across songs
  5. Retry up to MAX_ATTEMPTS times per song
  6. Flag unresolvable songs for manual review

Usage:
  # Run agent on all songs
  python lyrics_ai_agent.py

  # Dry run - evaluate only, no fixes
  python lyrics_ai_agent.py --dry-run

  # Run on specific song
  python lyrics_ai_agent.py --title "Blank Space" --artist "Taylor Swift"

  # Commit reviewed fixes to DB
  python lyrics_ai_agent.py --commit

  # Show strategy memory
  python lyrics_ai_agent.py --show-memory
"""

from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
import os
from dotenv import load_dotenv
load_dotenv()  # loads .env file automatically
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "database": "music_db",
    "user": "postgres",
    "password": "postgres123",
    "port": 5432,
}

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_ATTEMPTS = 2          # retries per song
QUALITY_THRESHOLD = 75    # minimum acceptable score (0-100)
REVIEW_DIR = Path("lyrics_review")
MEMORY_FILE = Path("agent_memory.json")

# ─────────────────────────────────────────────────────────────
# STRATEGY MEMORY
# Remembers what worked for similar songs across runs
# ─────────────────────────────────────────────────────────────

class StrategyMemory:
    def __init__(self):
        self.memory = {
            "strategies": {},       # language -> list of successful strategies
            "failed_patterns": [],  # patterns that never work
            "stats": {
                "total_processed": 0,
                "total_fixed": 0,
                "total_failed": 0,
            }
        }
        self.load()

    def load(self):
        if MEMORY_FILE.exists():
            try:
                self.memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                print(f"📚 Loaded strategy memory ({len(self.memory['strategies'])} language entries)")
            except Exception:
                pass

    def save(self):
        MEMORY_FILE.write_text(
            json.dumps(self.memory, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def record_success(self, language: str, issue_type: str, strategy: str, score: int):
        key = f"{language}:{issue_type}"
        if key not in self.memory["strategies"]:
            self.memory["strategies"][key] = []

        # Add strategy if not already known
        entry = {"strategy": strategy, "avg_score": score, "count": 1}
        existing = next((s for s in self.memory["strategies"][key]
                        if s["strategy"] == strategy), None)
        if existing:
            # Update running average
            existing["avg_score"] = (existing["avg_score"] * existing["count"] + score) / (existing["count"] + 1)
            existing["count"] += 1
        else:
            self.memory["strategies"][key].append(entry)

        # Sort by avg score descending
        self.memory["strategies"][key].sort(key=lambda x: x["avg_score"], reverse=True)
        self.save()

    def record_failure(self, title: str, artist: str, issue_type: str):
        self.memory["failed_patterns"].append({
            "title": title,
            "artist": artist,
            "issue": issue_type,
            "timestamp": datetime.now().isoformat()
        })
        self.memory["stats"]["total_failed"] += 1
        self.save()

    def get_best_strategy(self, language: str, issue_type: str) -> str | None:
        key = f"{language}:{issue_type}"
        strategies = self.memory["strategies"].get(key, [])
        if strategies:
            best = strategies[0]
            print(f"  🧠 Memory: Best strategy for {key}: '{best['strategy']}' (avg score: {best['avg_score']:.0f})")
            return best["strategy"]
        return None

    def update_stats(self, fixed: bool):
        self.memory["stats"]["total_processed"] += 1
        if fixed:
            self.memory["stats"]["total_fixed"] += 1
        self.save()


# ─────────────────────────────────────────────────────────────
# CLAUDE API — THE BRAIN
# ─────────────────────────────────────────────────────────────

def call_claude(prompt: str, system: str = "") -> str:
    """Call Claude API and return response text."""
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),  # ← paste your key here
    }

    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system:
        body["system"] = system

    try:
        r = requests.post(ANTHROPIC_API_URL, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"  ⚠️  Claude API error: {e}")
        return ""


def evaluate_lyrics(title: str, artist: str, lyrics: str,
                    language: str, source: str) -> dict:
    """
    Ask Claude to evaluate lyrics quality.
    Returns: { score, issues, diagnosis, suggested_strategy, reasoning }
    """
    if not lyrics or len(lyrics.strip()) < 10:
        return {
            "score": 0,
            "issues": ["MISSING"],
            "diagnosis": "No lyrics found",
            "suggested_strategy": "genius_search",
            "reasoning": "Empty lyrics"
        }

    total_chars = len(lyrics.strip())
    has_non_roman = any(ord(c) > 0x024F for c in lyrics)

    prompt = f"""You are evaluating lyrics for a music player app.

Song: "{title}" by {artist}
Language: {language or "unknown"}
Source: {source or "unknown"}
Total lyrics length: {total_chars} characters
Contains non-Roman script: {has_non_roman}
Lyrics (first 1500 chars of {total_chars} total):
---
{lyrics[:1500]}
---

Evaluate these lyrics and respond with ONLY a JSON object (no markdown, no explanation):
{{
  "score": <0-100 integer>,
  "issues": [<list of issue strings>],
  "diagnosis": "<one sentence explaining the main problem>",
  "suggested_strategy": "<one of: genius_search, genius_with_language_filter, whisper_retry, whisper_no_vad, romanise_only, clean_headers, manual_review>",
  "reasoning": "<one sentence explaining why this strategy>",
  "is_correct_song": <true/false>,
  "is_correct_language": <true/false>,
  "is_hallucinated": <true/false>
}}

Scoring guide:
- 90-100: Perfect lyrics, correct song, correct language, clean
- 70-89: Good lyrics, minor issues (some headers, slight formatting)
- 50-69: Mediocre (missing sections, slightly wrong)
- 30-49: Poor (wrong language, heavy hallucination, wrong song)
- 0-29: Unusable (complete garbage, empty, or totally wrong)

IMPORTANT RULES:
- TOO_SHORT: ONLY flag if total lyrics length is under 200 chars. Never flag based on preview being cut off.
- NEEDS_ROMANISATION: flag if lyrics contain non-Roman script (Telugu, Hindi, Korean, Arabic etc) AND romanised version is needed
- If lyrics are in a non-English language but are CORRECT for that song (e.g. Despacito in Spanish), score them highly
- HAS_HEADERS: only flag if [Verse], [Chorus], [Bridge] tags are present in the text

Issue strings to use: WRONG_LANGUAGE, HALLUCINATED, WRONG_SONG, HAS_HEADERS, MISSING_SECTIONS, TOO_SHORT, MISSING, NEEDS_ROMANISATION"""

    response = call_claude(prompt)

    try:
        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?|```", "", response).strip()
        result = json.loads(clean)
        return result
    except Exception:
        # Fallback if Claude returns unexpected format
        return {
            "score": 50,
            "issues": ["PARSE_ERROR"],
            "diagnosis": "Could not parse Claude evaluation",
            "suggested_strategy": "genius_search",
            "reasoning": "Defaulting to Genius search",
            "is_correct_song": None,
            "is_correct_language": None,
            "is_hallucinated": None
        }


def decide_next_strategy(title: str, artist: str, language: str,
                         previous_attempts: list[dict],
                         memory: StrategyMemory,
                         has_video_id: bool = False,
                         has_local_audio: bool = False) -> str:

    attempts_summary = "\n".join([
        f"  Attempt {i+1}: strategy={a['strategy']}, score={a['score']}, issues={a['issues']}"
        for i, a in enumerate(previous_attempts)
    ])

    primary_issue = previous_attempts[-1].get("issues", ["UNKNOWN"])[0] if previous_attempts else "UNKNOWN"
    memory_hint = memory.get_best_strategy(language or "en", primary_issue)

    prompt = f"""You are an AI agent deciding the next strategy to fix lyrics for a music app.

Song: "{title}" by {artist}
Language: {language or "unknown"}
Has YouTube video ID: {has_video_id} (can use youtube_captions if True)
Has local audio file: {has_local_audio} (can use whisper_retry if True)

Previous attempts:
{attempts_summary}

Memory hint: {memory_hint or "No memory yet"}

STRICT RULES:
1. If Genius scored below 50 → DO NOT try Genius again
2. If has_video_id is True and Genius failed → ALWAYS try youtube_captions next (instant!)
3. If youtube_captions failed or has_video_id is False → try whisper_youtube
4. If both Genius AND non-Genius strategy failed → manual_review
5. IGNORE memory hints if youtube_captions hasn't been tried yet and has_video_id is True

Available strategies:
- genius_search, genius_with_language_filter, genius_title_only
- youtube_captions: instant captions from YouTube (needs has_video_id=True) — PREFER THIS over whisper!
- whisper_retry: local audio transcription (needs has_local_audio=True)
- whisper_no_vad: Whisper without VAD
- whisper_youtube: download + transcribe (works without local file)
- romanise_only, clean_headers, manual_review

Respond with ONLY a JSON object:
{{
  "strategy": "<chosen strategy>",
  "reasoning": "<one sentence why>",
  "confidence": <0-100>
}}"""

    response = call_claude(prompt)
    try:
        clean = re.sub(r"```(?:json)?|```", "", response).strip()
        result = json.loads(clean)
        return result.get("strategy", "manual_review")
    except Exception:
        return "manual_review"

# ─────────────────────────────────────────────────────────────
# LYRICS FETCHERS
# ─────────────────────────────────────────────────────────────

BAD_TITLE_KEYWORDS = [
    "türkçe", "turkish", "traducción", "traduction", "перевод",
    "tradução", "versuri", "çeviri", "traduzione", "übersetzung",
    "letras", "magyar", "terjemahan",
]

def find_script(name: str) -> Path | None:
    """Find a python script in common locations."""
    candidates = [
        Path(__file__).parent / "python" / name,
        Path(__file__).parent / name,
        Path("python") / name,
        Path(name),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ─────────────────────────────────────────────────────────────
# PRIORITY 2: YouTube audio download fallback
# When no local_file_path exists, download audio from YouTube
# using yt-dlp so Whisper can transcribe it
# ─────────────────────────────────────────────────────────────

YTDLP_CACHE = Path("ytdlp_cache")  # temp folder for downloaded audio

def fetch_youtube_audio(title: str, artist: str, video_id: str = "") -> str | None:
    """
    Download audio from YouTube using yt-dlp.
    Uses video_id directly if available (from fct_songs), otherwise searches.
    Returns path to downloaded audio file, or None if failed.
    """
    try:
        import shutil
        if not shutil.which("yt-dlp"):
            print("    ⚠️  yt-dlp not installed. Run: pip install yt-dlp")
            return None

        YTDLP_CACHE.mkdir(exist_ok=True)

        safe = re.sub(r'[^\w\-]', '_', f"{title}_{artist}")[:60]
        out_path  = YTDLP_CACHE / f"{safe}.%(ext)s"
        final_mp3 = YTDLP_CACHE / f"{safe}.mp3"

        if final_mp3.exists():
            print(f"    📦 Using cached YouTube audio: {final_mp3.name}")
            return str(final_mp3)

        # Use direct video_id if available (more accurate than search)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"    🎬 Downloading from YouTube video ID: {video_id}")
        else:
            url = f"ytsearch1:{title} {artist} official audio"
            print(f"    🎬 Searching YouTube: {title} {artist} official audio")

        result = subprocess.run([
            "yt-dlp", url,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--output", str(out_path),
            "--no-playlist",
            "--quiet",
            "--max-filesize", "20M",
        ], capture_output=True, text=True, timeout=120)

        if final_mp3.exists():
            print(f"    ✅ Downloaded: {final_mp3.name}")
            return str(final_mp3)
        else:
            print(f"    ❌ yt-dlp failed: {result.stderr[:200]}")
            return None

    except Exception as e:
        print(f"    ⚠️  YouTube download error: {e}")
        return None


def cleanup_youtube_cache():
    """Remove downloaded YouTube audio files to free disk space."""
    if not YTDLP_CACHE.exists():
        return
    import shutil, time
    time.sleep(1)  # wait for yt-dlp to release file handles on Windows
    shutil.rmtree(YTDLP_CACHE, ignore_errors=True)
    if not YTDLP_CACHE.exists():
        print(f"🧹 Cleaned up YouTube cache")
    else:
        for f in YTDLP_CACHE.glob("*"):
            try: f.unlink()
            except Exception: pass
        print(f"🧹 Partially cleaned YouTube cache (delete ytdlp_cache/ manually if needed)")


# ─────────────────────────────────────────────────────────────
# PRIORITY 3: Strict Genius result validation
# Use Claude to verify Genius returned the RIGHT song
# before accepting the lyrics
# ─────────────────────────────────────────────────────────────

def validate_genius_result(expected_title: str, expected_artist: str,
                           returned_title: str, returned_artist: str,
                           lyrics_preview: str) -> dict:
    """
    Ask Claude to verify if the Genius result actually matches
    the song we were looking for.
    Returns: { is_correct: bool, confidence: int, reason: str }
    """
    prompt = f"""Verify if a Genius search returned the correct song.

We searched for: "{expected_title}" by {expected_artist}
Genius returned: "{returned_title}" by {returned_artist}
Lyrics preview (first 300 chars):
---
{lyrics_preview[:300]}
---

Is this the correct song? Consider:
- Title match (exact or close enough)
- Artist match (could be featuring artists, solo vs band)
- Lyrics language and content match the expected song

Respond with ONLY a JSON object:
{{
  "is_correct": <true/false>,
  "confidence": <0-100>,
  "reason": "<one sentence explanation>"
}}"""

    response = call_claude(prompt)
    try:
        clean = re.sub(r"```(?:json)?|```", "", response).strip()
        return json.loads(clean)
    except Exception:
        # Default to accepting if we can't validate
        return {"is_correct": True, "confidence": 50, "reason": "Could not validate"}


def fetch_genius(title: str, artist: str, title_only: bool = False,
                 reject_non_english: bool = False) -> dict | None:
    script = find_script("genius_lyrics.py")
    if not script:
        print("    ⚠️  genius_lyrics.py not found")
        return None

    py = "python.exe" if sys.platform == "win32" else "python3"
    args = [py, str(script), title]
    if not title_only:
        args.append(artist or "")

    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        result = json.loads(p.stdout.strip() or "{}")
        if not result.get("ok"):
            return None

        # Reject translated versions
        song_title = (result.get("title") or "").lower()
        if any(kw in song_title for kw in BAD_TITLE_KEYWORDS):
            print(f"    ⚠️  Rejected translated Genius result: {result.get('title')}")
            return None

        if reject_non_english:
            lyrics = result.get("lyrics", "")
            non_ascii = sum(1 for c in lyrics if ord(c) > 127)
            if non_ascii / max(len(lyrics), 1) > 0.08:
                print(f"    ⚠️  Rejected non-English Genius result")
                return None

        # ── PRIORITY 3: Validate Genius returned correct song ──
        returned_title  = result.get("title") or ""
        returned_artist = result.get("artist") or ""
        lyrics_preview  = result.get("lyrics") or ""

        print(f"    🔍 Validating Genius result: '{returned_title}' by {returned_artist}")
        validation = validate_genius_result(
            title, artist,
            returned_title, returned_artist,
            lyrics_preview
        )

        if not validation.get("is_correct", True):
            confidence = validation.get("confidence", 50)
            reason = validation.get("reason", "")
            print(f"    ⚠️  Genius wrong song (confidence {confidence}): {reason}")
            return None

        print(f"    ✅ Genius result validated (confidence {validation.get('confidence')}%)")
        return result

    except Exception as e:
        print(f"    ⚠️  Genius error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# YOUTUBE CAPTIONS FETCHER
# Uses youtube-transcript-api to get captions instantly
# Much faster than downloading audio + Whisper
# ─────────────────────────────────────────────────────────────

def fetch_youtube_captions(video_id: str, title: str, artist: str) -> dict | None:
    """
    Fetch captions/transcript from YouTube video.
    Compatible with youtube-transcript-api v1.x
    """
    if not video_id:
        print("    ⚠️  No YouTube video ID available")
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("    ⚠️  youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
        return None

    try:
        print(f"    📺 Fetching YouTube captions for video: {video_id}")

        # v1.x API — fetch directly with language preference
        transcript_data = None
        lang_used = "en"

        # Try English first, then any language
        for lang_list in [["en", "en-US", "en-GB"], None]:
            try:
                if lang_list:
                    transcript_data = YouTubeTranscriptApi.get_transcript(
                        video_id, languages=lang_list
                    )
                else:
                    transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
                    lang_used = "unknown"
                print(f"    ✅ Got captions ({len(transcript_data)} segments)")
                break
            except Exception:
                continue

        if not transcript_data:
            print(f"    ❌ No captions available for video: {video_id}")
            return None

        # Build lyrics from segments, filter out sound descriptions
        lines = []
        for segment in transcript_data:
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            if re.match(r'^\[.*\]$', text):  # [Music], [Applause] etc
                continue
            if text in ("♪", "♫", "🎵", "🎶"):
                continue
            lines.append(text)

        if not lines:
            print(f"    ❌ Captions were empty or only music notes")
            return None

        lyrics = "\n".join(lines).strip()
        romanised = romanise_text(lyrics, lang_used)

        print(f"    ✅ Got {len(lines)} lines ({len(lyrics)} chars)")

        return {
            "ok": True,
            "text": lyrics,
            "romanised": romanised,
            "language": lang_used,
            "source": "youtube_captions",
        }

    except Exception as e:
        print(f"    ⚠️  YouTube captions error: {e}")
        return None


def fetch_whisper(audio_path: str, no_vad: bool = False) -> dict | None:
    if not audio_path or not Path(audio_path).exists():
        print(f"    ⚠️  Audio file not found: {audio_path}")
        return None

    script = find_script("whisper_lyrics.py")
    if not script:
        print("    ⚠️  whisper_lyrics.py not found")
        return None

    py = "python.exe" if sys.platform == "win32" else "python3"
    args = [py, str(script), audio_path]
    if no_vad:
        args.append("--no-vad")

    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=300,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        result = json.loads(p.stdout.strip() or "{}")
        return result if result.get("ok") else None
    except Exception as e:
        print(f"    ⚠️  Whisper error: {e}")
        return None


def detect_script(text: str) -> str:
    """Detect what script/language family the text is in."""
    for ch in text:
        o = ord(ch)
        if 0x0C00 <= o <= 0x0C7F: return "telugu"
        if 0x0900 <= o <= 0x097F: return "devanagari"
        if 0x0B80 <= o <= 0x0BFF: return "tamil"
        if 0x0D00 <= o <= 0x0D7F: return "malayalam"
        if 0x0C80 <= o <= 0x0CFF: return "kannada"
        if 0x0A00 <= o <= 0x0A7F: return "gurmukhi"
        if 0x0980 <= o <= 0x09FF: return "bengali"
        if 0xAC00 <= o <= 0xD7A3: return "korean"
        if 0x3040 <= o <= 0x30FF: return "japanese"
        if 0x4E00 <= o <= 0x9FFF: return "chinese"
        if 0x0600 <= o <= 0x06FF: return "arabic"
    return "roman"  # already Roman script


def romanise_indic(text: str, script: str) -> str:
    """Romanise Indic scripts using indic_transliteration."""
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        scheme_map = {
            "telugu":     sanscript.TELUGU,
            "devanagari": sanscript.DEVANAGARI,
            "tamil":      sanscript.TAMIL,
            "malayalam":  sanscript.MALAYALAM,
            "kannada":    sanscript.KANNADA,
            "gurmukhi":   sanscript.GURMUKHI,
            "bengali":    sanscript.BENGALI,
        }
        scheme = scheme_map.get(script)
        if scheme:
            return transliterate(text, scheme, sanscript.ITRANS)
        return text
    except Exception:
        return text


def romanise_with_claude(text: str, language: str) -> str:
    """
    Use Claude to phonetically romanise non-English Roman-script lyrics
    (Spanish, French, Portuguese, Korean romanisation etc.)
    so users can sing along even if they don't know the language.
    """
    # Only send first 2000 chars to keep API cost low
    preview = text[:2000]
    is_truncated = len(text) > 2000

    prompt = f"""Phonetically romanise these {language} lyrics so an English speaker can sing along.

Rules:
- Write how the words SOUND in English phonetics, not a translation
- Keep the same line breaks as the original
- Keep any English words exactly as they are
- For repeated sections, romanise each occurrence
- Return ONLY the romanised lyrics, nothing else

Example (Spanish):
Original: "Sí, sabes que ya llevo un rato mirándote"
Romanised: "Si, sabes ke ya yevo un rato mirandote"

Lyrics to romanise:
---
{preview}
---"""

    result = call_claude(prompt)

    if not result:
        return text  # fallback to original if Claude fails

    # If we truncated, append the rest untouched
    if is_truncated:
        result = result + "\n" + text[2000:]

    return result


def romanise_text(text: str, language: str = "") -> str:
    """
    Smart romanisation:
    - Indic scripts → indic_transliteration library
    - Korean/Japanese/Chinese/Arabic → Claude phonetic romanisation
    - Spanish/French/Portuguese etc (Roman script) → Claude phonetic romanisation
    - English → return as-is
    """
    if not text:
        return text

    script = detect_script(text)

    # Already English Roman script → no romanisation needed
    if script == "roman" and language.lower() in ("en", "english", ""):
        return text

    # Indic scripts → use library (fast, accurate)
    if script in ("telugu", "devanagari", "tamil", "malayalam", "kannada", "gurmukhi", "bengali"):
        print(f"    🔤 Romanising {script} script with indic_transliteration...")
        return romanise_indic(text, script)

    # Non-Roman scripts (Korean, Japanese, Chinese, Arabic) → Claude
    if script in ("korean", "japanese", "chinese", "arabic"):
        print(f"    🔤 Romanising {script} script with Claude...")
        return romanise_with_claude(text, script)

    # Roman script but non-English language (Spanish, French, Portuguese etc)
    # → Claude phonetic romanisation so users can sing along
    if script == "roman" and language.lower() not in ("en", "english", ""):
        print(f"    🔤 Phonetically romanising {language} lyrics with Claude...")
        return romanise_with_claude(text, language)

    return text


def clean_headers(lyrics: str) -> str:
    lines = lyrics.split("\n")
    clean = [
        line for line in lines
        if not re.match(r'^\[.{2,40}\]$', line.strip())
        and "Contributor" not in line
        and not line.strip().endswith("Lyrics")
    ]
    return "\n".join(clean).strip()


# ─────────────────────────────────────────────────────────────
# EXECUTE STRATEGY
# ─────────────────────────────────────────────────────────────

def execute_strategy(strategy: str, title: str, artist: str,
                     audio_path: str, current_lyrics: str,
                     language: str = "", video_id: str = "") -> dict | None:
    """Execute a strategy and return new lyrics dict or None."""

    print(f"    🎯 Executing strategy: {strategy}")

    if strategy == "genius_search":
        result = fetch_genius(title, artist)
        if result and result.get("lyrics"):
            return {
                "lyrics": clean_headers(result["lyrics"]),
                "romanised": clean_headers(result["lyrics"]),
                "source": "genius",
                "language": "en"
            }

    elif strategy == "genius_with_language_filter":
        result = fetch_genius(title, artist, reject_non_english=True)
        if result and result.get("lyrics"):
            return {
                "lyrics": clean_headers(result["lyrics"]),
                "romanised": clean_headers(result["lyrics"]),
                "source": "genius",
                "language": "en"
            }

    elif strategy == "genius_title_only":
        result = fetch_genius(title, artist, title_only=True)
        if result and result.get("lyrics"):
            return {
                "lyrics": clean_headers(result["lyrics"]),
                "romanised": clean_headers(result["lyrics"]),
                "source": "genius",
                "language": "en"
            }

    elif strategy == "youtube_captions":
        # Fast caption fetch — no download needed!
        result = fetch_youtube_captions(video_id, title, artist)
        if result and result.get("text"):
            return {
                "lyrics": result["text"],
                "romanised": result.get("romanised") or result["text"],
                "source": "youtube_captions",
                "language": result.get("language") or "en"
            }

    elif strategy in ("whisper_retry", "whisper_no_vad", "whisper_youtube"):
        no_vad = (strategy == "whisper_no_vad")
        audio  = audio_path

        # ── PRIORITY 2: No local audio → try YouTube download ──
        if not audio or not Path(audio).exists():
            print(f"    📡 No local audio, trying YouTube download...")
            audio = fetch_youtube_audio(title, artist, video_id=video_id)

        result = fetch_whisper(audio, no_vad=no_vad)
        if result and result.get("text"):
            return {
                "lyrics": result["text"],
                "romanised": result.get("romanised") or result["text"],
                "source": "whisper",
                "language": result.get("language") or "unknown"
            }

    elif strategy == "romanise_only":
        if current_lyrics:
            romanised = romanise_text(current_lyrics, language)
            return {
                "lyrics": current_lyrics,
                "romanised": romanised,
                "source": "agent_romanised",
                "language": language or "romanised"
            }

    elif strategy == "clean_headers":
        if current_lyrics:
            cleaned = clean_headers(current_lyrics)
            return {
                "lyrics": cleaned,
                "romanised": cleaned,
                "source": "agent_cleaned",
                "language": "en"
            }

    return None


# ─────────────────────────────────────────────────────────────
# SAVE / COMMIT
# ─────────────────────────────────────────────────────────────

def save_for_review(song_id: int, title: str, artist: str,
                    attempts: list[dict], best: dict,
                    old_lyrics: str, flagged: bool):
    REVIEW_DIR.mkdir(exist_ok=True)
    safe = re.sub(r'[^\w\-]', '_', f"{title}_{artist}")[:60]
    folder = REVIEW_DIR / f"{song_id}_{safe}"
    folder.mkdir(exist_ok=True)

    (folder / "old_lyrics.txt").write_text(old_lyrics or "(empty)", encoding="utf-8")

    if best:
        (folder / "new_lyrics.txt").write_text(best.get("lyrics") or "", encoding="utf-8")
        if best.get("romanised") and best["romanised"] != best.get("lyrics"):
            (folder / "new_romanised.txt").write_text(best["romanised"], encoding="utf-8")

    meta = {
        "song_id": song_id,
        "title": title,
        "artist": artist,
        "flagged_for_manual_review": flagged,
        "approved": None,
        "attempts": attempts,
        "best_score": best.get("score", 0) if best else 0,
        "best_source": best.get("source") if best else None,
        "timestamp": datetime.now().isoformat(),
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


def commit_to_db(conn):
    if not REVIEW_DIR.exists():
        print("No review folder. Run agent first.")
        return

    committed = skipped = rejected = 0

    for folder in sorted(REVIEW_DIR.iterdir()):
        if not folder.is_dir():
            continue

        meta_path    = folder / "meta.json"
        new_lyr_path = folder / "new_lyrics.txt"
        new_rom_path = folder / "new_romanised.txt"

        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        if meta.get("committed"):
            continue

        if meta.get("approved") is False:
            print(f"  ⏭️  Rejected: {meta['title']}")
            rejected += 1
            continue

        if meta.get("flagged_for_manual_review") and meta.get("approved") is None:
            print(f"  🚩 Flagged (needs approval): {meta['title']}")
            skipped += 1
            continue

        if not new_lyr_path.exists():
            skipped += 1
            continue

        song_id     = meta["song_id"]
        new_lyrics  = new_lyr_path.read_text(encoding="utf-8").strip()
        new_roman   = (new_rom_path.read_text(encoding="utf-8").strip()
                       if new_rom_path.exists() else new_lyrics)
        source      = meta.get("best_source") or "agent"

        # Get language from last attempt
        attempts = meta.get("attempts", [])
        language = attempts[-1].get("language", "en") if attempts else "en"

        try:
            with conn.cursor() as cur:
                # Update fct_songs gold layer directly
                cur.execute("""
                    UPDATE fct_songs_with_lyrics SET
                        lyrics_text      = %s,
                        romanised_text   = %s,
                        lyrics_language  = %s,
                        lyrics_source    = %s,
                        lyrics_updated_at = NOW()
                    WHERE song_id = %s
                """, (new_lyrics, new_roman, language, source, song_id))

                if cur.rowcount == 0:
                    print(f"  ⚠️  song_id {song_id} not found in fct_songs")
                    skipped += 1
                    conn.rollback()
                    continue

            conn.commit()

            meta["committed"] = True
            meta["committed_at"] = datetime.now().isoformat()
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"  ✅ Committed: {meta['title']} — {meta['artist']}")
            committed += 1
        except Exception as e:
            conn.rollback()
            print(f"  ❌ Failed: {meta['title']}: {e}")

    print(f"\n  Committed={committed}, Skipped={skipped}, Rejected={rejected}")


# ─────────────────────────────────────────────────────────────
# CORE AGENT LOOP — one song
# ─────────────────────────────────────────────────────────────

def process_song(row: dict, memory: StrategyMemory, dry_run: bool) -> dict:
    """
    Full agentic loop for one song.
    Returns result dict with final status.
    """
    title      = row["title"] or ""
    artist     = row["artist"] or ""
    song_id    = row["song_id"]
    audio      = row.get("local_file_path") or ""
    video_id   = row.get("youtube_video_id") or ""
    language   = row.get("detected_language") or "en"
    source     = row.get("source") or "none"
    lyrics     = row.get("lyrics_text") or ""
    romanised  = row.get("romanised_text") or ""

    print(f"\n{'─'*55}")
    print(f"🎵 {title} — {artist}")
    print(f"   Source: {source} | Lang: {language} | Chars: {len(lyrics)}")

    # ── Step 1: Initial evaluation ───────────────────────────
    print(f"   🤖 Claude evaluating...")
    evaluation = evaluate_lyrics(title, artist, lyrics, language, source)
    score  = evaluation.get("score", 0)
    issues = evaluation.get("issues", [])

    print(f"   📊 Score: {score}/100 | Issues: {', '.join(issues) or 'none'}")
    print(f"   💬 {evaluation.get('diagnosis', '')}")

    if score >= QUALITY_THRESHOLD:
        print(f"   ✅ Quality OK — no fix needed")
        memory.update_stats(fixed=False)
        return {"status": "ok", "score": score, "song_id": song_id}

    if dry_run:
        return {"status": "needs_fix", "score": score, "issues": issues, "song_id": song_id}

    # ── Fast path: NEEDS_ROMANISATION only ───────────────────
    # If the only issue is missing romanisation, just romanise
    # existing lyrics — no need to re-fetch anything
    if issues == ["NEEDS_ROMANISATION"] and lyrics:
        print(f"   🔤 Fast path: romanising existing lyrics...")
        romanised_new = romanise_text(lyrics, language)
        if romanised_new and romanised_new != lyrics:
            best_result = {
                "lyrics": lyrics,
                "romanised": romanised_new,
                "source": row.get("source") or "agent_romanised",
                "language": language,
                "score": 92,
            }
            review_folder = save_for_review(
                song_id=song_id, title=title, artist=artist,
                attempts=[{"attempt": 0, "strategy": "romanise_only",
                           "score": 92, "issues": [], "language": language,
                           "source": "agent_romanised",
                           "diagnosis": "Romanised existing lyrics"}],
                best=best_result,
                old_lyrics=lyrics,
                flagged=False,
            )
            print(f"   ✅ Romanised! Saved: {review_folder.name}")
            memory.update_stats(fixed=True)
            return {"status": "fixed", "score": 92, "song_id": song_id, "attempts": 1}

    # ── Step 2: Agentic retry loop ───────────────────────────
    attempts = [{
        "attempt": 0,
        "strategy": "initial",
        "score": score,
        "issues": issues,
        "diagnosis": evaluation.get("diagnosis"),
        "lyrics_preview": lyrics[:200],
        "language": language,
        "source": source,
    }]

    best_result = None
    best_score  = score

    for attempt_num in range(1, MAX_ATTEMPTS + 1):
        print(f"\n   🔄 Attempt {attempt_num}/{MAX_ATTEMPTS}")

        # Ask Claude to decide next strategy
        strategy = decide_next_strategy(
            title, artist, language, attempts, memory,
            has_video_id=bool(video_id),
            has_local_audio=bool(audio and Path(audio).exists())
        )

        if strategy == "manual_review":
            print(f"   🚩 Claude decided: flag for manual review")
            break

        # Execute the strategy
        result = execute_strategy(strategy, title, artist, audio, lyrics, language, video_id)

        if not result:
            print(f"   ❌ Strategy '{strategy}' returned nothing")
            attempts.append({
                "attempt": attempt_num,
                "strategy": strategy,
                "score": 0,
                "issues": ["FETCH_FAILED"],
                "diagnosis": "Strategy returned no lyrics",
                "language": language,
                "source": strategy,
            })
            continue

        new_lyrics   = result.get("lyrics") or ""
        new_language = result.get("language") or language

        # ── Step 3: Claude evaluates new lyrics ─────────────
        print(f"   🤖 Claude evaluating new lyrics ({len(new_lyrics)} chars)...")
        new_eval = evaluate_lyrics(title, artist, new_lyrics, new_language, strategy)
        new_score = new_eval.get("score", 0)
        new_issues = new_eval.get("issues", [])

        print(f"   📊 New score: {new_score}/100 | Issues: {', '.join(new_issues) or 'none'}")
        print(f"   💬 {new_eval.get('diagnosis', '')}")

        attempt_record = {
            "attempt": attempt_num,
            "strategy": strategy,
            "score": new_score,
            "issues": new_issues,
            "diagnosis": new_eval.get("diagnosis"),
            "lyrics_preview": new_lyrics[:200],
            "language": new_language,
            "source": strategy,
        }
        attempts.append(attempt_record)

        # Track best result so far
        if new_score > best_score:
            best_score  = new_score
            best_result = {**result, "score": new_score, "language": new_language}
            lyrics = new_lyrics  # update current for next iteration

        # ── Step 4: Record to memory ─────────────────────────
        primary_issue = issues[0] if issues else "UNKNOWN"
        if new_score >= QUALITY_THRESHOLD:
            memory.record_success(language, primary_issue, strategy, new_score)
            print(f"   ✅ Quality threshold reached! Score: {new_score}/100")
            break
        else:
            print(f"   ⚠️  Still below threshold ({new_score} < {QUALITY_THRESHOLD})")
            # Update issues for next iteration
            issues = new_issues

        # Rate limit protection
        time.sleep(0.5)

    # ── Step 5: Final decision ───────────────────────────────
    flagged = best_score < QUALITY_THRESHOLD

    if flagged:
        memory.record_failure(title, artist, issues[0] if issues else "UNKNOWN")
        print(f"\n   🚩 Flagging for manual review (best score: {best_score}/100)")
    else:
        print(f"\n   🎉 Fixed! Best score: {best_score}/100")

    # Save to review folder
    review_folder = save_for_review(
        song_id=song_id,
        title=title,
        artist=artist,
        attempts=attempts,
        best=best_result,
        old_lyrics=row.get("lyrics_text") or "",
        flagged=flagged,
    )
    print(f"   💾 Saved: {review_folder.name}")

    memory.update_stats(fixed=not flagged)

    return {
        "status": "flagged" if flagged else "fixed",
        "score": best_score,
        "song_id": song_id,
        "attempts": len(attempts),
    }


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    global REVIEW_DIR, QUALITY_THRESHOLD

    ap = argparse.ArgumentParser(description="Amethyst Lyrics AI Agent")
    ap.add_argument("--dry-run",     action="store_true", help="Evaluate only, no fixes")
    ap.add_argument("--commit",      action="store_true", help="Commit reviewed fixes to DB")
    ap.add_argument("--show-memory", action="store_true", help="Show strategy memory and exit")
    ap.add_argument("--title",  default="", help="Process only this song title")
    ap.add_argument("--artist", default="", help="Artist filter (use with --title)")
    ap.add_argument("--review-dir", default="lyrics_review", help="Review folder path")
    ap.add_argument("--keep-cache",  action="store_true", help="Keep downloaded YouTube audio cache")
    ap.add_argument("--threshold", type=int, default=QUALITY_THRESHOLD,
                    help=f"Quality threshold 0-100 (default: {QUALITY_THRESHOLD})")
    args = ap.parse_args()

    REVIEW_DIR = Path(args.review_dir)
    QUALITY_THRESHOLD = args.threshold

    # ── Show memory ──────────────────────────────────────────
    if args.show_memory:
        memory = StrategyMemory()
        print("\n📚 Strategy Memory:")
        print(json.dumps(memory.memory, indent=2, ensure_ascii=False))
        return 0

    # ── DB connection ────────────────────────────────────────
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Connected to music_db")
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        return 1

    try:
        # ── Commit mode ──────────────────────────────────────
        if args.commit:
            print("\n📥 Committing reviewed fixes to DB...")
            commit_to_db(conn)
            return 0

        # ── Load songs from GOLD LAYER ───────────────────────
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if args.title:
                cur.execute("""
                    SELECT
                        song_id,
                        title,
                        artist,
                        local_file_path,
                        youtube_video_id,
                        lyrics_text,
                        romanised_text,
                        lyrics_language   AS detected_language,
                        lyrics_source     AS source
                    FROM fct_songs_with_lyrics
                    WHERE title IS NOT NULL
                    AND LOWER(TRIM(title)) = LOWER(TRIM(%s))
                    LIMIT 1
                """, (args.title,))
            else:
                cur.execute("""
                    SELECT
                        song_id,
                        title,
                        artist,
                        local_file_path,
                        youtube_video_id,
                        lyrics_text,
                        romanised_text,
                        lyrics_language   AS detected_language,
                        lyrics_source     AS source
                    FROM fct_songs_with_lyrics
                    WHERE title IS NOT NULL
                    ORDER BY title ASC
                """)
            songs = [dict(r) for r in cur.fetchall()]

        print(f"\n🎵 Found {len(songs)} songs to process")
        if args.dry_run:
            print("   (DRY RUN — no changes will be made)\n")

        # ── Agent memory ─────────────────────────────────────
        memory = StrategyMemory()

        # ── Process each song ────────────────────────────────
        results = []
        for row in songs:
            result = process_song(row, memory, dry_run=args.dry_run)
            results.append(result)
            time.sleep(0.3)  # gentle rate limiting

        # ── Clean up YouTube downloads ────────────────────────
        if not args.keep_cache and YTDLP_CACHE.exists():
            cleanup_youtube_cache()

        # ── Final summary ────────────────────────────────────
        ok      = sum(1 for r in results if r["status"] == "ok")
        fixed   = sum(1 for r in results if r["status"] == "fixed")
        flagged = sum(1 for r in results if r["status"] == "flagged")
        needs   = sum(1 for r in results if r["status"] == "needs_fix")

        print(f"\n{'='*55}")
        print("AGENT RUN COMPLETE")
        print(f"{'='*55}")
        print(f"  Total:           {len(results)}")
        print(f"  ✅ Already OK:   {ok}")
        print(f"  🔧 Fixed:        {fixed}")
        print(f"  🚩 Flagged:      {flagged}")
        if args.dry_run:
            print(f"  ⚠️  Needs fix:   {needs}")

        mem_stats = memory.memory["stats"]
        print(f"\n  📚 Memory stats:")
        print(f"     Total processed: {mem_stats['total_processed']}")
        print(f"     Total fixed:     {mem_stats['total_fixed']}")
        print(f"     Total failed:    {mem_stats['total_failed']}")

        if not args.dry_run and (fixed + flagged) > 0:
            print(f"\n  📁 Review folder: {REVIEW_DIR.resolve()}")
            print(f"  👀 Review the files, set 'approved: true/false' in meta.json")
            print(f"  Then run: python lyrics_ai_agent.py --commit")

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
