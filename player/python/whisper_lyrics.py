import json, sys, os, subprocess, tempfile
from faster_whisper import WhisperModel

# ensure utf-8 output on windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─────────────────────────────────────────────
# Convert any audio format to WAV
# Whisper works best with 16khz mono WAV
# ─────────────────────────────────────────────
def convert_to_wav(path):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    subprocess.run([
        "ffmpeg", "-y",
        "-i", path,
        "-ac", "1",       # mono
        "-ar", "16000",   # 16khz sample rate
        tmp.name
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp.name

# ─────────────────────────────────────────────
# Romanise text based on detected script
# Handles: Telugu, Hindi, Tamil, Malayalam,
#          Kannada, Punjabi, Bengali
# English and other Roman scripts → unchanged
# ─────────────────────────────────────────────
def to_roman(text: str) -> str:
    if not text:
        return text
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        # Detect script by Unicode range
        has_telugu   = any("\u0C00" <= ch <= "\u0C7F" for ch in text)
        has_deva     = any("\u0900" <= ch <= "\u097F" for ch in text)
        has_tamil    = any("\u0B80" <= ch <= "\u0BFF" for ch in text)
        has_malayalam= any("\u0D00" <= ch <= "\u0D7F" for ch in text)
        has_kannada  = any("\u0C80" <= ch <= "\u0CFF" for ch in text)
        has_gurmukhi = any("\u0A00" <= ch <= "\u0A7F" for ch in text)
        has_bengali  = any("\u0980" <= ch <= "\u09FF" for ch in text)

        if has_telugu:
            return transliterate(text, sanscript.TELUGU, sanscript.ITRANS)
        if has_deva:
            return transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
        if has_tamil:
            return transliterate(text, sanscript.TAMIL, sanscript.ITRANS)
        if has_malayalam:
            return transliterate(text, sanscript.MALAYALAM, sanscript.ITRANS)
        if has_kannada:
            return transliterate(text, sanscript.KANNADA, sanscript.ITRANS)
        if has_gurmukhi:
            return transliterate(text, sanscript.GURMUKHI, sanscript.ITRANS)
        if has_bengali:
            return transliterate(text, sanscript.BENGALI, sanscript.ITRANS)

        # Already Roman script (English, Spanish, French etc)
        return text

    except Exception:
        return text

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
try:
    audio_path = sys.argv[1]

    # Convert to WAV
    wav = convert_to_wav(audio_path)

    # Load Whisper model
    # "small" = good balance of speed and accuracy
    model = WhisperModel("small", device="cpu", compute_type="int8")

    # Transcribe with AUTO language detection
    # No language= parameter means Whisper detects it!
    segments, info = model.transcribe(
        wav,
        task="transcribe",
        vad_filter=True      # filters out silence automatically
    )

    # Collect segments with timestamps
    segment_list = list(segments)

    # Build full lyrics text (original script)
    original_lines = []
    for s in segment_list:
        t = (s.text or "").strip()
        if t:
            original_lines.append(t)

    original_text = "\n".join(original_lines).strip()

    # Romanise the full text
    romanised_text = to_roman(original_text)

    # Build karaoke cues with timestamps
    karaoke_cues = []
    for s in segment_list:
        t = (s.text or "").strip()
        if t:
            karaoke_cues.append({
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "text": t,
                "romanised": to_roman(t)
            })

    # Clean up temp WAV file
    try:
        os.remove(wav)
    except:
        pass

    # Return everything to main.js
    print(json.dumps({
        "ok": True,
        "text": original_text,           # original script
        "romanised": romanised_text,     # romanised version
        "language": info.language,       # detected language code
        "cues": karaoke_cues            # timestamped lines for karaoke
    }, ensure_ascii=False))

except Exception as e:
    print(json.dumps({
        "ok": False,
        "error": str(e)
    }, ensure_ascii=False))