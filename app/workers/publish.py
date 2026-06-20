from pathlib import Path

from app.database import SessionLocal
from app.models import Job
from app.services import meta, tiktok, youtube
from app.services.mobile_accounts import entitlement, refresh_subscription_if_due
from app.services.mobile_oauth import connection_data
from app.services.public_media import media_url


def _set_state(db, job: Job, **updates):
    state = dict(job.publish_status or {})
    state.update(updates)
    job.publish_status = state
    db.commit()


def _metadata(job: Job, language: str) -> tuple[str, str]:
    if language == "en":
        title = job.final_title or job.suggested_title_en or job.suggested_title_fi or "Video"
        description = job.final_description or job.suggested_description_en or job.suggested_description_fi or ""
    else:
        title = job.final_title or job.suggested_title_fi or job.suggested_title_en or "Video"
        description = job.final_description or job.suggested_description_fi or job.suggested_description_en or ""
    return title, description


def _caption(job: Job, language: str, max_length: int) -> str:
    title, description = _metadata(job, language)
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in (job.suggested_hashtags or []))
    return "\n\n".join(part for part in [title, description, hashtags] if part.strip())[:max_length]


def _thumbnail_path(job: Job, variant: str) -> str | None:
    if variant == "en" and job.thumbnail_path_en:
        return job.thumbnail_path_en
    if variant == "fi" and job.thumbnail_path_fi:
        return job.thumbnail_path_fi
    return job.thumbnail_path


def _thumbnail_kind(variant: str) -> str:
    return {"fi": "thumbnail-fi", "en": "thumbnail-en"}.get(variant, "thumbnail")


def _prepare_video(job: Job, thumbnail_path: str | None, prepend_thumbnail: bool = True):
    from app.api.jobs import rerender_video_thumbnail_frame

    if not rerender_video_thumbnail_frame(
        str(job.id),
        job,
        thumbnail_path,
        prepend_thumbnail=prepend_thumbnail,
    ):
        raise ValueError("Could not prepare video for publishing")


def _credentials(db, job: Job, provider: str) -> dict | None:
    if not job.mobile_owner:
        return None
    return connection_data(db, job.mobile_owner, provider)


def _publish_youtube(db, job: Job, options: dict) -> dict:
    if job.youtube_video_id:
        return {"status": "already_posted", "url": job.youtube_url}
    credentials = _credentials(db, job, "youtube")
    if not credentials and not youtube.is_authenticated():
        raise ValueError("YouTube is not authenticated")

    content_type = options["content_type"]
    thumbnail_path = _thumbnail_path(job, options["thumbnail"])
    _prepare_video(job, thumbnail_path, prepend_thumbnail=(content_type == "short"))
    db.commit()

    title, description = _metadata(job, options["language"])
    result = youtube.upload_video(
        video_path=job.output_video_path,
        title=title,
        description=description,
        tags=job.suggested_hashtags or [],
        privacy="public",
        is_short=(content_type == "short"),
        thumbnail_path=thumbnail_path,
        credentials_data=credentials,
    )
    job.youtube_video_id = result["video_id"]
    job.youtube_url = result["url"]
    job.youtube_content_type = content_type
    job.youtube_thumbnail_status = (
        "mobile_selection_required"
        if content_type == "short"
        else ("uploaded" if result.get("thumbnail_uploaded") else "failed")
    )
    job.youtube_thumbnail_error = result.get("thumbnail_error")
    db.commit()
    return {"status": "uploaded", "url": result["url"], "video_id": result["video_id"]}


def _publish_instagram(db, job: Job, options: dict) -> dict:
    if job.instagram_media_id:
        return {"status": "already_posted", "url": job.instagram_url}

    thumbnail_path = _thumbnail_path(job, options["thumbnail"])
    _prepare_video(job, thumbnail_path, prepend_thumbnail=True)
    db.commit()

    result = meta.upload_instagram_reel(
        video_url=media_url(str(job.id), "video"),
        cover_url=media_url(str(job.id), _thumbnail_kind(options["thumbnail"])),
        caption=_caption(job, options["language"], 2200),
        connection_data=_credentials(db, job, "meta"),
    )
    job.instagram_media_id = result["media_id"]
    job.instagram_url = result.get("url")
    job.instagram_status = result.get("status") or "uploaded"
    db.commit()
    return {"status": "uploaded", "url": job.instagram_url, "media_id": job.instagram_media_id}


def _publish_facebook(db, job: Job, options: dict) -> dict:
    if job.facebook_video_id:
        return {"status": "already_posted", "url": job.facebook_url}

    thumbnail_path = _thumbnail_path(job, options["thumbnail"])
    _prepare_video(job, thumbnail_path, prepend_thumbnail=True)
    db.commit()

    result = meta.upload_facebook_reel(
        video_url=media_url(str(job.id), "video"),
        description=_caption(job, options["language"], 5000),
        thumbnail_path=thumbnail_path,
        connection_data=_credentials(db, job, "meta"),
    )
    job.facebook_video_id = result["video_id"]
    job.facebook_url = result.get("url")
    if result.get("thumbnail_error"):
        job.facebook_status = f"uploaded; thumbnail failed: {result['thumbnail_error']}"
    else:
        job.facebook_status = "uploaded with thumbnail" if result.get("thumbnail_uploaded") else "uploaded"
    db.commit()
    return {"status": "uploaded", "url": job.facebook_url, "video_id": job.facebook_video_id}


def _publish_tiktok(db, job: Job, options: dict) -> dict:
    if job.tiktok_publish_id:
        return {"status": "already_uploaded", "publish_id": job.tiktok_publish_id}
    if not tiktok.is_configured():
        raise ValueError("TikTok is not configured")

    thumbnail_path = _thumbnail_path(job, options["thumbnail"])
    _prepare_video(job, thumbnail_path, prepend_thumbnail=True)
    db.commit()

    result = tiktok.upload_video_draft(
        job.output_video_path,
        connection_data=_credentials(db, job, "tiktok"),
    )
    job.tiktok_publish_id = result["publish_id"]
    job.tiktok_url = result.get("url")
    job.tiktok_status = result.get("status") or "draft_uploaded"
    db.commit()
    return {"status": "uploaded", "publish_id": job.tiktok_publish_id}


PUBLISHERS = {
    "youtube": _publish_youtube,
    "instagram": _publish_instagram,
    "facebook": _publish_facebook,
    "tiktok": _publish_tiktok,
}


def publish_job(job_id: str, options: dict):
    db = SessionLocal()
    job = None
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError("Job not found")
        if not job.output_video_path or not Path(job.output_video_path).exists():
            raise ValueError("Video is not ready")
        if job.mobile_owner:
            try:
                current = refresh_subscription_if_due(db, job.mobile_owner)
            except Exception:
                current = entitlement(db, job.mobile_owner)
            if not current["publishing_enabled"]:
                raise ValueError("Beathill Studio Pro is no longer active")

        platforms = options["platforms"]
        results = {}
        errors = {}
        _set_state(
            db,
            job,
            status="running",
            current_platform=None,
            completed=0,
            total=len(platforms),
            results=results,
            errors=errors,
        )

        for index, platform in enumerate(platforms):
            _set_state(db, job, current_platform=platform, completed=index)
            try:
                results[platform] = PUBLISHERS[platform](db, job, options)
            except Exception as exc:
                errors[platform] = str(exc)
            _set_state(
                db,
                job,
                completed=index + 1,
                results=dict(results),
                errors=dict(errors),
            )

        final_status = "completed" if not errors else ("partial" if results else "failed")
        _set_state(db, job, status=final_status, current_platform=None)
        return {"status": final_status, "results": results, "errors": errors}
    except Exception as exc:
        if job:
            _set_state(db, job, status="failed", current_platform=None, fatal_error=str(exc))
        raise
    finally:
        db.close()
