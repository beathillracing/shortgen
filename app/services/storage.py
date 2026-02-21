import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from app.config import settings


def save_upload(file_content: bytes, original_filename: str) -> str:
    """Save uploaded file and return the path."""
    ext = Path(original_filename).suffix.lower()
    unique_name = f"{uuid.uuid4()}{ext}"
    upload_path = settings.storage_path / "uploads" / unique_name

    with open(upload_path, "wb") as f:
        f.write(file_content)

    return str(upload_path)


def get_processing_path(job_id: str, filename: str) -> Path:
    """Get a path in the processing directory for a job."""
    job_dir = settings.storage_path / "processing" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir / filename


def get_export_path(job_id: str, filename: str) -> Path:
    """Get a path in the exports directory for a job."""
    job_dir = settings.storage_path / "exports" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir / filename


def cleanup_old_jobs(days: int = 7):
    """Delete jobs older than specified days."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    for subdir in ["processing", "exports"]:
        base_path = settings.storage_path / subdir
        if not base_path.exists():
            continue

        for job_dir in base_path.iterdir():
            if job_dir.is_dir():
                # Check modification time
                mtime = datetime.fromtimestamp(job_dir.stat().st_mtime)
                if mtime < cutoff:
                    shutil.rmtree(job_dir, ignore_errors=True)


def get_job_files(job_id: str) -> dict:
    """Get all files for a job."""
    files = {}

    export_dir = settings.storage_path / "exports" / job_id
    if export_dir.exists():
        for f in export_dir.iterdir():
            files[f.name] = str(f)

    return files
