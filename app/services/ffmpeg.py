import subprocess
import json
import shutil
from pathlib import Path
from typing import Optional

from app.config import settings


def _configured_outro_duration(outro_path: Path) -> float:
    configured_duration = max(float(settings.outro_duration_seconds or 0), 0.0)
    if configured_duration <= 0:
        return 0.0

    return min(configured_duration, get_video_info(str(outro_path))["duration"])


def append_outro(input_path: str, output_path: str) -> str:
    """
    Append the outro clip to the end of a video.
    The outro should be at assets/outro.mp4
    Uses filter_complex concat to handle videos with different specs.
    """
    outro_path = settings.assets_path / "outro.mp4"
    if not outro_path.exists():
        # No outro configured, just copy the file
        shutil.copy(input_path, output_path)
        return output_path

    outro_duration = _configured_outro_duration(outro_path)
    if outro_duration <= 0:
        shutil.copy(input_path, output_path)
        return output_path

    # Use filter_complex concat for reliable joining of different video specs
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-t", str(outro_duration),
        "-i", str(outro_path),
        "-filter_complex",
        "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Outro append failed: {result.stderr}")

    return output_path


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


def extract_thumbnail_candidates(video_path: str, output_dir: str, count: int = 10) -> list:
    """
    Extract multiple frames from video as thumbnail candidates.
    First frame at ~1 second, last frame at ~5 seconds before end,
    rest distributed evenly between.
    Returns list of paths to extracted frames.
    """
    video_info = get_video_info(video_path)
    duration = video_info["duration"]

    # Start at 0.5 seconds (catch opening shots), end 5 seconds before the end
    start_offset = 0.5
    end_offset = max(duration - 5.0, start_offset + 1.0)
    usable_duration = end_offset - start_offset

    paths = []
    for i in range(count):
        timestamp = start_offset + (usable_duration * i / (count - 1)) if count > 1 else duration / 2
        output_path = f"{output_dir}/thumb_candidate_{i+1:02d}.jpg"

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
        if result.returncode == 0 and Path(output_path).exists():
            paths.append({
                "path": output_path,
                "timestamp": timestamp,
                "index": i + 1
            })

    return paths


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


def render_video_with_captions_and_outro(
    input_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
    ass_path: Optional[str] = None,
    watermark_path: Optional[str] = None,
    burn_captions: bool = True,
    target_width: int = 1080,
    target_height: int = 1920,
    job_id: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    thumbnail_duration: float = 0.3,
    progress_base: Optional[int] = None,
    progress_ceiling: int = 99,
) -> str:
    """
    Render video with captions, watermark, and outro - ALL IN ONE ENCODE.
    Much faster than separate render + outro append.

    If thumbnail_path is provided, prepends the thumbnail as a brief frame
    at the start (YouTube Shorts workaround for thumbnail selection).
    """
    video_info = get_video_info(input_path)
    duration = video_info["duration"]

    # Default watermark path
    if watermark_path is None:
        default_watermark = settings.assets_path / "watermark.png"
        if default_watermark.exists():
            watermark_path = str(default_watermark)

    has_watermark = watermark_path and Path(watermark_path).exists()
    has_thumbnail = thumbnail_path and Path(thumbnail_path).exists()

    # Check for outro
    outro_path = settings.assets_path / "outro.mp4"
    outro_duration = _configured_outro_duration(outro_path) if outro_path.exists() else 0.0
    has_outro = outro_duration > 0

    cmd = ["ffmpeg"]
    input_idx = 0

    # Add thumbnail input first (as image with duration)
    if has_thumbnail:
        cmd.extend([
            "-loop", "1",
            "-t", str(thumbnail_duration),
            "-i", thumbnail_path,
        ])
        thumb_idx = input_idx
        input_idx += 1

    # Add main video
    cmd.extend(["-i", input_path])
    main_video_idx = input_idx
    input_idx += 1

    # Add watermark input if exists
    if has_watermark:
        cmd.extend(["-i", watermark_path])
        watermark_idx = input_idx
        input_idx += 1

    # Add outro input if exists
    if has_outro:
        cmd.extend(["-t", str(outro_duration), "-i", str(outro_path)])
        outro_idx = input_idx

    # Build filter chain
    filter_parts = []

    # Scale and pad main video to 9:16
    filter_parts.append(
        f"[{main_video_idx}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[scaled]"
    )

    current_video = "[scaled]"

    # Add watermark overlay (top-right, transparent)
    if has_watermark:
        watermark_width = int(target_width * 0.18)  # ~195px wide
        padding = 15
        filter_parts.append(
            f"[{watermark_idx}:v]scale={watermark_width}:-1[wm]"
        )
        filter_parts.append(
            f"{current_video}[wm]overlay=W-w-{padding}:{padding}[watermarked]"
        )
        current_video = "[watermarked]"

    # Add subtitles if burn_captions is True
    if burn_captions:
        # Prefer ASS (karaoke style) over SRT
        if ass_path and Path(ass_path).exists():
            escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
            filter_parts.append(f"{current_video}ass={escaped_ass}[captioned]")
            current_video = "[captioned]"
        elif srt_path and Path(srt_path).exists():
            escaped_srt = srt_path.replace(":", "\\:").replace("'", "\\'")
            filter_parts.append(
                f"{current_video}subtitles={escaped_srt}:force_style='"
                "FontName=Arial Bold,FontSize=10,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
                "BackColour=&H80000000,Outline=1,Shadow=0,Alignment=2,MarginV=25'[captioned]"
            )
            current_video = "[captioned]"

    # Reset timestamps before concat. Multi-file phone videos can retain edit-list
    # discontinuities that otherwise make FFmpeg repeat the preceding thumbnail.
    filter_parts.append(f"{current_video}setpts=PTS-STARTPTS[main_video]")
    filter_parts.append(
        f"[{main_video_idx}:a]aresample=48000,asetpts=PTS-STARTPTS[main_audio]"
    )

    # Prepare thumbnail if exists (scale to target resolution)
    if has_thumbnail:
        filter_parts.append(
            f"[{thumb_idx}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps=30,trim=duration={thumbnail_duration},setpts=PTS-STARTPTS[thumb_v]"
        )
        # Generate silence for the thumbnail duration
        filter_parts.append(
            f"anullsrc=r=44100:cl=stereo,atrim=0:{thumbnail_duration}[thumb_a]"
        )

    # Build concat chain: thumbnail (optional) -> main -> outro (optional)
    video_streams = []
    audio_streams = []

    if has_thumbnail:
        video_streams.append("[thumb_v]")
        audio_streams.append("[thumb_a]")

    video_streams.append("[main_video]")
    audio_streams.append("[main_audio]")

    if has_outro:
        filter_parts.append(
            f"[{outro_idx}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps=30,setpts=PTS-STARTPTS[outro_v]"
        )
        filter_parts.append(
            f"[{outro_idx}:a]aresample=48000,asetpts=PTS-STARTPTS[outro_a]"
        )
        video_streams.append("[outro_v]")
        audio_streams.append("[outro_a]")

    # Concat all parts if more than one stream
    if len(video_streams) > 1:
        n_parts = len(video_streams)
        filter_parts.append(
            f"{''.join(video_streams)}concat=n={n_parts}:v=1:a=0[final_v]"
        )
        filter_parts.append(
            f"{''.join(audio_streams)}concat=n={n_parts}:v=0:a=1[final_a]"
        )
        final_video = "[final_v]"
        final_audio = "[final_a]"
    else:
        final_video = "[main_video]"
        final_audio = "[main_audio]"

    # Build complete filter_complex string
    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", final_video,
        "-map", final_audio,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ])

    # Calculate total duration for progress
    total_duration = duration
    if has_thumbnail:
        total_duration += thumbnail_duration
    if has_outro:
        total_duration += outro_duration

    # Use progress tracking if job_id provided
    if job_id:
        from app.services.progress import run_ffmpeg_with_progress
        result = run_ffmpeg_with_progress(
            cmd, job_id, total_duration,
            base_percent=progress_base, ceiling_percent=progress_ceiling,
        )
    else:
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Video rendering failed: {result.stderr}")

    return output_path


def stitch_videos(
    input_paths: list,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """Stitch clips after normalizing timestamps, frame rate, size, and audio."""
    if len(input_paths) == 1:
        import shutil
        shutil.copy(input_paths[0], output_path)
        return output_path

    cmd = ["ffmpeg"]
    infos = []
    for path in input_paths:
        cmd.extend(["-i", path])
        infos.append(get_video_info(path))

    filter_parts = []
    streams = []
    for index, info in enumerate(infos):
        filter_parts.append(
            f"[{index}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps=30,setpts=PTS-STARTPTS[v{index}]"
        )
        if info["has_audio"]:
            filter_parts.append(
                f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[a{index}]"
            )
        else:
            filter_parts.append(
                f"anullsrc=r=48000:cl=stereo,atrim=duration={info['duration']},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
        streams.append(f"[v{index}][a{index}]")

    filter_parts.append(
        f"{''.join(streams)}concat=n={len(input_paths)}:v=1:a=1[outv][outa]"
    )
    cmd.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "20",
        "-threads", "4",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)

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
    job_id: Optional[str] = None,
    duration: Optional[float] = None,
    append_outro: bool = True,
    progress_base: Optional[int] = None,
    progress_ceiling: int = 99,
) -> str:
    """
    Remove CapCut watermark, add custom watermark, and append outro - ALL IN ONE ENCODE.

    CapCut free tier adds:
    1. An outro screen at the end (2-3 seconds)
    2. Sometimes a small corner watermark (bottom-right)

    This function:
    - Trims the CapCut outro from the end
    - Covers the corner watermark area with black box + our logo
    - Appends our outro clip
    - Scales to 9:16 format
    - Does it all in ONE FFmpeg pass for speed
    """
    # Get video duration to calculate trim point
    video_info = get_video_info(input_path)
    vid_duration = video_info["duration"]
    trim_to = max(vid_duration - trim_end_seconds, 1.0)

    # Default watermark path
    if watermark_path is None:
        default_watermark = settings.assets_path / "watermark.png"
        if default_watermark.exists():
            watermark_path = str(default_watermark)

    has_watermark = watermark_path and Path(watermark_path).exists()

    # Check for outro
    outro_path = settings.assets_path / "outro.mp4"
    outro_duration = _configured_outro_duration(outro_path) if append_outro and outro_path.exists() else 0.0
    has_outro = outro_duration > 0

    cmd = ["ffmpeg", "-i", input_path]
    input_idx = 1

    # Add watermark input if exists
    if has_watermark:
        cmd.extend(["-i", watermark_path])
        watermark_idx = input_idx
        input_idx += 1

    # Add outro input if exists
    if has_outro:
        cmd.extend(["-t", str(outro_duration), "-i", str(outro_path)])
        outro_idx = input_idx

    # Build filter chain
    filter_parts = []

    # Scale and pad main video to 9:16, trim it
    filter_parts.append(
        f"[0:v]trim=0:{trim_to},setpts=PTS-STARTPTS,"
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[scaled]"
    )
    filter_parts.append(
        f"[0:a]atrim=0:{trim_to},asetpts=PTS-STARTPTS[main_audio]"
    )

    current_video = "[scaled]"

    # Add our own watermark overlay - position it over the CapCut logo (top-left)
    if has_watermark:
        watermark_width = int(target_width * 0.28)  # ~300px wide
        x_pos = 5
        y_pos = 5

        # Scale logo
        filter_parts.append(
            f"[{watermark_idx}:v]scale={watermark_width}:-1[wm_scaled]"
        )

        # Draw black box to cover CapCut logo, then overlay our logo
        box_w = watermark_width + 20
        box_h = 150
        filter_parts.append(
            f"{current_video}drawbox=x=0:y=0:w={box_w}:h={box_h}:color=black:t=fill[boxed]"
        )
        filter_parts.append(
            f"[boxed][wm_scaled]overlay={x_pos}:{y_pos}[main_video]"
        )
        current_video = "[main_video]"
    else:
        filter_parts.append(f"{current_video}copy[main_video]")
        current_video = "[main_video]"

    # Concat with outro if exists
    if has_outro:
        filter_parts.append(
            f"[{outro_idx}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[outro_v]"
        )
        filter_parts.append(
            f"{current_video}[outro_v]concat=n=2:v=1:a=0[final_v]"
        )
        filter_parts.append(
            f"[main_audio][{outro_idx}:a]concat=n=2:v=0:a=1[final_a]"
        )
        final_video = "[final_v]"
        final_audio = "[final_a]"
    else:
        final_video = current_video
        final_audio = "[main_audio]"

    # Build complete filter_complex string
    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", final_video,
        "-map", final_audio,
        "-c:v", "libx264",
        "-preset", "fast",  # faster encoding
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-y",
        output_path
    ])

    # Calculate total duration for progress
    total_duration = trim_to
    if has_outro:
        total_duration += outro_duration

    # Use progress tracking if job_id provided
    if job_id:
        from app.services.progress import run_ffmpeg_with_progress
        result = run_ffmpeg_with_progress(
            cmd, job_id, total_duration,
            base_percent=progress_base, ceiling_percent=progress_ceiling,
        )
    else:
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
