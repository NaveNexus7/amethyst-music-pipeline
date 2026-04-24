#!/usr/bin/env python3
"""
genius_lyrics.py
Fetches lyrics from Genius API for English songs.
Usage: python genius_lyrics.py "Song Title" "Artist Name"
Returns JSON: {ok, lyrics, source}
"""

import sys
import json

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

GENIUS_TOKEN = "9EODBuM4Puttgx_oicJCIe9ezdXGdmfHX9dzgXS_wTLAN51PMHxjj7WR0-VMuCAv"

try:
    import lyricsgenius

    title  = sys.argv[1] if len(sys.argv) > 1 else ""
    artist = sys.argv[2] if len(sys.argv) > 2 else ""

    if not title:
        print(json.dumps({"ok": False, "error": "No title provided"}))
        sys.exit(0)

    # Connect to Genius
    genius = lyricsgenius.Genius(
        GENIUS_TOKEN,
        skip_non_songs=True,
        excluded_terms=["(Remix)", "(Live)", "(Cover)"],
        remove_section_headers=True  # removes [Chorus] [Verse] tags
    )
    genius.timeout = 10

    # Search for song
    song = genius.search_song(title, artist)

    if not song or not song.lyrics:
        print(json.dumps({
            "ok": False,
            "error": f"Not found on Genius: {title}"
        }))
        sys.exit(0)

    # Clean up lyrics
    lyrics = song.lyrics.strip()

    # Remove "contributor" text Genius sometimes adds at top
    lines = lyrics.split("\n")
    clean_lines = []
    skip_next = False

    for line in lines:
        # Skip lines like "123 ContributorsBlank Space Lyrics"
        if "Contributor" in line or line.endswith("Lyrics"):
            continue
        clean_lines.append(line)

    lyrics = "\n".join(clean_lines).strip()

    print(json.dumps({
        "ok": True,
        "lyrics": lyrics,
        "title": song.title,
        "artist": song.artist,
        "source": "genius"
    }, ensure_ascii=False))

except Exception as e:
    print(json.dumps({
        "ok": False,
        "error": str(e)
    }))