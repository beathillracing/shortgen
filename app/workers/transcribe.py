"""
Main processing worker that chains all steps together.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Job
from app.services import ffmpeg, whisper, claude, storage, thumbnail, youtube


def get_db_session():
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def process_job(job_id: str):
    """
    Main job processor. Runs through all steps:
    1. Stitch multiple videos (if needed)
    2. Extract audio
    3. Transcribe
    4. Analyze with Claude
    5. Render video
    6. Generate thumbnail
    """
    db = get_db_session()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Step 0: Stitch multiple files if present
        import json
        if job.upload_paths:
            update_job_status(db, job, "transcribing", "Stitching video clips...")
            paths = json.loads(job.upload_paths)
            stitched_path = str(storage.get_processing_path(job_id, "stitched.mp4"))
            ffmpeg.stitch_videos(paths, stitched_path)
            input_video = stitched_path
        else:
            input_video = job.upload_path

        # Step 1: Get video info and extract audio
        update_job_status(db, job, "transcribing", "Extracting audio...")

        video_info = ffmpeg.get_video_info(input_video)
        audio_path = str(storage.get_processing_path(job_id, "audio.mp3"))
        ffmpeg.extract_audio(input_video, audio_path)

        # Step 2: Transcribe with Whisper
        update_job_status(db, job, "transcribing", "Transcribing audio...")

        transcription = whisper.transcribe_audio(audio_path)
        job.transcript = transcription["transcript"]
        # Split subtitles into short chunks (3-4 words) for better readability
        job.srt_content = whisper.split_srt_into_chunks(transcription["srt"], max_words=4)
        db.commit()

        # Step 3: Analyze with Claude
        update_job_status(db, job, "analyzing", "Analyzing content...")

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

        # Step 4: Render video
        update_job_status(db, job, "rendering", "Rendering video...")

        # First, cut segments if we have a cut plan
        cut_video_path = str(storage.get_processing_path(job_id, "cut.mp4"))
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
        else:
            # Use original video
            import shutil
            shutil.copy(input_video, cut_video_path)

        # Save SRT file for burning
        srt_path = str(storage.get_processing_path(job_id, "captions.srt"))
        with open(srt_path, "w") as f:
            f.write(job.srt_content or "")

        # Save ASS file for karaoke-style captions
        ass_path = None
        if transcription.get("ass"):
            ass_path = str(storage.get_processing_path(job_id, "captions.ass"))
            with open(ass_path, "w") as f:
                f.write(transcription["ass"])

        # Render final video with captions
        output_path = str(storage.get_export_path(job_id, "video.mp4"))
        ffmpeg.render_video_with_captions(
            cut_video_path,
            output_path,
            srt_path=srt_path,
            ass_path=ass_path,
            burn_captions=(job.burn_captions == "true"),
        )
        job.output_video_path = output_path

        # Step 5: Generate thumbnails with text
        update_job_status(db, job, "rendering", "Generating thumbnails...")

        # Extract base frame at 1/3 of the video
        base_thumb_path = str(storage.get_processing_path(job_id, "thumb_base.jpg"))
        thumb_timestamp = video_info["duration"] / 3
        ffmpeg.extract_frame(input_video, base_thumb_path, thumb_timestamp)

        # Generate thumbnail text in both languages
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

        # Step 6: Auto-post to YouTube if enabled
        if job.youtube_autopost == "true":
            update_job_status(db, job, "rendering", "Uploading to YouTube...")
            try:
                if youtube.is_authenticated():
                    result = youtube.upload_video(
                        video_path=output_path,
                        title=job.suggested_title_fi or job.suggested_title_en or "Short Video",
                        description=job.suggested_description_fi or job.suggested_description_en or "",
                        tags=job.suggested_hashtags or [],
                        privacy="private",  # Upload as private first for safety
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
        update_job_status(db, job, "review", "Ready for review")

    except Exception as e:
        # Mark job as failed
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
