from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from redis import Redis
from rq import Queue

from app.database import get_db
from app.models import Job
from app.config import settings
from app.services.storage import save_upload

router = APIRouter()


def get_queue():
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue(connection=redis_conn)


def create_and_queue_job(
    db: Session,
    upload_paths: list[str],
    filenames: list[str],
    *,
    context: str = "",
    minimal_cuts: str = "false",
    burn_captions: str = "false",
    youtube_autopost: str = "false",
    precaptioned: str = "false",
    remove_outro_seconds: str = "3",
    mobile_owner: str | None = None,
) -> Job:
    job = Job(
        original_filename=", ".join(filenames) if len(filenames) > 1 else filenames[0],
        upload_path=upload_paths[0],
        context_description=context if context else None,
        minimal_cuts=minimal_cuts,
        burn_captions=burn_captions,
        youtube_autopost=youtube_autopost,
        precaptioned=precaptioned,
        remove_outro_seconds=remove_outro_seconds,
        mobile_owner=mobile_owner,
        status="pending",
        current_step="uploaded",
    )

    if len(upload_paths) > 1:
        import json

        job.upload_paths = json.dumps(upload_paths)

    db.add(job)
    db.commit()
    db.refresh(job)

    queue = get_queue()
    worker = (
        "app.workers.precaptioned.process_precaptioned_job"
        if precaptioned == "true"
        else "app.workers.transcribe.process_job"
    )
    queue.enqueue(worker, str(job.id), job_timeout="30m")
    return job


@router.post("/upload")
async def upload_video(
    files: List[UploadFile] = File(...),
    context: str = Form(""),
    minimal_cuts: str = Form("false"),
    burn_captions: str = Form("false"),
    youtube_autopost: str = Form("false"),
    precaptioned: str = Form("false"),  # Video already has captions (e.g. from CapCut)
    remove_outro_seconds: str = Form("3"),  # Seconds to trim from end for CapCut outro
    db: Session = Depends(get_db),
):
    """Upload video file(s) and start processing. Multiple files will be stitched together."""
    allowed_types = [".mp4", ".mov", ".avi", ".mkv", ".webm"]
    upload_paths = []
    filenames = []

    for file in files:
        ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""

        if ext not in allowed_types:
            raise HTTPException(400, f"File type not allowed. Use: {', '.join(allowed_types)}")

        content = await file.read()
        upload_path = save_upload(content, file.filename)
        upload_paths.append(upload_path)
        filenames.append(file.filename)

    job = create_and_queue_job(
        db,
        upload_paths,
        filenames,
        context=context,
        minimal_cuts=minimal_cuts,
        burn_captions=burn_captions,
        youtube_autopost=youtube_autopost,
        precaptioned=precaptioned,
        remove_outro_seconds=remove_outro_seconds,
    )

    return {
        "job_id": str(job.id),
        "status": "pending",
        "message": f"{'Videos' if len(files) > 1 else 'Video'} uploaded, processing started"
    }
