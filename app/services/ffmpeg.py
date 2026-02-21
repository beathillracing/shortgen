import subprocess
import json
from pathlib import Path
from typing import Optional

from app.config import settings


def get_video_info(video_path: str) -> dict:
    """Get video metadata using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)

    # Extract relevant info
    video_stream = next((s for s in data.get("streams", []) if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s["codec_type"] == "audio"), None)

    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": video_stream["width"] if video_stream else None,
        "height": video_stream["height"] if video_stream else None,
        "has_audio": audio_stream is not None,
    }


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as MP3."""
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "libmp3lame",
        "-ab", "128k",
        "-y",  # Overwrite
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr}")

    return output_path


def extract_frame(video_path: str, output_path: str, timestamp: float = 0) -> str:
    """Extract a single frame from video."""
    cmd = [
        "ffmpeg",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    return output_path


def render_video_with_captions(
    input_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
    ass_path: Optional[str] = None,
    watermark_path: Optional[str] = None,
    burn_captions: bool = True,
    segments: Optional[list] = None,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """
    Render final video with optional captions, watermark, and segment cuts.
    Outputs 9:16 vertical video for shorts/reels.
    """
    # Default watermark path
    if watermark_path is None:
        default_watermark = settings.assets_path / "watermark.png"
        if default_watermark.exists():
            watermark_path = str(default_watermark)

    has_watermark = watermark_path and Path(watermark_path).exists()

    cmd = ["ffmpeg", "-i", input_path]

    # Add watermark input if exists
    if has_watermark:
        cmd.extend(["-i", watermark_path])

    # Build filter chain
    filter_parts = []

    # Scale and pad video to 9:16
    filter_parts.append(
        f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[scaled]"
    )

    current_output = "[scaled]"

    # Add watermark overlay if present
    if has_watermark:
        # Scale watermark to ~15% of video width, position top-right with padding
        watermark_width = int(target_width * 0.15)
        padding = 20
        filter_parts.append(
            f"[1:v]scale={watermark_width}:-1[wm]"
        )
        filter_parts.append(
            f"{current_output}[wm]overlay=W-w-{padding}:{padding}[watermarked]"
        )
        current_output = "[watermarked]"

    # Add subtitles if provided and burn_captions is True
    if burn_captions:
        # Prefer ASS (karaoke style) over SRT
        if ass_path and Path(ass_path).exists():
            escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
            subtitle_filter = f"{current_output}ass={escaped_ass}[final]"
            filter_parts.append(subtitle_filter)
            current_output = "[final]"
        elif srt_path and Path(srt_path).exists():
            escaped_srt = srt_path.replace(":", "\\:").replace("'", "\\'")
            subtitle_filter = (
                f"{current_output}subtitles={escaped_srt}:force_style='"
                "FontName=Arial Bold,FontSize=10,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
                "BackColour=&H80000000,Outline=1,Shadow=0,Alignment=2,MarginV=25,MarginL=20,MarginR=20'[final]"
            )
            filter_parts.append(subtitle_filter)
            current_output = "[final]"

    # Build complete filter_complex string
    filter_complex = ";".join(filter_parts)

    # Map the final output - strip brackets for -map
    map_output = current_output.strip("[]")

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", f"[{map_output}]",
        "-map", "0:a?",  # Map audio if exists
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Video rendering failed: {result.stderr}")

    return output_path


def stitch_videos(input_paths: list, output_path: str) -> str:
    """Stitch multiple video files together in order."""
    if len(input_paths) == 1:
        import shutil
        shutil.copy(input_paths[0], output_path)
        return output_path

    # Create concat file
    concat_file = Path(output_path).parent / "concat_input.txt"
    with open(concat_file, "w") as f:
        for path in input_paths:
            f.write(f"file '{path}'\n")

    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-y",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup
    concat_file.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"Video stitching failed: {result.stderr}")

    return output_path


def remove_capcut_watermark(
    input_path: str,
    output_path: str,
    trim_end_seconds: float = 3.0,
    cover_corner: bool = True,
    watermark_path: Optional[str] = None,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """
    Remove CapCut watermark and add custom watermark.

    CapCut free tier adds:
    1. An outro screen at the end (2-3 seconds)
    2. Sometimes a small corner watermark (bottom-right)

    This function:
    - Trims the outro from the end
    - Covers the corner watermark area with a blur/box
    - Adds your own watermark
    - Scales to 9:16 format if needed
    """
    # Get video duration to calculate trim point
    video_info = get_video_info(input_path)
    duration = video_info["duration"]
    trim_to = max(duration - trim_end_seconds, 1.0)

    # Default watermark path
    if watermark_path is None:
        default_watermark = settings.assets_path / "watermark.png"
        if default_watermark.exists():
            watermark_path = str(default_watermark)

    has_watermark = watermark_path and Path(watermark_path).exists()

    cmd = ["ffmpeg", "-i", input_path]

    # Add watermark input if exists
    if has_watermark:
        cmd.extend(["-i", watermark_path])

    # Build filter chain
    filter_parts = []

    # Scale and pad video to 9:16 (in case it's not already)
    filter_parts.append(
        f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[scaled]"
    )

    current_output = "[scaled]"

    # Cover CapCut corner watermark (bottom-right area) with a subtle blur box
    if cover_corner:
        # CapCut watermark is typically ~200x50px in bottom-right
        # We'll blur that area slightly
        box_w = 220
        box_h = 60
        box_x = target_width - box_w - 10  # 10px from right edge
        box_y = target_height - box_h - 10  # 10px from bottom

        # Use delogo filter to blur/remove the watermark area
        filter_parts.append(
            f"{current_output}delogo=x={box_x}:y={box_y}:w={box_w}:h={box_h}:show=0[cleaned]"
        )
        current_output = "[cleaned]"

    # Add our own watermark overlay if present
    if has_watermark:
        watermark_width = int(target_width * 0.15)
        padding = 20
        filter_parts.append(
            f"[1:v]scale={watermark_width}:-1[wm]"
        )
        filter_parts.append(
            f"{current_output}[wm]overlay=W-w-{padding}:{padding}[final]"
        )
        current_output = "[final]"

    # Build complete filter_complex string
    filter_complex = ";".join(filter_parts)
    map_output = current_output.strip("[]")

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", f"[{map_output}]",
        "-map", "0:a?",
        "-t", str(trim_to),  # Trim to remove CapCut outro
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"CapCut watermark removal failed: {result.stderr}")

    return output_path


def cut_segments(input_path: str, output_path: str, segments: list) -> str:
    """
    Cut and concatenate specific segments from video.
    segments: list of {start: float, end: float}
    """
    if not segments:
        # Just copy the file
        import shutil
        shutil.copy(input_path, output_path)
        return output_path

    # Create temporary segment files
    temp_dir = Path(output_path).parent / "temp_segments"
    temp_dir.mkdir(exist_ok=True)

    segment_files = []
    for i, seg in enumerate(segments):
        temp_file = temp_dir / f"segment_{i}.mp4"
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-ss", str(seg["start"]),
            "-to", str(seg["end"]),
            "-c", "copy",
            "-y",
            str(temp_file)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            segment_files.append(temp_file)

    if not segment_files:
        raise RuntimeError("No segments extracted")

    # Create concat file
    concat_file = temp_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")

    # Concatenate
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-y",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup temp files
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

    if result.returncode != 0:
        raise RuntimeError(f"Segment concatenation failed: {result.stderr}")

    return output_path
