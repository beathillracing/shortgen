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

        # Step 1: Remove CapCut watermark and add our watermark
        update_job_status(db, job, "rendering", "Removing CapCut watermark...")

        trim_seconds = float(job.remove_outro_seconds or "3")
        output_path = str(storage.get_export_path(job_id, "video.mp4"))

        ffmpeg.remove_capcut_watermark(
            input_video,
            output_path,
            trim_end_seconds=trim_seconds,
            cover_corner=True,  # Cover the corner watermark
        )
        job.output_video_path = output_path

        # Step 2: Extract audio for transcription
        update_job_status(db, job, "transcribing", "Extracting audio...")

        video_info = ffmpeg.get_video_info(output_path)  # Use processed video
        audio_path = str(storage.get_processing_path(job_id, "audio.mp3"))
        ffmpeg.extract_audio(output_path, audio_path)

        # Step 3: Transcribe (for metadata generation only)
        update_job_status(db, job, "transcribing", "Transcribing for metadata...")

        transcription = whisper.transcribe_audio(audio_path)
        job.transcript = transcription["transcript"]
        # We don't need SRT since video already has captions
        db.commit()

        # Step 4: Analyze with Claude for titles/tags/descriptions
        update_job_status(db, job, "analyzing", "Generating titles and tags...")

        analysis = claude.analyze_transcript(
            job.transcript,
            video_info["duration"],
            context=job.context_description,
            minimal_cuts=True  # No cutting needed, video is already edited
        )

        job.suggested_title_fi = analysis.get("title_fi", "")
        job.suggested_title_en = analysis.get("title_en", "")
        job.suggested_description_fi = analysis.get("description_fi", "")
        job.suggested_description_en = analysis.get("description_en", "")
        job.suggested_hashtags = analysis.get("hashtags", [])
        job.suggested_hook_fi = analysis.get("hook_fi", "")
        job.suggested_hook_en = analysis.get("hook_en", "")
        db.commit()

        # Step 5: Generate thumbnails
        update_job_status(db, job, "rendering", "Generating thumbnails...")

        # Extract base frame at 1/3 of the video
        base_thumb_path = str(storage.get_processing_path(job_id, "thumb_base.jpg"))
        thumb_timestamp = video_info["duration"] / 3
        ffmpeg.extract_frame(output_path, base_thumb_path, thumb_timestamp)

        # Generate thumbnail text
        thumb_text = claude.generate_thumbnail_text(
            job.suggested_title_fi or "",
            job.suggested_title_en or "",
            job.context_description
        )

        # Create thumbnails with text overlays
        export_dir = storage.get_export_path(job_id, "")
        thumb_paths = thumbnail.create_thumbnail_variants(
            base_thumb_path,
            export_dir,
            thumb_text.get("text_fi", "KATSO"),
            thumb_text.get("text_en", "WATCH")
        )

        job.thumbnail_path = thumb_paths["clean"]
        job.thumbnail_path_fi = thumb_paths["fi"]
        job.thumbnail_path_en = thumb_paths["en"]

        # Done!
        update_job_status(db, job, "review", "Ready for review")

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = "error"
        db.commit()
        raise

    finally:
        db.close()


def update_job_status(db, job, status, step):
    """Helper to update job status."""
    job.status = status
    job.current_step = step
    db.commit()
