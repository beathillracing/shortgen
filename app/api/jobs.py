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


@router.get("/jobs/{job_id}/progress")
def get_job_progress(job_id: str, db: Session = Depends(get_db)):
    """Get real-time job progress."""
    from app.services.progress import get_progress

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    progress = get_progress(job_id)
    return {
        "status": job.status,
        "current_step": job.current_step,
        "percent": progress["percent"],
        "step": progress["step"]
    }


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


@router.post("/jobs/{job_id}/status")
def update_job_status(job_id: str, data: dict, db: Session = Depends(get_db)):
    """Manually update job status for tracking."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    new_status = data.get("status")
    allowed_statuses = ["review", "uploaded", "posted", "archived", "completed"]

    if new_status not in allowed_statuses:
        raise HTTPException(400, f"Invalid status. Allowed: {', '.join(allowed_statuses)}")

    job.status = new_status
    db.commit()

    return {"status": "updated", "new_status": new_status}


@router.post("/jobs/{job_id}/continue")
def continue_job(job_id: str, data: dict, db: Session = Depends(get_db)):
    """Continue processing after thumbnail selection."""
    from redis import Redis
    from rq import Queue
    from app.workers.transcribe import continue_processing

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status != "thumbnail_selection":
        raise HTTPException(400, f"Job is not awaiting thumbnail selection (status: {job.status})")

    # Get selected thumbnail index and optional custom text
    selected_index = data.get("thumbnail_index", 1)
    text_fi = data.get("text_fi")
    text_en = data.get("text_en")

    # Update job status
    job.status = "processing"
    job.current_step = "Continuing processing..."
    job.selected_thumbnail_index = str(selected_index)
    db.commit()

    # Queue the continuation
    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue(connection=redis_conn)
    queue.enqueue(
        continue_processing,
        job_id,
        selected_index,
        text_fi,
        text_en,
        job_timeout=1800
    )

    return {"status": "processing", "message": "Continuing with selected thumbnail"}


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

            # Add all thumbnail variants
            if job.thumbnail_path_fi and Path(job.thumbnail_path_fi).exists():
                zf.write(job.thumbnail_path_fi, "thumbnail_fi.jpg")
            if job.thumbnail_path_en and Path(job.thumbnail_path_en).exists():
                zf.write(job.thumbnail_path_en, "thumbnail_en.jpg")
            if job.thumbnail_path and Path(job.thumbnail_path).exists():
                zf.write(job.thumbnail_path, "thumbnail_clean.jpg")

            # Add SRT
            if job.srt_content:
                zf.writestr("captions.srt", job.srt_content)

            # Add metadata JSON
            import json
            metadata = {
                "title_fi": job.final_title or job.suggested_title_fi,
                "title_en": job.suggested_title_en,
                "description_fi": job.final_description or job.suggested_description_fi,
                "description_en": job.suggested_description_en,
                "hashtags": job.suggested_hashtags or [],
                "hook_fi": job.suggested_hook_fi,
                "hook_en": job.suggested_hook_en,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False))

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


@router.get("/jobs/{job_id}/thumbnail/candidate/{index}")
def get_thumbnail_candidate(job_id: str, index: int, db: Session = Depends(get_db)):
    """Get a thumbnail candidate by index."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.thumbnail_candidates:
        raise HTTPException(404, "No thumbnail candidates available")

    # Find the candidate with matching index
    candidate = next((c for c in job.thumbnail_candidates if c["index"] == index), None)
    if not candidate or not Path(candidate["path"]).exists():
        raise HTTPException(404, "Thumbnail candidate not found")

    return FileResponse(candidate["path"], media_type="image/jpeg")


@router.post("/jobs/{job_id}/thumbnail/select")
def select_thumbnail(job_id: str, data: dict, db: Session = Depends(get_db)):
    """Select a thumbnail candidate and regenerate final thumbnails with text."""
    from app.services import thumbnail, claude

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    index = data.get("index", 1)
    if not job.thumbnail_candidates:
        raise HTTPException(400, "No thumbnail candidates available")

    # Find the selected candidate
    candidate = next((c for c in job.thumbnail_candidates if c["index"] == index), None)
    if not candidate:
        raise HTTPException(400, "Invalid thumbnail index")

    # Update selected index
    job.selected_thumbnail_index = str(index)

    # Regenerate thumbnails with text overlays using the selected candidate
    export_dir = settings.storage_path / "exports" / job_id

    # Use custom text if provided, otherwise generate with AI
    custom_text_fi = data.get("text_fi")
    custom_text_en = data.get("text_en")

    if custom_text_fi and custom_text_en:
        # Both provided - use custom text
        text_fi = custom_text_fi
        text_en = custom_text_en
    else:
        # Generate with AI
        thumb_text = claude.generate_thumbnail_text(
            job.suggested_title_fi or "",
            job.suggested_title_en or "",
            job.context_description
        )
        text_fi = custom_text_fi or thumb_text.get("text_fi", "KATSO")
        text_en = custom_text_en or thumb_text.get("text_en", "WATCH")

    # Create new thumbnails from selected candidate
    thumb_paths = thumbnail.create_thumbnail_variants(
        candidate["path"],
        export_dir,
        text_fi,
        text_en
    )

    job.thumbnail_path = thumb_paths["clean"]
    job.thumbnail_path_fi = thumb_paths["fi"]
    job.thumbnail_path_en = thumb_paths["en"]

    db.commit()

    return {"status": "ok", "selected": index, "text_fi": text_fi, "text_en": text_en}


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


@router.post("/jobs/{job_id}/youtube")
def upload_to_youtube(job_id: str, data: dict, db: Session = Depends(get_db)):
    """Upload video to YouTube with selected thumbnail and language."""
    from app.services import youtube

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status not in ["review", "completed"]:
        raise HTTPException(400, "Job not ready for upload")

    if job.youtube_url:
        raise HTTPException(400, "Already uploaded to YouTube")

    if not youtube.is_authenticated():
        raise HTTPException(400, "YouTube not authenticated. Go to /api/youtube/auth")

    # Get language preference
    lang = data.get("language", "fi")
    thumb_variant = data.get("thumbnail", "fi")

    # Select title/description based on language
    if lang == "en":
        title = job.suggested_title_en or job.suggested_title_fi or "Video"
        description = job.suggested_description_en or job.suggested_description_fi or ""
    else:
        title = job.suggested_title_fi or job.suggested_title_en or "Video"
        description = job.suggested_description_fi or job.suggested_description_en or ""

    # Select thumbnail
    if thumb_variant == "en" and job.thumbnail_path_en:
        thumbnail_path = job.thumbnail_path_en
    elif thumb_variant == "fi" and job.thumbnail_path_fi:
        thumbnail_path = job.thumbnail_path_fi
    else:
        thumbnail_path = job.thumbnail_path

    # Upload to YouTube
    result = youtube.upload_video(
        video_path=job.output_video_path,
        title=title,
        description=description,
        tags=job.suggested_hashtags or [],
        privacy="private",
        is_short=True,
        thumbnail_path=thumbnail_path
    )

    # Save result
    job.youtube_video_id = result["video_id"]
    job.youtube_url = result["url"]
    db.commit()

    return {
        "status": "uploaded",
        "video_id": result["video_id"],
        "url": result["url"]
    }
