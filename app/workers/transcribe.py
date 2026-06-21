"""
Main processing worker that chains all steps together.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Job
from app.services import ffmpeg, whisper, claude, storage, thumbnail, youtube
from app.services.progress import set_progress, clear_progress


def get_db_session():
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def _output_dims(job):
    if getattr(job, "orientation", None) == "horizontal":
        return 1920, 1080
    return 1080, 1920


def analyze_and_prepare_video(db, job: Job, input_video: str, cut_video_path: str):
    """Transcribe, analyze, cut, and prepare caption files before thumbnail selection."""
    video_info = ffmpeg.get_video_info(input_video)

    update_job_status(db, job, "transcribing", "Extracting audio...", 20)
    audio_path = str(storage.get_processing_path(str(job.id), "audio.mp3"))
    ffmpeg.extract_audio(input_video, audio_path)

    update_job_status(db, job, "transcribing", "Transcribing audio...", 30)
    cap_w, cap_h = _output_dims(job)
    transcription = whisper.transcribe_audio(
        audio_path,
        highlight_color=job.caption_highlight_color,
        border=(job.caption_border != "false"),
        border_color=job.caption_border_color,
        width=cap_w,
        height=cap_h,
    )
    job.transcript = transcription["transcript"]
    job.srt_content = whisper.split_srt_into_chunks(transcription["srt"], max_words=4)
    db.commit()

    update_job_status(
        db,
        job,
        "analyzing",
        "Generating titles, descriptions and thumbnail text...",
        45,
    )
    analysis = claude.analyze_transcript(
        job.transcript,
        video_info["duration"],
        context=job.context_description,
        minimal_cuts=(job.minimal_cuts == "true"),
    )

    job.cut_plan = analysis.get("cut_plan")
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

    # Older/fallback model responses may omit the new fields.
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
        db.commit()

    update_job_status(db, job, "rendering", "Preparing final cut...", 55)
    segments_to_keep = []
    if job.cut_plan and job.cut_plan.get("segments"):
        for segment in job.cut_plan["segments"]:
            if segment.get("keep", True):
                segments_to_keep.append(
                    {"start": segment["start"], "end": segment["end"]}
                )

    if segments_to_keep:
        ffmpeg.cut_segments(input_video, cut_video_path, segments_to_keep)

    srt_path = storage.get_processing_path(str(job.id), "captions.srt")
    srt_path.write_text(job.srt_content or "")

    if transcription.get("ass"):
        ass_path = storage.get_processing_path(str(job.id), "captions.ass")
        ass_path.write_text(transcription["ass"])


def process_job(job_id: str):
    """
    Phase 1: Analyze the video, then wait for thumbnail selection.
    1. Stitch multiple videos (if needed)
    2. Transcribe and analyze content
    3. Prepare smart cuts and captions
    4. Extract thumbnail candidates from the prepared video
    5. STOP - wait for user to select thumbnail with AI text prefilled
    """
    db = get_db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Step 0: Stitch multiple files if present
        import json
        import shutil
        if job.upload_paths:
            update_job_status(db, job, "processing", "Combining video clips...", 5)
            paths = json.loads(job.upload_paths)
            stitched_path = str(storage.get_processing_path(job_id, "stitched.mp4"))
            ffmpeg.stitch_videos(paths, stitched_path)
            input_video = stitched_path
        else:
            input_video = job.upload_path

        # Step 1: Cut segments if needed (prepare the base video)
        update_job_status(db, job, "processing", "Preparing video...", 10)
        cut_video_path = str(storage.get_processing_path(job_id, "cut.mp4"))

        # For now, just copy - we'll do smart cuts after transcription in phase 2
        shutil.copy(input_video, cut_video_path)

        job.upload_path = input_video
        db.commit()

        analyze_and_prepare_video(db, job, input_video, cut_video_path)

        update_job_status(db, job, "rendering", "Preparing thumbnails...", 65)
        thumb_dir = str(storage.get_export_path(job_id, ""))
        candidates = ffmpeg.extract_thumbnail_candidates(cut_video_path, thumb_dir, count=10)
        job.thumbnail_candidates = candidates
        db.commit()

        update_job_status(
            db,
            job,
            "thumbnail_selection",
            "Choose your thumbnail and review the suggested text",
            70,
        )
        clear_progress(str(job.id))

    except Exception as e:
        db.rollback()
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = "error"
        db.commit()
        _notify_push(db, job)
        raise

    finally:
        db.close()


def prepare_existing_thumbnail_selection(job_id: str):
    """Upgrade a job paused under the old pre-analysis thumbnail workflow."""
    db = get_db_session()
    job = None
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status != "thumbnail_selection":
            raise ValueError(f"Job is not awaiting thumbnail selection: {job.status}")

        cut_video_path = str(storage.get_processing_path(job_id, "cut.mp4"))
        analyze_and_prepare_video(db, job, job.upload_path, cut_video_path)

        update_job_status(db, job, "rendering", "Refreshing thumbnails...", 65)
        thumb_dir = str(storage.get_export_path(job_id, ""))
        job.thumbnail_candidates = ffmpeg.extract_thumbnail_candidates(
            cut_video_path,
            thumb_dir,
            count=10,
        )
        db.commit()
        update_job_status(
            db,
            job,
            "thumbnail_selection",
            "Choose your thumbnail and review the suggested text",
            70,
        )
        clear_progress(str(job.id))
    except Exception as exc:
        if job:
            db.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.current_step = "error"
            db.commit()
            _notify_push(db, job)
        raise
    finally:
        db.close()


def continue_processing(job_id: str, selected_thumbnail_index: int = 1, thumbnail_text_fi: str = None, thumbnail_text_en: str = None):
    """
    Phase 2: Continue processing after thumbnail selection.
    1. Apply selected thumbnail and suggested/custom text
    2. Render the already analyzed/prepared video
    """
    db = get_db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        input_video = job.upload_path
        cut_video_path = str(storage.get_processing_path(job_id, "cut.mp4"))

        # Get the selected thumbnail
        selected_thumb = None
        if job.thumbnail_candidates:
            selected_thumb = next(
                (c for c in job.thumbnail_candidates if c["index"] == selected_thumbnail_index),
                job.thumbnail_candidates[0] if job.thumbnail_candidates else None
            )

        base_thumb_path = selected_thumb["path"] if selected_thumb else None
        job.selected_thumbnail_index = str(selected_thumbnail_index)

        # Compatibility for jobs that reached selection under the old workflow.
        if not job.transcript or not job.suggested_title_fi:
            analyze_and_prepare_video(db, job, input_video, cut_video_path)

        srt_path = str(storage.get_processing_path(job_id, "captions.srt"))
        ass_file = storage.get_processing_path(job_id, "captions.ass")
        ass_path = str(ass_file) if ass_file.exists() else None

        update_job_status(db, job, "rendering", "Creating thumbnail...", 75)

        text_fi = (
            thumbnail_text_fi
            or job.suggested_thumbnail_text_fi
            or "KATSO"
        )
        text_en = (
            thumbnail_text_en
            or job.suggested_thumbnail_text_en
            or "WATCH"
        )

        export_dir = storage.get_export_path(job_id, "")
        out_w, out_h = _output_dims(job)
        thumb_paths = thumbnail.create_thumbnail_variants(
            base_thumb_path,
            export_dir,
            text_fi,
            text_en,
            text_color=job.thumbnail_text_color,
            target_width=out_w,
            target_height=out_h,
        )

        job.thumbnail_path = thumb_paths["clean"]
        job.thumbnail_path_fi = thumb_paths["fi"]
        job.thumbnail_path_en = thumb_paths["en"]
        db.commit()

        update_job_status(db, job, "rendering", "Rendering video...", 80)
        output_path = str(storage.get_export_path(job_id, "video.mp4"))
        ffmpeg.render_video_with_captions_and_outro(
            cut_video_path,
            output_path,
            srt_path=srt_path,
            ass_path=ass_path,
            burn_captions=(job.burn_captions == "true"),
            job_id=str(job.id),
            thumbnail_path=thumb_paths["fi"],  # Prepend Finnish thumbnail WITH TEXT
            thumbnail_duration=settings.thumbnail_duration_seconds,
            target_width=out_w,
            target_height=out_h,
            progress_base=80,
            progress_ceiling=99,
        )
        job.output_video_path = output_path

        # Step 7: Auto-post to YouTube if enabled
        if job.youtube_autopost == "true":
            update_job_status(db, job, "rendering", "Uploading to YouTube...", 90)
            try:
                if youtube.is_authenticated():
                    result = youtube.upload_video(
                        video_path=output_path,
                        title=job.suggested_title_fi or job.suggested_title_en or "Short Video",
                        description=job.suggested_description_fi or job.suggested_description_en or "",
                        tags=job.suggested_hashtags or [],
                        privacy="public",
                        is_short=True,
                        thumbnail_path=job.thumbnail_path_fi or job.thumbnail_path
                    )
                    job.youtube_video_id = result["video_id"]
                    job.youtube_url = result["url"]
                    job.youtube_content_type = "short"
                    job.youtube_thumbnail_status = "mobile_selection_required"
                    job.youtube_thumbnail_error = result.get("thumbnail_error")
                else:
                    job.error_message = "YouTube auto-post enabled but not authenticated"
            except Exception as yt_err:
                job.error_message = f"YouTube upload failed: {str(yt_err)}"

        # Done!
        update_job_status(db, job, "review", "Ready for review", 100)
        clear_progress(str(job.id))

    except Exception as e:
        # Mark job as failed
        db.rollback()
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
