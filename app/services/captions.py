"""Editing the burned-in captions while a job waits for review.

The karaoke captions are generated from word-level timings, but only the
transcript and the chunked SRT are stored on the job. The timings are kept
next to the caption files so a typo can be fixed before the render burns
them into the video, which is the only point where fixing one is cheap.
"""
import json

from app.models import Job
from app.services import storage, whisper

WORDS_FILE = "words.json"
SRT_FILE = "captions.srt"
ASS_FILE = "captions.ass"


def _words_path(job_id: str):
    return storage.get_processing_path(job_id, WORDS_FILE)


def save_word_timings(job_id: str, words: list):
    _words_path(job_id).write_text(json.dumps(words), encoding="utf-8")


def load_word_timings(job_id: str) -> list:
    path = _words_path(job_id)
    if not path.exists():
        return []
    try:
        words = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return words if isinstance(words, list) else []


def is_editable(job: Job) -> bool:
    """Captions can only be edited while they are still separate from the video."""
    if job.burn_captions != "true" or job.precaptioned == "true":
        return False
    return bool(job.srt_content)


def editable_lines(job: Job) -> list:
    """The caption lines as shown to the user, in playback order."""
    if not job.srt_content:
        return []
    return [
        {
            "index": segment["index"],
            "start": round(segment["start"], 3),
            "end": round(segment["end"], 3),
            "text": segment["text"],
        }
        for segment in whisper.parse_srt(job.srt_content)
    ]


def _output_dims(job: Job) -> tuple[int, int]:
    if getattr(job, "orientation", None) == "horizontal":
        return 1920, 1080
    return 1080, 1920


def _redistribute(new_words: list, start: float, end: float) -> list:
    """Spread a line's time span evenly when its word count changed."""
    span = max(end - start, 0.0)
    step = span / len(new_words) if new_words else 0.0
    out = []
    for position, word in enumerate(new_words):
        out.append(
            {
                "word": word,
                "start": start + position * step,
                "end": start + (position + 1) * step if position < len(new_words) - 1 else end,
            }
        )
    return out


def _remap(original_lines: list, edited_texts: dict, words: list) -> list:
    """Rebuild the word list so edited text keeps the original timings.

    Each caption line covers a contiguous run of words, so the runs are walked
    in order. A line whose word count is unchanged - the usual case when fixing
    a typo - keeps its timings exactly; otherwise the line's span is shared out
    across the new words.
    """
    rebuilt = []
    cursor = 0
    for line in original_lines:
        count = len(line["text"].split())
        original_run = words[cursor:cursor + count]
        cursor += count

        new_words = edited_texts.get(line["index"], line["text"]).split()
        if not new_words:
            continue

        if len(new_words) == len(original_run):
            for word, timing in zip(new_words, original_run):
                rebuilt.append({**timing, "word": word})
        else:
            start = original_run[0]["start"] if original_run else line["start"]
            end = original_run[-1]["end"] if original_run else line["end"]
            rebuilt.extend(_redistribute(new_words, start, end))

    # Anything the caption lines never covered still belongs in the video.
    rebuilt.extend(words[cursor:])
    return rebuilt


def save_lines(job: Job, lines: list) -> list:
    """Apply edited caption lines and rewrite the files the render reads."""
    original_lines = editable_lines(job)
    if not original_lines:
        raise ValueError("This job has no editable captions")

    known = {line["index"] for line in original_lines}
    edited_texts = {}
    for line in lines:
        try:
            index = int(line["index"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each caption line needs an index")
        if index not in known:
            raise ValueError(f"Unknown caption line {index}")
        edited_texts[index] = " ".join(str(line.get("text") or "").split())

    updated_segments = []
    for line in original_lines:
        text = edited_texts.get(line["index"], line["text"])
        if not text:
            continue
        updated_segments.append({**line, "text": text})

    if not updated_segments:
        raise ValueError("The captions cannot be emptied completely")

    for position, segment in enumerate(updated_segments, start=1):
        segment["index"] = position

    job_id = str(job.id)
    job.srt_content = whisper.segments_to_srt(updated_segments)
    storage.get_processing_path(job_id, SRT_FILE).write_text(
        job.srt_content, encoding="utf-8"
    )

    words = load_word_timings(job_id)
    if words:
        rebuilt = _remap(original_lines, edited_texts, words)
        save_word_timings(job_id, rebuilt)
        width, height = _output_dims(job)
        ass_content = whisper.generate_karaoke_ass(
            rebuilt,
            video_width=width,
            video_height=height,
            highlight_color=job.caption_highlight_color or "#66FF00",
            border=(job.caption_border != "false"),
            border_color=job.caption_border_color or "#000000",
            position=job.caption_position or "bottom",
        )
        storage.get_processing_path(job_id, ASS_FILE).write_text(
            ass_content, encoding="utf-8"
        )

    return editable_lines(job)
