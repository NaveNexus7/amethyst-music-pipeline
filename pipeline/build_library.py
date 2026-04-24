#!/usr/bin/env python3
"""
Amethyst Music Pipeline (offline-first)

For every input audio file, this pipeline produces a standardized folder:

  <output>/<trackId>/
    song.m4a      # AAC audio (storage-optimized)
    song.txt      # lyrics text (one line per segment)
    song.lrc      # karaoke timing (LRC timestamps)
    meta.json     # metadata + pipeline info

WAV is used only as a TEMP working file for Whisper, then deleted.

Usage examples:
  python build_library.py --input "..\\songs_input" --output "..\\amethyst_library"

Better settings for songs:
  python build_library.py --input "..\\songs_input" --output "..\\amethyst_library" ^
    --language auto --romanize --no-vad --beam-size 5 --best-of 5 --temperature 0 --chunk-seconds 45 --force

Prereqs:
  - ffmpeg + ffprobe installed and on PATH
  - pip install faster-whisper
Optional:
  - pip install indic-transliteration (Telugu/Devanagari -> Roman)

Important note:
  ASR on songs is imperfect. Chunking + decoding improvements reduce missed sections.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List


# -----------------------------
# File types we accept as input
# -----------------------------
AUDIO_EXTS = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac",
    ".ogg", ".opus", ".wma", ".aiff", ".aif",
    ".mp4", ".webm"
}


# -----------------------------
# Small helpers
# -----------------------------
def ensure_utf8_stdio() -> None:
    """Windows console sometimes needs explicit UTF-8 for Indic text."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_cmd(cmd: List[str], quiet: bool = True) -> None:
    """Run a subprocess command and raise a readable error if it fails."""
    try:
        if quiet:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        else:
            p = subprocess.run(cmd)
    except FileNotFoundError as fe:
        raise RuntimeError(f"Command not found: {cmd[0]} (install it and add to PATH)") from fe

    if p.returncode != 0:
        err = (p.stderr or "").strip()
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{err[:1500]}")


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    """Best-effort duration using ffprobe (works for wav too)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path)
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            return None
        out = (p.stdout or "").strip()
        return float(out) if out else None
    except Exception:
        return None


def sha1_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Stable trackId: sha1 of the full file bytes (fine for small libraries)."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def list_audio_files(input_path: Path) -> List[Path]:
    """If input is a file -> [file], else scan folder recursively for audio files."""
    if input_path.is_file():
        return [input_path]

    files: List[Path] = []
    for p in input_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            files.append(p)
    return sorted(files)


def format_lrc_timestamp(seconds: float) -> str:
    """LRC timestamp format: [mm:ss.xx]"""
    if seconds < 0:
        seconds = 0.0
    mm = int(seconds // 60)
    ss = seconds - (mm * 60)
    return f"[{mm:02d}:{ss:05.2f}]"


def looks_like_garbage(text: str) -> bool:
    """Quick sanity check: detect obviously empty/garbage outputs."""
    t = (text or "").strip()
    if len(t) < 10:
        return True
    if t == "..." or t.count("...") >= 2:
        return True
    # too repetitive
    if len(set(t)) < 6 and len(t) > 20:
        return True
    return False


# -----------------------------
# Script detection + romanization
# -----------------------------
def detect_scripts(text: str) -> Tuple[bool, bool]:
    """Returns (has_telugu, has_devanagari)."""
    has_telugu = any("\u0C00" <= ch <= "\u0C7F" for ch in text)
    has_deva = any("\u0900" <= ch <= "\u097F" for ch in text)
    return has_telugu, has_deva


def translit_to_roman(text: str) -> str:
    """
    Telugu/Devanagari -> Roman (ITRANS).
    If indic_transliteration isn't installed, returns text unchanged.
    """
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        has_telugu, has_deva = detect_scripts(text)
        if has_telugu:
            return transliterate(text, sanscript.TELUGU, sanscript.ITRANS)
        if has_deva:
            return transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
        return text
    except Exception:
        return text


# -----------------------------
# Pipeline configuration
# -----------------------------
@dataclasses.dataclass
class PipelineConfig:
    model: str
    device: str
    compute_type: str
    language: Optional[str]  # None = auto
    romanize: bool

    bitrate_kbps: int
    force: bool
    max_files: Optional[int]
    vad_filter: bool

    # Better decoding for songs
    beam_size: int
    best_of: int
    temperature: float

    # Chunking is the biggest fix for "few lines only"
    chunk_seconds: int


# -----------------------------
# Audio stages
# -----------------------------
def ensure_m4a(src: Path, out_m4a: Path, bitrate_kbps: int, force: bool) -> None:
    """Convert any input to AAC .m4a for standardized storage."""
    if out_m4a.exists() and not force:
        return
    out_m4a.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vn",
        "-c:a", "aac",
        "-b:a", f"{bitrate_kbps}k",
        "-movflags", "+faststart",
        str(out_m4a),
    ]
    run_cmd(cmd, quiet=True)


def make_temp_wav(src: Path) -> Path:
    """Create a temp 16kHz mono WAV for ASR."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    out_wav = Path(tmp.name)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-ac", "1",
        "-ar", "16000",
        str(out_wav),
    ]
    run_cmd(cmd, quiet=True)
    return out_wav


def make_chunk_wav(wav: Path, start_s: float, dur_s: float) -> Path:
    """Extract a chunk from an existing WAV to another temp WAV."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    chunk_wav = Path(tmp.name)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav),
        "-ss", str(start_s),
        "-t", str(dur_s),
        "-ac", "1", "-ar", "16000",
        str(chunk_wav),
    ]
    run_cmd(cmd, quiet=True)
    return chunk_wav


# Whisper model singleton so we don't reload for each song
_WHISPER_MODEL_SINGLETON = None


def transcribe_to_txt_and_lrc(src_audio: Path, out_txt: Path, out_lrc: Path, cfg: PipelineConfig) -> dict:
    """
    Transcribe with faster-whisper using chunking + improved decoding.
    Generates:
      - song.txt (lyrics lines)
      - song.lrc (timestamps per line)

    Returns info dict for meta.json.
    """
    from faster_whisper import WhisperModel

    global _WHISPER_MODEL_SINGLETON

    # 1) Make a temp WAV for the entire song
    wav = make_temp_wav(src_audio)

    # 2) Load Whisper model once
    if _WHISPER_MODEL_SINGLETON is None:
        _WHISPER_MODEL_SINGLETON = WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type)
    model = _WHISPER_MODEL_SINGLETON

    # 3) Base ASR settings
    base_kwargs = dict(task="transcribe", vad_filter=cfg.vad_filter)
    if cfg.language:
        base_kwargs["language"] = cfg.language

    # 4) Decode settings (more accuracy / less skipping)
    decode_kwargs = dict(base_kwargs)
    decode_kwargs.update({
        "beam_size": cfg.beam_size,
        "best_of": cfg.best_of,
        "temperature": cfg.temperature,
    })

    # 5) Chunk loop (prevents missing big parts)
    all_segments = []
    info = None

    duration = ffprobe_duration_seconds(wav) or 0.0
    step = max(10, int(cfg.chunk_seconds))  # never below 10s
    t = 0.0

    while t < duration + 0.01:
        chunk_wav = None
        try:
            chunk_wav = make_chunk_wav(wav, t, step)
            segs, inf = model.transcribe(str(chunk_wav), **decode_kwargs)
            if info is None:
                info = inf

            for s in segs:
                # shift timestamps to global song timeline
                start = float(getattr(s, "start", 0.0) or 0.0) + t
                end = float(getattr(s, "end", 0.0) or 0.0) + t
                s.start = start
                s.end = end
                all_segments.append(s)

        finally:
            if chunk_wav is not None:
                try:
                    chunk_wav.unlink(missing_ok=True)
                except Exception:
                    pass

        t += step

    # 6) Convert segments -> lines + LRC
    lines: List[str] = []
    lrc_lines: List[str] = []

    for s in all_segments:
        seg_text = (getattr(s, "text", "") or "").strip()
        if not seg_text:
            continue

        if cfg.romanize:
            seg_text = translit_to_roman(seg_text)

        lines.append(seg_text)

        ts = format_lrc_timestamp(float(getattr(s, "start", 0.0) or 0.0))
        lrc_lines.append(f"{ts}{seg_text}")

    # cleanup temp main wav
    try:
        wav.unlink(missing_ok=True)
    except Exception:
        pass

    final_text = "\n".join(lines).strip()

    # 7) Write outputs
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(final_text + ("\n" if final_text else ""), encoding="utf-8")

    out_lrc.parent.mkdir(parents=True, exist_ok=True)
    out_lrc.write_text("\n".join(lrc_lines).strip() + ("\n" if lrc_lines else ""), encoding="utf-8")

    # 8) Return run metadata
    return {
        "detected_language": getattr(info, "language", None) if info else None,
        "language_probability": getattr(info, "language_probability", None) if info else None,
        "model": cfg.model,
        "device": cfg.device,
        "compute_type": cfg.compute_type,
        "vad_filter": cfg.vad_filter,
        "romanize": cfg.romanize,
        "forced_language": cfg.language,
        "beam_size": cfg.beam_size,
        "best_of": cfg.best_of,
        "temperature": cfg.temperature,
        "chunk_seconds": cfg.chunk_seconds,
        "segments_count": len(lrc_lines),
        "looks_like_garbage": looks_like_garbage(final_text),
    }


def write_meta(meta_path: Path, meta: dict) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one(file_path: Path, out_root: Path, cfg: PipelineConfig) -> Tuple[str, Path]:
    """Process one audio file -> standardized folder with artifacts."""
    track_id = sha1_of_file(file_path)
    track_dir = out_root / track_id

    audio_out = track_dir / "song.m4a"
    txt_out = track_dir / "song.txt"
    lrc_out = track_dir / "song.lrc"
    meta_out = track_dir / "meta.json"

    # skip if already built and not forcing regeneration
    if (not cfg.force) and audio_out.exists() and txt_out.exists() and lrc_out.exists() and meta_out.exists():
        return track_id, track_dir

    # Stage 1: standardize audio for storage
    ensure_m4a(file_path, audio_out, cfg.bitrate_kbps, cfg.force)

    # Stage 2: build lyrics + karaoke timing from ORIGINAL audio
    asr_info = transcribe_to_txt_and_lrc(file_path, txt_out, lrc_out, cfg)

    duration = ffprobe_duration_seconds(file_path)

    meta = {
        "trackId": track_id,
        "source_path": str(file_path),
        "source_name": file_path.name,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_seconds": duration,
        "outputs": {
            "audio": str(audio_out),
            "lyrics_txt": str(txt_out),
            "karaoke_lrc": str(lrc_out),
        },
        "pipeline": asr_info,
    }

    write_meta(meta_out, meta)
    return track_id, track_dir


# -----------------------------
# CLI
# -----------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Amethyst pipeline: audio -> m4a + txt + lrc + meta.")

    p.add_argument("--input", "-i", required=True, help="Input file or folder containing audio files.")
    p.add_argument("--output", "-o", required=True, help="Output library folder (per-track folders).")

    p.add_argument("--model", default="small", help="Whisper model size: tiny/base/small/medium/...")
    p.add_argument("--language", default="auto", help="Language code (te/ta/hi/en/pa) or 'auto'.")
    p.add_argument("--romanize", action="store_true", help="Romanize Telugu/Devanagari -> Latin (ITRANS).")

    p.add_argument("--bitrate", type=int, default=192, help="AAC bitrate kbps for .m4a output (default 192).")
    p.add_argument("--device", default="cpu", help="faster-whisper device: cpu or cuda (if available).")
    p.add_argument("--compute-type", default="int8", help="Compute type (cpu): int8 recommended.")
    p.add_argument("--force", action="store_true", help="Regenerate artifacts even if they exist.")
    p.add_argument("--max-files", type=int, default=None, help="Process only first N audio files (testing).")

    # Songs often suffer with VAD. You can disable it.
    p.add_argument("--no-vad", action="store_true", help="Disable VAD filter (often better for songs).")

    # Better decoding
    p.add_argument("--beam-size", type=int, default=5, help="Beam size for decoding (accuracy).")
    p.add_argument("--best-of", type=int, default=5, help="Best-of sampling (robustness).")
    p.add_argument("--temperature", type=float, default=0.0, help="Decoding temperature (0=stable).")

    # Chunking: prevents missing large sections (biggest fix for 'few lines only')
    p.add_argument("--chunk-seconds", type=int, default=45, help="Transcribe in chunks to avoid missed lines.")

    return p.parse_args()


def main() -> int:
    ensure_utf8_stdio()
    args = parse_args()

    in_path = Path(args.input).expanduser().resolve()
    out_root = Path(args.output).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    files = list_audio_files(in_path)
    if not files:
        print(f"No audio files found in: {in_path}", file=sys.stderr)
        return 2

    if args.max_files:
        files = files[: args.max_files]

    # language 'auto' -> None (let whisper detect)
    language = None if (args.language or "").lower() == "auto" else args.language

    cfg = PipelineConfig(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=language,
        romanize=args.romanize,
        bitrate_kbps=args.bitrate,
        force=args.force,
        max_files=args.max_files,
        vad_filter=not args.no_vad,
        beam_size=args.beam_size,
        best_of=args.best_of,
        temperature=args.temperature,
        chunk_seconds=args.chunk_seconds,
    )

    print(f"Amethyst Pipeline: {len(files)} file(s)")
    print(f"Input : {in_path}")
    print(f"Output: {out_root}")
    print(
        f"Model : {cfg.model} | lang={args.language} | romanize={cfg.romanize} | "
        f"aac={cfg.bitrate_kbps}kbps | vad={cfg.vad_filter} | "
        f"beam={cfg.beam_size} best_of={cfg.best_of} temp={cfg.temperature} chunk={cfg.chunk_seconds}s"
    )
    print("-" * 72)

    ok = 0
    failed = 0

    for idx, f in enumerate(files, start=1):
        try:
            track_id, track_dir = process_one(f, out_root, cfg)
            print(f"[{idx:02d}/{len(files):02d}] ✅ {f.name}")
            print(f"      trackId: {track_id}")
            print(f"      out    : {track_dir}")
            ok += 1
        except Exception as e:
            failed += 1
            print(f"[{idx:02d}/{len(files):02d}] ❌ {f.name}")
            print(f"      error: {e}")

    print("-" * 72)
    print(f"Done. Success={ok}, Failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
