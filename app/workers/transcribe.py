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


def process_job(job_id: str):
    """
    Phase 1: Extract thumbnails and wait for user selection.
    1. Stitch multiple videos (if needed)
    2. Extract thumbnail candidates
    3. STOP - wait for user to select thumbnail
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
            update_job_status(db, job, "processing", "Stitching video clips...", 5)
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

        # Step 2: Extract thumbnail candidates
        update_job_status(db, job, "processing", "Extracting thumbnail options...", 20)
        thumb_dir = str(storage.get_export_path(job_id, ""))
        candidates = ffmpeg.extract_thumbnail_candidates(cut_video_path, thumb_dir, count=10)
        job.thumbnail_candidates = candidates

        # Store the input video path for phase 2
        job.upload_path = input_video  # Update to stitched if applicable
        db.commit()

        # STOP HERE - wait for user to select thumbnail
        update_job_status(db, job, "thumbnail_selection", "Choose your thumbnail", 25)
        clear_progress(str(job.id))

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = "error"
        db.commit()
        raise

    finally:
        db.close()


def continue_processing(job_id: str, selected_thumbnail_index: int = 1, thumbnail_text_fi: str = None, thumbnail_text_en: str = None):
    """
    Phase 2: Continue processing after thumbnail selection.
    1. Extract audio & transcribe
    2. Analyze with Claude
    3. Generate thumbnail with text
    4. Render video with selected thumbnail prepended
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

        # Step 1: Extract audio
        update_job_status(db, job, "transcribing", "Extracting audio...", 30)
        video_info = ffmpeg.get_video_info(input_video)
        audio_path = str(storage.get_processing_path(job_id, "audio.mp3"))
        ffmpeg.extract_audio(input_video, audio_path)

        # Step 2: Transcribe with Whisper large-v3
        update_job_status(db, job, "transcribing", "Transcribing with Whisper large-v3...", 35)
        transcription = whisper.transcribe_audio(audio_path)
        job.transcript = transcription["transcript"]
        job.srt_content = whisper.split_srt_into_chunks(transcription["srt"], max_words=4)
        db.commit()

        # Step 3: Analyze with Claude
        update_job_status(db, job, "analyzing", "Generating titles & descriptions...", 50)
        analysis = claude.analyze_transcript(
            job.transcript,
            video_info["duration"],
            context=job.context_description,
            minimal_cuts=(job.minimal_cuts == "true")
        )

        job.cut_plan = analysis.get("cut_plan")
        job.suggested_title_fi = analysis.get("title_fi", "")
        job.suggested_title_en = analysis.get("title_en", "")
        job.suggested_description_fi = analysis.get("description_fi", "")
        job.suggested_description_en = analysis.get("description_en", "")
        job.suggested_hashtags = analysis.get("hashtags", [])
        job.suggested_hook_fi = analysis.get("hook_fi", "")
        job.suggested_hook_en = analysis.get("hook_en", "")
        db.commit()

        # Step 4: Cut segments if we have a cut plan
        update_job_status(db, job, "rendering", "Cutting video segments...", 55)
        segments_to_keep = []
        if job.cut_plan and job.cut_plan.get("segments"):
            for seg in job.cut_plan["segments"]:
                if seg.get("keep", True):
                    segments_to_keep.append({
                        "start": seg["start"],
                        "end": seg["end"]
                    })

        if segments_to_keep:
            ffmpeg.cut_segments(input_video, cut_video_path, segments_to_keep)
        # else: already copied in phase 1

        # Save caption files
        srt_path = str(storage.get_processing_path(job_id, "captions.srt"))
        with open(srt_path, "w") as f:
            f.write(job.srt_content or "")

        ass_path = None
        if transcription.get("ass"):
            ass_path = str(storage.get_processing_path(job_id, "captions.ass"))
            with open(ass_path, "w") as f:
                f.write(transcription["ass"])

        # Step 5: Generate thumbnail with text
        update_job_status(db, job, "rendering", "Creating thumbnail...", 60)

        # Use custom text if provided, otherwise generate with AI
        if thumbnail_text_fi and thumbnail_text_en:
            text_fi = thumbnail_text_fi
            text_en = thumbnail_text_en
        else:
            thumb_text = claude.generate_thumbnail_text(
                job.suggested_title_fi or "",
                job.suggested_title_en or "",
                job.context_description
            )
            text_fi = thumbnail_text_fi or thumb_text.get("text_fi", "KATSO")
            text_en = thumbnail_text_en or thumb_text.get("text_en", "WATCH")

        export_dir = storage.get_export_path(job_id, "")
        thumb_paths = thumbnail.create_thumbnail_variants(
            base_thumb_path,
            export_dir,
            text_fi,
            text_en
        )

        job.thumbnail_path = thumb_paths["clean"]
        job.thumbnail_path_fi = thumb_paths["fi"]
        job.thumbnail_path_en = thumb_paths["en"]
        db.commit()

        # Step 6: Render video with thumbnail prepended
        update_job_status(db, job, "rendering", "Rendering video with karaoke captions...", 65)
        output_path = str(storage.get_export_path(job_id, "video.mp4"))
        ffmpeg.render_video_with_captions_and_outro(
            cut_video_path,
            output_path,
            srt_path=srt_path,
            ass_path=ass_path,
            burn_captions=(job.burn_captions == "true"),
            job_id=str(job.id),
            thumbnail_path=thumb_paths["fi"],  # Prepend Finnish thumbnail WITH TEXT
            thumbnail_duration=0.3,
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
                        privacy="private",
                        is_short=True,
                        thumbnail_path=job.thumbnail_path_fi or job.thumbnail_path
                    )
                    job.youtube_video_id = result["video_id"]
                    job.youtube_url = result["url"]
                else:
                    job.error_message = "YouTube auto-post enabled but not authenticated"
            except Exception as yt_err:
                job.error_message = f"YouTube upload failed: {str(yt_err)}"

        # Done!
        update_job_status(db, job, "review", "Ready for review", 100)
        clear_progress(str(job.id))

    except Exception as e:
        # Mark job as failed
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = "error"
        db.commit()
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
