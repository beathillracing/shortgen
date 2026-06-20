"""
Worker for processing pre-captioned videos (e.g., from CapCut).
Skips caption generation, focuses on:
- Removing CapCut watermark/outro
- Adding your own watermark
- Generating titles, tags, descriptions from audio
- Creating thumbnails
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Job
from app.services import ffmpeg, whisper, claude, storage, thumbnail
from app.services.progress import set_progress, clear_progress


def get_db_session():
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def process_precaptioned_job(job_id: str):
    """
    Process a pre-captioned video (already has captions burned in).

    Steps:
    1. Remove CapCut watermark/outro
    2. Add your own watermark
    3. Extract audio & transcribe (for metadata only)
    4. Generate titles, tags, descriptions with Claude
    5. Generate thumbnails
    """
    db = get_db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        input_video = job.upload_path
        video_info = ffmpeg.get_video_info(input_video)
        duration = video_info["duration"]

        # Step 1: Remove CapCut watermark, add our watermark, append outro (0-55%)
        # All done in ONE FFmpeg pass for speed
        update_job_status(db, job, "rendering", "Processing video...", 0)

        trim_seconds = float(job.remove_outro_seconds or "3")
        output_path = str(storage.get_export_path(job_id, "video.mp4"))

        ffmpeg.remove_capcut_watermark(
            input_video,
            output_path,
            trim_end_seconds=trim_seconds,
            cover_corner=True,
            job_id=job_id,
            duration=duration,
            append_outro=True,  # Outro appended in same encode
            progress_base=0,
            progress_ceiling=45,
        )
        job.output_video_path = output_path

        # Step 2: Extract audio for transcription (55%)
        update_job_status(db, job, "transcribing", "Extracting audio...", 50)

        video_info = ffmpeg.get_video_info(output_path)
        audio_path = str(storage.get_processing_path(job_id, "audio.mp3"))
        ffmpeg.extract_audio(output_path, audio_path)

        # Step 3: Transcribe (for metadata generation only) (60-75%)
        update_job_status(db, job, "transcribing", "Transcribing audio...", 60)

        transcription = whisper.transcribe_audio(audio_path)
        job.transcript = transcription["transcript"]
        db.commit()

        # Step 4: Analyze with Claude for titles/tags/descriptions (75-85%)
        update_job_status(db, job, "analyzing", "Generating titles and tags...", 75)

        analysis = claude.analyze_transcript(
            job.transcript,
            video_info["duration"],
            context=job.context_description,
            minimal_cuts=True
        )

        job.suggested_title_fi = analysis.get("title_fi", "")
        job.suggested_title_en = analysis.get("title_en", "")
        job.suggested_description_fi = analysis.get("description_fi", "")
        job.suggested_description_en = analysis.get("description_en", "")
        job.suggested_hashtags = analysis.get("hashtags", [])
        job.suggested_hook_fi = analysis.get("hook_fi", "")
        job.suggested_hook_en = analysis.get("hook_en", "")
        job.suggested_thumbnail_text_fi = analysis.get("thumbnail_text_fi", "")
        job.suggested_thumbnail_text_en = analysis.get("thumbnail_text_en", "")
        db.commit()

        # Step 5: Generate thumbnails (85-100%)
        update_job_status(db, job, "rendering", "Preparing thumbnails...", 85)

        # Extract multiple thumbnail candidates for user to choose from
        thumb_dir = str(storage.get_export_path(job_id, ""))
        candidates = ffmpeg.extract_thumbnail_candidates(output_path, thumb_dir, count=10)
        job.thumbnail_candidates = candidates

        # Use first candidate as default base
        base_thumb_path = candidates[0]["path"] if candidates else str(storage.get_processing_path(job_id, "thumb_base.jpg"))
        if not candidates:
            thumb_timestamp = video_info["duration"] / 3
            ffmpeg.extract_frame(output_path, base_thumb_path, thumb_timestamp)

        if not job.suggested_thumbnail_text_fi or not job.suggested_thumbnail_text_en:
            thumb_text = claude.generate_thumbnail_text(
                job.suggested_title_fi or "",
                job.suggested_title_en or "",
                job.context_description,
            )
            job.suggested_thumbnail_text_fi = (
                job.suggested_thumbnail_text_fi or thumb_text.get("text_fi", "KATSO")
            )
            job.suggested_thumbnail_text_en = (
                job.suggested_thumbnail_text_en or thumb_text.get("text_en", "WATCH")
            )

        # Create thumbnails with text overlays
        export_dir = storage.get_export_path(job_id, "")
        thumb_paths = thumbnail.create_thumbnail_variants(
            base_thumb_path,
            export_dir,
            job.suggested_thumbnail_text_fi or "KATSO",
            job.suggested_thumbnail_text_en or "WATCH",
        )

        job.thumbnail_path = thumb_paths["clean"]
        job.thumbnail_path_fi = thumb_paths["fi"]
        job.thumbnail_path_en = thumb_paths["en"]

        # Done!
        update_job_status(db, job, "review", "Ready for review", 100)
        clear_progress(job_id)

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = "error"
        db.commit()
        _notify_push(db, job)
        raise

    finally:
        db.close()


def update_job_status(db, job, status, step, percent=None):
    """Helper to update job status."""
    job.status = status
    job.current_step = step
    db.commit()
    if percent is not None:
        set_progress(str(job.id), percent, step)
    if status in ("thumbnail_selection", "review", "completed"):
        _notify_push(db, job)


def _notify_push(db, job):
    try:
        from app.services.push import notify_job
        notify_job(db, job)
    except Exception:
        pass
