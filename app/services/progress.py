"""
Real-time progress tracking for video processing jobs.
Uses Redis to store progress that can be polled by the frontend.
"""
import re
import subprocess
from redis import Redis
from app.config import settings

redis_client = Redis.from_url(settings.redis_url)


def set_progress(job_id: str, percent: int, step: str = ""):
    """Set job progress in Redis."""
    redis_client.hset(f"job_progress:{job_id}", mapping={
        "percent": percent,
        "step": step
    })
    redis_client.expire(f"job_progress:{job_id}", 3600)  # Expire after 1 hour


def get_progress(job_id: str) -> dict:
    """Get job progress from Redis."""
    data = redis_client.hgetall(f"job_progress:{job_id}")
    if data:
        return {
            "percent": int(data.get(b"percent", 0)),
            "step": data.get(b"step", b"").decode()
        }
    return {"percent": 0, "step": ""}


def clear_progress(job_id: str):
    """Clear job progress from Redis."""
    redis_client.delete(f"job_progress:{job_id}")


def run_ffmpeg_with_progress(cmd: list, job_id: str, duration: float, step_name: str = "Processing") -> subprocess.CompletedProcess:
    """
    Run ffmpeg command while tracking progress.

    Args:
        cmd: FFmpeg command list
        job_id: Job ID for progress tracking
        duration: Total duration in seconds (for calculating %)
        step_name: Name of current step
    """
    # Add progress output to ffmpeg
    cmd_with_progress = cmd.copy()
    # Insert -progress pipe:1 after ffmpeg
    if cmd_with_progress[0] == "ffmpeg":
        cmd_with_progress.insert(1, "-progress")
        cmd_with_progress.insert(2, "pipe:1")
        cmd_with_progress.insert(3, "-stats_period")
        cmd_with_progress.insert(4, "1")

    process = subprocess.Popen(
        cmd_with_progress,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )

    current_time = 0

    # Read progress from stdout
    for line in process.stdout:
        # Parse out_time_ms or out_time
        if line.startswith("out_time_ms="):
            try:
                time_ms = int(line.split("=")[1].strip())
                current_time = time_ms / 1000000  # Convert microseconds to seconds
                percent = min(int((current_time / duration) * 100), 99)
                set_progress(job_id, percent, step_name)
            except (ValueError, IndexError):
                pass
        elif line.startswith("out_time="):
            try:
                time_str = line.split("=")[1].strip()
                # Parse HH:MM:SS.microseconds
                match = re.match(r"(\d+):(\d+):(\d+\.?\d*)", time_str)
                if match:
                    h, m, s = match.groups()
                    current_time = int(h) * 3600 + int(m) * 60 + float(s)
                    percent = min(int((current_time / duration) * 100), 99)
                    set_progress(job_id, percent, step_name)
            except (ValueError, IndexError):
                pass

    # Wait for completion
    process.wait()
    stderr = process.stderr.read()

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=process.returncode,
        stdout="",
        stderr=stderr
    )
