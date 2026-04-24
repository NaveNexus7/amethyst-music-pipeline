#!/usr/bin/env python3
"""
Lyrics Quality Agent for Amethyst Library

Scans amethyst_library/<trackId>/ folders, checks song.txt quality,
and if it looks bad (too short / garbage), it regenerates using better settings.

Usage:
  python lyrics_agent.py --library "..\amethyst_library"
"""

from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip()[:1500])
    return p.stdout

def looks_bad(txt: str) -> bool:
    t = (txt or "").strip()
    if len(t) < 60:                 # too short for a song → likely incomplete
        return True
    if t == "..." or t.count("...") >= 2:
        return True
    # too many non-letter characters
    non_letters = sum(1 for c in t if not (c.isalpha() or c.isspace() or c in ".,'\"-?!"))
    if non_letters > max(30, int(len(t) * 0.25)):
        return True
    # repeated same line
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if len(lines) >= 3 and len(set(lines)) <= max(1, len(lines)//5):
        return True
    return False

def update_meta(meta_path: Path, patch: dict):
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
    meta.setdefault("agent", {})
    meta["agent"].update(patch)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, help="Path to amethyst_library")
    ap.add_argument("--model", default="small", help="Retry model: base/small/medium")
    ap.add_argument("--language", default="auto", help="auto or te/hi/ta/en/pa...")
    ap.add_argument("--romanize", action="store_true", help="Pass romanize flag to pipeline")
    ap.add_argument("--no-vad", action="store_true", help="Disable VAD for songs")
    args = ap.parse_args()

    lib = Path(args.library).resolve()
    if not lib.exists():
        print("Library not found:", lib)
        return 2

    track_dirs = [p for p in lib.iterdir() if p.is_dir()]
    if not track_dirs:
        print("No track folders inside:", lib)
        return 2

    fixed = 0
    skipped = 0

    for td in track_dirs:
        txt = td / "song.txt"
        meta = td / "meta.json"

        if not txt.exists():
            update_meta(meta, {"status": "missing_song_txt"})
            continue

        content = txt.read_text(encoding="utf-8", errors="ignore")
        if not looks_bad(content):
            skipped += 1
            continue

        # We need source_path from meta.json to regenerate properly
        if not meta.exists():
            update_meta(meta, {"status": "bad_lyrics_no_meta"})
            continue

        meta_obj = json.loads(meta.read_text(encoding="utf-8", errors="ignore") or "{}")
        source_path = meta_obj.get("source_path")
        if not source_path:
            update_meta(meta, {"status": "bad_lyrics_no_source_path"})
            continue

        # Re-run pipeline for this ONE song (force) using improved settings
        # NOTE: uses build_library.py in same folder
        cmd = [
            sys.executable, "build_library.py",
            "--input", source_path,
            "--output", str(lib),
            "--model", args.model,
            "--language", args.language,
            "--force",
        ]
        if args.romanize:
            cmd.append("--romanize")
        if args.no_vad:
            cmd.append("--no-vad")

        try:
            run(cmd)
            update_meta(meta, {"status": "fixed", "retry_model": args.model, "language": args.language})
            fixed += 1
            print("✅ fixed:", td.name)
        except Exception as e:
            update_meta(meta, {"status": "fix_failed", "error": str(e)[:500]})
            print("❌ fix failed:", td.name, "->", str(e)[:200])

    print(f"Done. Fixed={fixed}, Skipped={skipped}, Total={len(track_dirs)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
