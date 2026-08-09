import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.config import settings
from app.services import meta, mobile_oauth, tiktok
from app.services.job_metadata import metadata_for_language
from app.services.public_media import media_url

router = APIRouter()


def _web_return_key(provider: str) -> str:
    """Query key the web client watches for after an OAuth round trip."""
    return {"meta": "facebook"}.get(provider.lower(), provider.lower())


def _mobile_oauth_complete(provider: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta name='viewport' content='width=device-width'>"
        "<title>Account connected</title>"
        "<main style='font:16px system-ui;text-align:center;padding:48px 20px'>"
        f"<h1>{provider} connected</h1>"
        "<p>You can close this page and return to Beathill Studio.</p>"
        f"<p><a href='https://studio.beathillracing.fi/?{_web_return_key(provider)}=connected' "
        "style='display:inline-block;margin-top:8px;padding:12px 22px;border-radius:100px;"
        "background:#167A45;color:#fff;text-decoration:none;font-weight:600'>"
        "Back to Beathill Studio</a></p></main>"
    )


def _instagram_signed_request(value: str) -> dict:
    try:
        signature_text, payload_text = value.split(".", 1)
        signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(
            settings.instagram_app_secret.encode(),
            payload_text.encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = base64.urlsafe_b64decode(
            payload_text + "=" * (-len(payload_text) % 4)
        )
        return json.loads(payload)
    except Exception as exc:
        raise HTTPException(400, "Invalid Instagram signed request") from exc


def _deletion_confirmation(user_id: str) -> str:
    payload = f"{user_id}:{int(time.time())}:{secrets.token_urlsafe(12)}"
    signature = hmac.new(
        settings.secret_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode().rstrip("=")


def _verify_deletion_confirmation(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        payload, signature = decoded.rsplit(":", 1)
        expected = hmac.new(
            settings.secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


def _job_or_404(job_id: str, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ["review", "completed"]:
        raise HTTPException(400, "Job not ready for posting")
    if not job.output_video_path or not Path(job.output_video_path).exists():
        raise HTTPException(400, "Video is not ready")
    return job


def _caption(job: Job, language: str, max_length: int) -> str:
    title, description = metadata_for_language(job, language)
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in (job.suggested_hashtags or []))
    caption = "\n\n".join(part for part in [title, description, hashtags] if part.strip())
    return caption[:max_length]


def _thumbnail_path(job: Job, variant: str) -> str | None:
    if variant == "en" and job.thumbnail_path_en:
        return job.thumbnail_path_en
    if variant == "fi" and job.thumbnail_path_fi:
        return job.thumbnail_path_fi
    return job.thumbnail_path


def _thumbnail_kind(variant: str) -> str:
    if variant == "en":
        return "thumbnail-en"
    if variant == "fi":
        return "thumbnail-fi"
    return "thumbnail"


def _ensure_public_base_url():
    if settings.base_url.startswith("http://localhost") or settings.base_url.startswith("http://127.0.0.1"):
        raise HTTPException(400, "BASE_URL must be public HTTPS for Meta to fetch video files")


@router.get("/meta/status")
def meta_status():
    return meta.status()


@router.get("/meta/auth")
def meta_auth():
    auth_url = meta.get_auth_url()
    if not auth_url:
        raise HTTPException(400, "Meta app credentials are not configured")
    return RedirectResponse(auth_url)


@router.get("/meta/callback")
def meta_callback(request: Request, db: Session = Depends(get_db)):
    if error := request.query_params.get("error_message"):
        raise HTTPException(400, error)
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Missing Meta OAuth code")
    state = request.query_params.get("state")
    try:
        if state and mobile_oauth.handle_meta_callback(db, code, state):
            return _mobile_oauth_complete("Meta")
        meta.handle_callback(code, state)
    except Exception as exc:
        raise HTTPException(400, f"Meta OAuth failed: {exc}") from exc
    return RedirectResponse("/?meta=connected")


@router.get("/instagram/callback")
def instagram_callback(request: Request, db: Session = Depends(get_db)):
    if error := request.query_params.get("error_description"):
        raise HTTPException(400, error)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(400, "Missing Instagram OAuth response")
    try:
        if mobile_oauth.handle_instagram_callback(db, code, state):
            return _mobile_oauth_complete("Instagram")
    except Exception as exc:
        raise HTTPException(400, f"Instagram OAuth failed: {exc}") from exc
    raise HTTPException(400, "Invalid or expired Instagram OAuth state")


@router.post("/instagram/deauthorize")
async def instagram_deauthorize(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    payload = _instagram_signed_request(str(form.get("signed_request") or ""))
    mobile_oauth.disconnect_provider_user(db, "instagram", str(payload.get("user_id") or ""))
    return {"success": True}


@router.post("/instagram/data-deletion")
async def instagram_data_deletion(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    payload = _instagram_signed_request(str(form.get("signed_request") or ""))
    mobile_oauth.disconnect_provider_user(db, "instagram", str(payload.get("user_id") or ""))
    confirmation_code = _deletion_confirmation(str(payload.get("user_id") or "unknown"))
    return {
        "url": (
            f"{settings.base_url.rstrip('/')}/api/instagram/data-deletion/"
            f"{confirmation_code}"
        ),
        "confirmation_code": confirmation_code,
    }


@router.get("/instagram/data-deletion/{confirmation_code}")
def instagram_data_deletion_status(confirmation_code: str):
    if not _verify_deletion_confirmation(confirmation_code):
        raise HTTPException(404, "Deletion request not found")
    return HTMLResponse(
        "<!doctype html><meta name='viewport' content='width=device-width'>"
        "<title>Data deletion status</title>"
        "<main style='font:16px system-ui;text-align:center;padding:48px 20px'>"
        "<h1>Instagram data deleted</h1>"
        f"<p>Confirmation code: {confirmation_code}</p></main>"
    )


@router.get("/meta/pages")
def meta_pages():
    return {"pages": meta.list_pages()}


@router.post("/meta/select-page")
def meta_select_page(data: dict):
    page_id = data.get("page_id")
    if not page_id:
        raise HTTPException(400, "page_id is required")
    try:
        return meta.select_page(page_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/meta/disconnect")
def meta_disconnect():
    meta.disconnect()
    return {"status": "disconnected"}


@router.get("/tiktok/status")
def tiktok_status():
    return tiktok.status()


@router.get("/tiktok/auth")
def tiktok_auth():
    auth_url = tiktok.get_auth_url()
    if not auth_url:
        raise HTTPException(400, "TikTok app credentials are not configured")
    return RedirectResponse(auth_url)


@router.get("/tiktok/callback")
def tiktok_callback(request: Request, db: Session = Depends(get_db)):
    if error := request.query_params.get("error_description"):
        raise HTTPException(400, error)
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Missing TikTok OAuth code")
    state = request.query_params.get("state")
    try:
        if state and mobile_oauth.handle_tiktok_callback(db, code, state):
            return _mobile_oauth_complete("TikTok")
        tiktok.handle_callback(code, state)
    except Exception as exc:
        raise HTTPException(400, f"TikTok OAuth failed: {exc}") from exc
    return RedirectResponse("/?tiktok=connected")


@router.post("/tiktok/disconnect")
def tiktok_disconnect():
    tiktok.disconnect()
    return {"status": "disconnected"}


@router.post("/jobs/{job_id}/publish")
def queue_publish(job_id: str, data: dict, db: Session = Depends(get_db)):
    job = _job_or_404(job_id, db)
    platforms = data.get("platforms") or []
    allowed = ["youtube", "instagram", "facebook", "tiktok"]
    platforms = [platform for platform in allowed if platform in platforms]
    if not platforms:
        raise HTTPException(400, "Select at least one publishing platform")

    current = job.publish_status or {}
    if current.get("status") in ["queued", "running"]:
        raise HTTPException(409, "A publishing job is already running")

    content_type = data.get("content_type", "short")
    if content_type not in ["short", "video"]:
        raise HTTPException(400, "content_type must be short or video")

    options = {
        "platforms": platforms,
        "language": data.get("language", "fi"),
        "thumbnail": data.get("thumbnail", "fi"),
        "content_type": content_type,
    }
    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue(connection=redis_conn)
    rq_job = queue.enqueue(
        "app.workers.publish.publish_job",
        job_id,
        options,
        job_timeout="30m",
        result_ttl=86400,
        failure_ttl=86400,
    )
    job.publish_queue_id = rq_job.id
    job.publish_status = {
        "status": "queued",
        "platforms": platforms,
        "current_platform": None,
        "completed": 0,
        "total": len(platforms),
        "results": {},
        "errors": {},
    }
    db.commit()
    return {"status": "queued", "queue_id": rq_job.id, "platforms": platforms}


@router.get("/jobs/{job_id}/publish/status")
def publishing_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job.publish_status or {"status": "idle"}


@router.post("/jobs/{job_id}/instagram")
def post_to_instagram(job_id: str, data: dict, db: Session = Depends(get_db)):
    from app.api.jobs import rerender_video_thumbnail_frame

    _ensure_public_base_url()
    job = _job_or_404(job_id, db)
    if job.instagram_media_id:
        raise HTTPException(409, "Already posted to Instagram. Reset the saved post first to post again.")
    language = data.get("language", "fi")
    thumbnail = data.get("thumbnail", "fi")

    rerender_video_thumbnail_frame(job_id, job, _thumbnail_path(job, thumbnail))
    db.commit()

    try:
        result = meta.upload_instagram_reel(
            video_url=media_url(job_id, "video"),
            cover_url=media_url(job_id, _thumbnail_kind(thumbnail)),
            caption=_caption(job, language, 2200),
        )
    except Exception as exc:
        job.instagram_status = f"failed: {exc}"
        db.commit()
        raise HTTPException(400, str(exc))

    job.instagram_media_id = result["media_id"]
    job.instagram_url = result.get("url")
    job.instagram_status = result.get("status") or "uploaded"
    db.commit()
    return {"status": "uploaded", **result}


@router.post("/jobs/{job_id}/facebook")
def post_to_facebook(job_id: str, data: dict, db: Session = Depends(get_db)):
    _ensure_public_base_url()
    job = _job_or_404(job_id, db)
    if job.facebook_video_id:
        raise HTTPException(409, "Already posted to Facebook. Reset the saved post first to post again.")
    language = data.get("language", "fi")
    thumbnail = data.get("thumbnail", "fi")
    thumbnail_path = _thumbnail_path(job, thumbnail)

    try:
        result = meta.upload_facebook_reel(
            video_url=media_url(job_id, "video"),
            description=_caption(job, language, 5000),
            thumbnail_path=thumbnail_path,
        )
    except Exception as exc:
        job.facebook_status = f"failed: {exc}"
        db.commit()
        raise HTTPException(400, str(exc))

    job.facebook_video_id = result["video_id"]
    job.facebook_url = result.get("url")
    if result.get("thumbnail_error"):
        job.facebook_status = f"uploaded; thumbnail failed: {result['thumbnail_error']}"
    else:
        job.facebook_status = "uploaded with thumbnail" if result.get("thumbnail_uploaded") else str(result.get("status") or "uploaded")
    db.commit()
    return {"status": "uploaded", **result}


@router.post("/jobs/{job_id}/facebook/thumbnail")
def set_facebook_thumbnail(job_id: str, data: dict, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.facebook_video_id:
        raise HTTPException(400, "This job has no Facebook video")

    thumbnail = data.get("thumbnail", "fi")
    thumbnail_path = _thumbnail_path(job, thumbnail)
    if not thumbnail_path:
        raise HTTPException(400, "Selected thumbnail is not available")

    try:
        success = meta.set_facebook_video_thumbnail(job.facebook_video_id, thumbnail_path)
    except Exception as exc:
        job.facebook_status = f"thumbnail failed: {exc}"
        db.commit()
        raise HTTPException(400, str(exc))

    job.facebook_status = "uploaded with thumbnail"
    db.commit()
    return {"status": "updated", "thumbnail_uploaded": success}


@router.post("/jobs/{job_id}/meta")
def post_to_meta(job_id: str, data: dict, db: Session = Depends(get_db)):
    job = _job_or_404(job_id, db)
    results = {}
    errors = {}

    if job.instagram_media_id:
        results["instagram"] = {
            "status": "already_posted",
            "media_id": job.instagram_media_id,
            "url": job.instagram_url,
        }
    else:
        try:
            results["instagram"] = post_to_instagram(job_id, data, db)
        except HTTPException as exc:
            errors["instagram"] = exc.detail

    if job.facebook_video_id:
        results["facebook"] = {
            "status": "already_posted",
            "video_id": job.facebook_video_id,
            "url": job.facebook_url,
        }
    else:
        try:
            results["facebook"] = post_to_facebook(job_id, data, db)
        except HTTPException as exc:
            errors["facebook"] = exc.detail

    return {"status": "done" if not errors else "partial", "results": results, "errors": errors}


@router.post("/jobs/{job_id}/tiktok")
def post_to_tiktok(job_id: str, data: dict, db: Session = Depends(get_db)):
    job = _job_or_404(job_id, db)
    if job.tiktok_publish_id:
        raise HTTPException(409, "Already uploaded to TikTok. Reset the saved upload first to upload again.")
    if not tiktok.is_configured():
        raise HTTPException(400, "TikTok app credentials are not configured")
    if settings.tiktok_post_mode != "draft":
        raise HTTPException(400, "Only TikTok draft upload mode is configured in ShortGen right now")

    try:
        result = tiktok.upload_video_draft(job.output_video_path)
    except Exception as exc:
        job.tiktok_status = f"failed: {exc}"
        db.commit()
        raise HTTPException(400, str(exc))

    job.tiktok_publish_id = result["publish_id"]
    job.tiktok_url = result.get("url")
    job.tiktok_status = result.get("status") or "draft_uploaded"
    db.commit()
    return {"status": "uploaded", **result}


@router.post("/jobs/{job_id}/tiktok/status")
def refresh_tiktok_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.tiktok_publish_id:
        raise HTTPException(400, "This job has no TikTok upload")

    try:
        result = tiktok.get_publish_status(job.tiktok_publish_id)
    except Exception as exc:
        raise HTTPException(400, str(exc))

    job.tiktok_status = result.get("status") or job.tiktok_status
    db.commit()
    return result


@router.post("/jobs/{job_id}/{platform}/reset")
def reset_social_post(job_id: str, platform: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if platform == "instagram":
        job.instagram_media_id = None
        job.instagram_url = None
        job.instagram_status = None
    elif platform == "facebook":
        job.facebook_video_id = None
        job.facebook_url = None
        job.facebook_status = None
    elif platform == "tiktok":
        job.tiktok_publish_id = None
        job.tiktok_url = None
        job.tiktok_status = None
    else:
        raise HTTPException(400, "Unknown platform")

    db.commit()
    return {"status": "reset"}
