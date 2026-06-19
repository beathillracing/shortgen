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


def run_ffmpeg_with_progress(
    cmd: list,
    job_id: str,
    duration: float,
    step_name: str = None,
    base_percent: int = None,
    ceiling_percent: int = 99,
) -> subprocess.CompletedProcess:
    """
    Run an ffmpeg command while reporting real progress.

    The live ffmpeg position is mapped into the [base_percent, ceiling_percent]
    band so the overall job bar advances smoothly within the current stage
    instead of resetting to the render-relative percentage. When base_percent or
    step_name are omitted they are read from the job's current progress so the
    worker's stage label and starting percentage are preserved.
    """
    current = get_progress(job_id)
    if base_percent is None:
        base_percent = current.get("percent", 0)
    if step_name is None:
        step_name = current.get("step", "")
    if ceiling_percent <= base_percent:
        ceiling_percent = min(base_percent + 1, 99)
    span = ceiling_percent - base_percent

    cmd_with_progress = cmd.copy()
    if cmd_with_progress[0] == "ffmpeg":
        cmd_with_progress.insert(1, "-progress")
        cmd_with_progress.insert(2, "pipe:1")
        cmd_with_progress.insert(3, "-stats_period")
        cmd_with_progress.insert(4, "1")

    process = subprocess.Popen(
        cmd_with_progress,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )

    def report(current_time):
        if not duration or duration <= 0:
            return
        fraction = max(0.0, min(current_time / duration, 1.0))
        percent = min(base_percent + int(fraction * span), ceiling_percent)
        set_progress(job_id, percent, step_name)

    for line in process.stdout:
        if line.startswith("out_time_ms="):
            try:
                report(int(line.split("=")[1].strip()) / 1000000)
            except (ValueError, IndexError):
                pass
        elif line.startswith("out_time="):
            try:
                time_str = line.split("=")[1].strip()
                match = re.match(r"(\d+):(\d+):(\d+\.?\d*)", time_str)
                if match:
                    h, m, s = match.groups()
                    report(int(h) * 3600 + int(m) * 60 + float(s))
            except (ValueError, IndexError):
                pass

    process.wait()
    stderr = process.stderr.read()
    return subprocess.CompletedProcess(
        args=cmd, returncode=process.returncode, stdout="", stderr=stderr
    )
