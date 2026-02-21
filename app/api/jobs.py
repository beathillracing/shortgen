import zipfile
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.config import settings
from app.services.storage import get_export_path

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job status and data."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    return job.to_dict()


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), limit: int = 20):
    """List recent jobs."""
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
    return [job.to_dict() for job in jobs]


@router.post("/jobs/{job_id}/update")
def update_job(
    job_id: str,
    title: str = None,
    description: str = None,
    notes: str = None,
    db: Session = Depends(get_db)
):
    """Update job with user edits."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if title is not None:
        job.final_title = title
    if description is not None:
        job.final_description = description
    if notes is not None:
        job.notes = notes

    db.commit()
    return {"status": "updated"}


@router.get("/jobs/{job_id}/export")
def export_job(job_id: str, db: Session = Depends(get_db)):
    """Download export pack as ZIP."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status not in ["review", "completed"]:
        raise HTTPException(400, "Job not ready for export")

    # Create ZIP file
    export_dir = settings.storage_path / "exports" / job_id
    zip_path = export_dir / "export.zip"

    if not zip_path.exists():
        # Create the ZIP
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Add video if exists
            if job.output_video_path and Path(job.output_video_path).exists():
                zf.write(job.output_video_path, "video.mp4")

            # Add thumbnail if exists
            if job.thumbnail_path and Path(job.thumbnail_path).exists():
                zf.write(job.thumbnail_path, "thumbnail.jpg")

            # Add SRT
            if job.srt_content:
                zf.writestr("captions.srt", job.srt_content)

            # Add metadata JSON
            import json
            metadata = {
                "title": job.final_title or job.suggested_title,
                "description": job.final_description or job.suggested_description,
                "hashtags": job.suggested_hashtags or [],
                "hook": job.suggested_hook,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"shortgen-{job_id[:8]}.zip"
    )


@router.get("/jobs/{job_id}/video")
def get_video(job_id: str, db: Session = Depends(get_db)):
    """Stream the output video."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.output_video_path or not Path(job.output_video_path).exists():
        raise HTTPException(404, "Video not ready")

    return FileResponse(job.output_video_path, media_type="video/mp4")


@router.get("/jobs/{job_id}/thumbnail/{variant}")
def get_thumbnail(job_id: str, variant: str = "clean", db: Session = Depends(get_db)):
    """Get the thumbnail image. Variants: fi, en, clean"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if variant == "fi" and job.thumbnail_path_fi:
        path = job.thumbnail_path_fi
    elif variant == "en" and job.thumbnail_path_en:
        path = job.thumbnail_path_en
    else:
        path = job.thumbnail_path

    if not path or not Path(path).exists():
        raise HTTPException(404, "Thumbnail not ready")

    return FileResponse(path, media_type="image/jpeg")


@router.get("/jobs/{job_id}/thumbnail")
def get_thumbnail_default(job_id: str, db: Session = Depends(get_db)):
    """Get the default (clean) thumbnail."""
    return get_thumbnail(job_id, "clean", db)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Delete a job and all its files."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Delete upload file
    if job.upload_path and Path(job.upload_path).exists():
        Path(job.upload_path).unlink()

    # Delete processing directory
    processing_dir = settings.storage_path / "processing" / job_id
    if processing_dir.exists():
        shutil.rmtree(processing_dir, ignore_errors=True)

    # Delete export directory
    export_dir = settings.storage_path / "exports" / job_id
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)

    # Delete from database
    db.delete(job)
    db.commit()

    return {"status": "deleted"}
