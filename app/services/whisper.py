"""
Speech-to-text using Groq Whisper large-v3 API with custom vocabulary support.
"""
from groq import Groq
from app.config import settings

# Common Finglish/technical terms to help Whisper recognize
DEFAULT_VOCABULARY = [
    # 3D/scanning terms
    "pointcloud", "point cloud", "CloudCompare", "mesh", "meshata", "meshaan",
    "skannata", "skannaan", "skanni", "3D-skanni", "LiDAR",
    "skannaus", "skannauksessa", "skannaukseen", "skannauksen",
    "pinta", "pinnat", "pinnan", "pintoja",
    "align", "alignata", "alignaan", "alignaa", "alignasin", "alignoin",
    # Cloud/upload
    "pilvi", "pilveen", "pilvestä", "cloud",
    # Software/tech
    "renderöi", "renderöin", "exporttaa", "importtaa", "softa",
    # Car/racing terms
    "drag car", "dragster", "turbo", "boost", "dyno",
    "ECU", "ecuun", "ecun", "ecua",  # engine control unit
    "pervo", "pervoja", "pervojen",  # rear wing/spoiler parts
    "visio", "visioita", "visioon",  # vision/design
    # General Finglish
    "upgradeta", "downloadaa", "uploadaa", "streamaa", "settingit",
]

# Auto-corrections for common Whisper mistakes (case-insensitive)
# Format: "wrong" -> "correct"
AUTO_CORRECTIONS = {
    # pervo (rear wing parts)
    "perhoja": "pervoja",
    "perhoa": "pervoa",
    "perho": "pervo",
    "perhot": "pervot",
    "perhojen": "pervojen",
    # align (3D scanning term)
    "ala-ain": "alignaan",
    "alainaan": "alignaan",
    "alainaa": "alignaa",
    "alainin": "alignin",
    "alain": "align",
    "ala-ainaan": "alignaan",
    # ECU (engine control unit)
    "EQ": "ECU",
    "eq": "ECU",
    # Add more as you find them
}


def apply_corrections(text: str) -> str:
    """Apply auto-corrections to transcript text."""
    import re
    result = text
    for wrong, correct in AUTO_CORRECTIONS.items():
        # Case-insensitive replacement, preserving original case
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        result = pattern.sub(correct, result)
    return result


def transcribe_audio(audio_path: str, custom_vocabulary: list = None, highlight_color: str = None, border: bool = True, border_color: str = None, width: int = 1080, height: int = 1920, position: str = "bottom") -> dict:
    """
    Transcribe audio using Groq Whisper large-v3 API.

    Args:
        audio_path: Path to audio file
        custom_vocabulary: Additional words/phrases to help recognition

    Returns:
        dict with transcript text and SRT content
    """
    client = Groq(api_key=settings.groq_api_key)

    # Build prompt with vocabulary hints
    vocab = DEFAULT_VOCABULARY.copy()
    if custom_vocabulary:
        vocab.extend(custom_vocabulary)

    # Whisper prompt - include expected words/phrases
    prompt = (
        "This is Finnish speech that may include English technical terms. "
        "Common words: " + ", ".join(vocab[:50])  # Limit prompt length
    )

    # Get transcript with word-level timestamps
    with open(audio_path, "rb") as f:
        # Groq's API with verbose_json for timestamps
        response = client.audio.transcriptions.create(
            model="whisper-large-v3",  # Full large-v3, not turbo
            file=f,
            language="fi",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            prompt=prompt
        )

    # Extract transcript and apply auto-corrections
    transcript = apply_corrections(response.text)

    # Build SRT from word timestamps if available
    srt_segments = []
    segment_index = 1

    if hasattr(response, 'words') and response.words:
        # Use word-level timestamps
        word_buffer = []
        for word_info in response.words:
            # Handle both dict and object responses (Groq vs OpenAI)
            if isinstance(word_info, dict):
                word = word_info.get("word", "")
                start = word_info.get("start", 0)
                end = word_info.get("end", 0)
            else:
                word = word_info.word
                start = word_info.start
                end = word_info.end
            word_buffer.append({
                "word": apply_corrections(word),
                "start": start,
                "end": end,
            })

            # Create segment every 4-5 words or at punctuation
            if len(word_buffer) >= 4 or (word_buffer and word_buffer[-1]["word"].rstrip().endswith((".", "!", "?", ","))):
                srt_segments.append({
                    "index": segment_index,
                    "start": word_buffer[0]["start"],
                    "end": word_buffer[-1]["end"],
                    "text": " ".join(w["word"].strip() for w in word_buffer).strip()
                })
                segment_index += 1
                word_buffer = []

        # Don't forget remaining words
        if word_buffer:
            srt_segments.append({
                "index": segment_index,
                "start": word_buffer[0]["start"],
                "end": word_buffer[-1]["end"],
                "text": " ".join(w["word"].strip() for w in word_buffer).strip()
            })

    elif hasattr(response, 'segments') and response.segments:
        # Fall back to segment-level timestamps
        for seg in response.segments:
            srt_segments.append({
                "index": segment_index,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip()
            })
            segment_index += 1

    # Convert to SRT format
    srt_content = segments_to_srt(srt_segments)

    # Generate karaoke ASS if we have word timestamps
    ass_content = ""
    word_list = []
    if hasattr(response, 'words') and response.words:
        for w in response.words:
            if isinstance(w, dict):
                word_list.append({
                    "word": apply_corrections(w.get("word", "")),
                    "start": w.get("start", 0),
                    "end": w.get("end", 0)
                })
            else:
                word_list.append({
                    "word": apply_corrections(w.word),
                    "start": w.start,
                    "end": w.end
                })
        ass_content = generate_karaoke_ass(word_list, video_width=width, video_height=height, highlight_color=highlight_color or "#66FF00", border=border, border_color=border_color or "#000000", position=position)

    return {
        "transcript": transcript,
        "srt": srt_content,
        "ass": ass_content,
        "words": word_list,
    }


def segments_to_srt(segments: list) -> str:
    """Convert segments to SRT format."""
    srt_lines = []
    for seg in segments:
        srt_lines.append(str(seg["index"]))
        srt_lines.append(f"{seconds_to_srt_time(seg['start'])} --> {seconds_to_srt_time(seg['end'])}")
        srt_lines.append(seg["text"])
        srt_lines.append("")
    return "\n".join(srt_lines)


def parse_srt(srt_content: str) -> list:
    """
    Parse SRT content into list of segments.
    Returns list of {index, start, end, text}
    """
    segments = []
    blocks = srt_content.strip().split("\n\n")

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            try:
                index = int(lines[0])
                times = lines[1].split(" --> ")
                start = srt_time_to_seconds(times[0])
                end = srt_time_to_seconds(times[1])
                text = " ".join(lines[2:])

                segments.append({
                    "index": index,
                    "start": start,
                    "end": end,
                    "text": text
                })
            except (ValueError, IndexError):
                continue

    return segments


def srt_time_to_seconds(time_str: str) -> float:
    """Convert SRT timestamp to seconds."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace(".", ",")


def _hex_to_ass_bgr(hex_color: str) -> str:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return "00FF66"
    try:
        int(h, 16)
    except ValueError:
        return "00FF66"
    return (h[4:6] + h[2:4] + h[0:2]).upper()


def generate_karaoke_ass(words: list, video_width: int = 1080, video_height: int = 1920, highlight_color: str = "#66FF00", border: bool = True, border_color: str = "#000000", position: str = "bottom") -> str:
    """
    Generate ASS subtitle file with CapCut-style word pop effect.
    Shows 2-3 words at a time, current word highlighted and scaled.

    Args:
        words: List of {word, start, end} dicts with timestamps
        video_width/height: Video dimensions for positioning

    Returns:
        ASS file content as string
    """
    # ASS header with styles - CapCut style with Poppins font and thick outline
    outline_bgr = _hex_to_ass_bgr(border_color)
    outline_width = 6 if border else 0
    # Caption placement. Default bottom keeps the original look; top/middle let
    # users dodge on-screen action. MarginV scales with frame height so text
    # stays inside a safe area for both vertical and horizontal videos.
    _align = {"top": 8, "middle": 5, "bottom": 2}.get((position or "bottom").lower(), 2)
    _margin_v = max(50, round(video_height * 0.078))
    ass_header = f"""[Script Info]
Title: Pop Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Poppins Black,90,&H00FFFFFF,&H00FFFFFF,&H00{outline_bgr},&H00000000,-1,0,0,0,100,100,0,0,1,{outline_width},0,{_align},40,40,{_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    hl = _hex_to_ass_bgr(highlight_color)
    events = []

    # Group words into chunks of 2-3 words
    chunks = []
    current_chunk = []

    for word_info in words:
        current_chunk.append(word_info)
        word_text = word_info["word"].strip()

        # New chunk after 3 words or at punctuation
        if len(current_chunk) >= 3 or word_text.endswith((".", "!", "?", ",")):
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    # Generate events - each word gets highlighted when spoken
    for chunk in chunks:
        if not chunk:
            continue

        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"] + 0.1  # Small buffer

        # For each word in the chunk, show the full chunk with current word highlighted
        for i, current_word in enumerate(chunk):
            word_start = current_word["start"]
            word_end = current_word["end"]

            # Build the line: previous words dim, current word GREEN + BIGGER, next words dim
            parts = []
            for j, w in enumerate(chunk):
                word_text = w["word"].strip()
                if j < i:
                    # Already spoken - white, normal size
                    parts.append(f"{{\\c&HFFFFFF&\\fscx100\\fscy100}}{word_text}")
                elif j == i:
                    # Current word - GREEN, slightly bigger, with pop animation
                    parts.append(f"{{\\c&H{hl}&\\fscx115\\fscy115\\t(0,50,\\fscx100\\fscy100)}}{word_text}")
                else:
                    # Not yet spoken - white, normal
                    parts.append(f"{{\\c&HFFFFFF&\\fscx100\\fscy100}}{word_text}")

            line_text = " ".join(parts)

            # Format timestamps
            start_ts = seconds_to_ass_time(word_start)
            end_ts = seconds_to_ass_time(word_end)

            events.append(f"Dialogue: 0,{start_ts},{end_ts},Word,,0,0,0,,{line_text}")

    return ass_header + "\n".join(events) + "\n"


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"


def split_srt_into_chunks(srt_content: str, max_words: int = 4) -> str:
    """
    Split SRT subtitles into smaller chunks (few words at a time).
    This makes subtitles easier to read on short-form video.
    """
    segments = parse_srt(srt_content)
    new_segments = []
    index = 1

    for seg in segments:
        words = seg["text"].split()
        if len(words) <= max_words:
            new_segments.append({
                "index": index,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"]
            })
            index += 1
        else:
            duration = seg["end"] - seg["start"]
            words_per_second = len(words) / duration if duration > 0 else len(words)

            for i in range(0, len(words), max_words):
                chunk_words = words[i:i + max_words]
                chunk_text = " ".join(chunk_words)

                chunk_start = seg["start"] + (i / words_per_second) if words_per_second > 0 else seg["start"]
                chunk_end_idx = min(i + max_words, len(words))
                chunk_end = seg["start"] + (chunk_end_idx / words_per_second) if words_per_second > 0 else seg["end"]
                chunk_end = min(chunk_end, seg["end"])

                new_segments.append({
                    "index": index,
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": chunk_text
                })
                index += 1

    return segments_to_srt(new_segments)
