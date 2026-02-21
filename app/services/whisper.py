"""
Speech-to-text using OpenAI Whisper API with custom vocabulary support.
"""
from openai import OpenAI
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
    "pervo", "pervoja", "pervojen",  # rear wing/spoiler parts
    "visio", "visioita", "visioon",  # vision/design
    # General Finglish
    "upgradeta", "downloadaa", "uploadaa", "streamaa", "settingit",
]


def transcribe_audio(audio_path: str, custom_vocabulary: list = None) -> dict:
    """
    Transcribe audio using OpenAI Whisper API.

    Args:
        audio_path: Path to audio file
        custom_vocabulary: Additional words/phrases to help recognition

    Returns:
        dict with transcript text and SRT content
    """
    client = OpenAI(api_key=settings.openai_api_key)

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
        # First get the verbose JSON for timestamps
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="fi",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            prompt=prompt
        )

    # Extract transcript
    transcript = response.text

    # Build SRT from word timestamps if available
    srt_segments = []
    segment_index = 1

    if hasattr(response, 'words') and response.words:
        # Use word-level timestamps
        word_buffer = []
        for word_info in response.words:
            word_buffer.append({
                "word": word_info.word,
                "start": word_info.start,
                "end": word_info.end,
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
    if hasattr(response, 'words') and response.words:
        word_list = [{"word": w.word, "start": w.start, "end": w.end} for w in response.words]
        ass_content = generate_karaoke_ass(word_list)

    return {
        "transcript": transcript,
        "srt": srt_content,
        "ass": ass_content,
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


def generate_karaoke_ass(words: list, video_width: int = 1080, video_height: int = 1920) -> str:
    """
    Generate ASS subtitle file with karaoke-style word highlighting.
    Words highlight in green as they're spoken.

    Args:
        words: List of {word, start, end} dicts with timestamps
        video_width/height: Video dimensions for positioning

    Returns:
        ASS file content as string
    """
    # ASS header with styles
    ass_header = f"""[Script Info]
Title: Karaoke Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,60,&HFFFFFF,&H00FF00,&H000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,80,1
Style: Highlight,Arial Black,60,&H00FF00,&H00FF00,&H000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    # Group words into lines (4-5 words per line)
    lines = []
    current_line = []

    for word_info in words:
        current_line.append(word_info)
        word_text = word_info["word"].strip()

        # Start new line after 4 words or at sentence end
        if len(current_line) >= 4 or word_text.endswith((".", "!", "?", ",")):
            if current_line:
                lines.append(current_line)
                current_line = []

    if current_line:
        lines.append(current_line)

    # Generate karaoke events for each line
    for line_words in lines:
        if not line_words:
            continue

        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]

        # Build karaoke text with \k tags
        # \k duration is in centiseconds (1/100 sec)
        karaoke_text = ""

        for i, word_info in enumerate(line_words):
            word = word_info["word"].strip()
            word_start = word_info["start"]
            word_end = word_info["end"]

            # Duration of this word in centiseconds
            duration_cs = int((word_end - word_start) * 100)
            duration_cs = max(duration_cs, 10)  # Minimum 0.1 sec

            # Use \kf for smooth fill effect (green highlight)
            # {\kf<duration>} highlights over duration
            karaoke_text += f"{{\\kf{duration_cs}}}{word} "

        karaoke_text = karaoke_text.strip()

        # Format timestamps for ASS (H:MM:SS.cc)
        start_ts = seconds_to_ass_time(line_start)
        end_ts = seconds_to_ass_time(line_end + 0.5)  # Add small buffer

        events.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{karaoke_text}")

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
