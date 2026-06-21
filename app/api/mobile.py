import json
import os
import secrets
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.jobs import continue_job, retry_job, select_thumbnail
from app.api.social import queue_publish
from app.api.upload import create_and_queue_job
from app.config import settings
from app.database import get_db
from app.models import Job
from app.models import MobileAccess, MobileUsage, OAuthConnection, OAuthState
from app.services.progress import get_progress
from app.services.mobile_access import register_installation, resolve_access
from app.services.mobile_accounts import (
    consume_job_allowance,
    entitlement,
    link_google_identity,
    refresh_subscription_if_due,
    verify_subscription,
)
from app.services.mobile_oauth import (
    authorization_url,
    connection_statuses,
    disconnect as disconnect_oauth,
    select_facebook_page,
)
from app.database import SessionLocal
from redis import Redis

router = APIRouter()

_register_rate_redis = Redis.from_url(settings.redis_url)
REGISTER_RATE_LIMIT = 10  # registrations per IP per hour

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_FILES = 20


@router.post("/register")
def register_mobile_installation(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    rate_key = f"mobile_register_rl:{client_ip}"
    try:
        attempts = _register_rate_redis.incr(rate_key)
        if attempts == 1:
            _register_rate_redis.expire(rate_key, 3600)
    except Exception:
        attempts = 0  # fail open if Redis is unavailable
    if attempts > REGISTER_RATE_LIMIT:
        raise HTTPException(429, "Too many registration attempts. Try again later.")
    installation_id = str(data.get("installation_id") or "").strip()
    token = str(data.get("access_token") or "").strip()
    if not 16 <= len(installation_id) <= 64:
        raise HTTPException(400, "Invalid installation ID")
    if not token.startswith("bst_") or not 32 <= len(token) <= 96:
        raise HTTPException(400, "Invalid access token")
    try:
        access = register_installation(db, installation_id, token)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "status": "registered",
        "owner": access.owner,
        "publishing_enabled": bool(access.publishing_enabled),
    }


def _mobile_identity(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid mobile authorization")
    token = authorization[7:]
    if settings.mobile_api_token and secrets.compare_digest(token, settings.mobile_api_token):
        return {
            "role": "admin",
            "owner": None,
            "access_id": None,
            "publishing_enabled": True,
            "label": "Administrator",
        }
    if settings.mobile_creator_api_token and secrets.compare_digest(
        token,
        settings.mobile_creator_api_token,
    ):
        return {
            "role": "creator",
            "owner": "creator",
            "access_id": None,
            "publishing_enabled": False,
            "label": "Creator",
        }
    db = SessionLocal()
    try:
        identity = resolve_access(db, token)
        if identity:
            return identity
    finally:
        db.close()
    raise HTTPException(401, "Invalid mobile authorization")


def _sessions_dir() -> Path:
    path = settings.storage_path / "mobile_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_dir(session_id: str) -> Path:
    try:
        normalized = str(uuid.UUID(session_id))
    except ValueError as exc:
        raise HTTPException(404, "Upload session not found") from exc
    path = _sessions_dir() / normalized
    if not path.is_dir():
        raise HTTPException(404, "Upload session not found")
    return path


def _metadata_path(session_dir: Path) -> Path:
    return session_dir / "session.json"


def _load_metadata(session_dir: Path) -> dict:
    try:
        return json.loads(_metadata_path(session_dir).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Upload session metadata is invalid") from exc


def _write_metadata(session_dir: Path, metadata: dict):
    target = _metadata_path(session_dir)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(metadata, indent=2))
    os.replace(temp, target)


def _file_entry(metadata: dict, file_index: int) -> dict:
    files = metadata["files"]
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(404, "Upload file not found")
    return files[file_index]


def _authorize_session(metadata: dict, identity: dict):
    if metadata.get("mobile_owner") != identity["owner"]:
        raise HTTPException(404, "Upload session not found")


def _job_or_404(job_id: str, db: Session, identity: dict) -> Job:
    query = db.query(Job).filter(Job.id == job_id)
    if identity["owner"]:
        query = query.filter(Job.mobile_owner == identity["owner"])
    job = query.first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _job_payload(job: Job, include_detail: bool = False) -> dict:
    progress = get_progress(str(job.id))
    payload = {
        "id": str(job.id),
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "original_filename": job.original_filename,
        "current_step": job.current_step,
        "error_message": job.error_message,
        "progress": progress,
        "selected_thumbnail_index": int(job.selected_thumbnail_index or 1),
        "has_video": bool(job.output_video_path and Path(job.output_video_path).exists()),
        "has_thumbnail": bool(job.thumbnail_path and Path(job.thumbnail_path).exists()),
        "publish_status": job.publish_status or {"status": "idle"},
        "posted": {
            "youtube": bool(job.youtube_video_id),
            "instagram": bool(job.instagram_media_id),
            "facebook": bool(job.facebook_video_id),
            "tiktok": bool(job.tiktok_publish_id),
        },
    }
    if include_detail:
        payload.update(
            {
                "context": job.context_description or "",
                "title_fi": job.final_title or job.suggested_title_fi or "",
                "title_en": job.final_title or job.suggested_title_en or "",
                "description_fi": job.final_description or job.suggested_description_fi or "",
                "description_en": job.final_description or job.suggested_description_en or "",
                "thumbnail_text_fi": job.suggested_thumbnail_text_fi or "",
                "thumbnail_text_en": job.suggested_thumbnail_text_en or "",
                "final_title": job.final_title or "",
                "final_description": job.final_description or "",
                "hashtags": job.suggested_hashtags or [],
                "thumbnail_candidates": [
                    {
                        "index": candidate["index"],
                        "timestamp": candidate.get("timestamp"),
                        "url": f"/api/mobile/jobs/{job.id}/media/candidate/{candidate['index']}",
                    }
                    for candidate in (job.thumbnail_candidates or [])
                ],
                "media": {
                    "video": f"/api/mobile/jobs/{job.id}/media/video",
                    "thumbnail_fi": f"/api/mobile/jobs/{job.id}/media/thumbnail/fi",
                    "thumbnail_en": f"/api/mobile/jobs/{job.id}/media/thumbnail/en",
                    "thumbnail_clean": f"/api/mobile/jobs/{job.id}/media/thumbnail/clean",
                },
                "platform_urls": {
                    "youtube": job.youtube_url,
                    "instagram": job.instagram_url,
                    "facebook": job.facebook_url,
                    "tiktok": job.tiktok_url,
                },
            }
        )
    return payload


@router.get("/status")
def mobile_status(identity: dict = Depends(_mobile_identity)):
    db = SessionLocal()
    try:
        account = entitlement(db, identity["owner"]) if identity["owner"] else None
    finally:
        db.close()
    return {
        "status": "ok",
        "chunk_size": max(1, settings.mobile_upload_chunk_size_mb) * 1024 * 1024,
        "role": identity["role"],
        "publishing_enabled": (
            account["publishing_enabled"] if account else identity["publishing_enabled"]
        ),
        "label": identity["label"],
        "account": account,
    }


@router.post("/auth/google")
def mobile_google_auth(
    data: dict,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    credential = str(data.get("credential") or "")
    if not credential:
        raise HTTPException(400, "Google credential is required")
    if not identity.get("access_id"):
        raise HTTPException(400, "This legacy access code cannot be linked to Google")
    try:
        return link_google_identity(db, identity["access_id"], credential)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Google Sign-In failed: {exc}") from exc


@router.get("/account")
def mobile_account(
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    if not identity["owner"]:
        return {
            "account_id": "administrator",
            "plan": "admin",
            "publishing_enabled": True,
            "usage": {"jobs_limit": None, "jobs_remaining": None},
        }
    try:
        return refresh_subscription_if_due(db, identity["owner"])
    except Exception:
        return entitlement(db, identity["owner"])


def _require_mobile_publishing(db: Session, identity: dict):
    if not identity["owner"] or not identity.get("access_id"):
        raise HTTPException(400, "Platform connections require a Play app account")
    try:
        current = refresh_subscription_if_due(db, identity["owner"])
    except Exception:
        current = entitlement(db, identity["owner"])
    if not current["publishing_enabled"]:
        raise HTTPException(403, "Beathill Studio Pro is required for direct publishing")
    return current


@router.get("/connections")
def mobile_connections(
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    _require_mobile_publishing(db, identity)
    return {"connections": connection_statuses(db, identity["owner"])}


@router.post("/connections/{provider}/auth")
def mobile_connection_auth(
    provider: str,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    _require_mobile_publishing(db, identity)
    if provider not in {"youtube", "facebook", "instagram", "tiktok"}:
        raise HTTPException(404, "Unknown publishing platform")
    try:
        url = authorization_url(db, identity["owner"], provider)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if not url:
        raise HTTPException(503, f"{provider.title()} OAuth is not configured")
    return {"authorization_url": url}


@router.delete("/connections/{provider}")
def mobile_connection_disconnect(
    provider: str,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    _require_mobile_publishing(db, identity)
    if provider not in {"youtube", "facebook", "instagram", "tiktok"}:
        raise HTTPException(404, "Unknown publishing platform")
    disconnect_oauth(db, identity["owner"], provider)
    return {"status": "disconnected"}


@router.post("/connections/facebook/page")
def mobile_connection_facebook_page(
    data: dict,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    _require_mobile_publishing(db, identity)
    page_id = str(data.get("page_id") or "")
    if not page_id:
        raise HTTPException(400, "Facebook Page is required")
    try:
        select_facebook_page(db, identity["owner"], page_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"connections": connection_statuses(db, identity["owner"])}


@router.post("/fcm-token")
def register_fcm_token(
    data: dict,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    token = str(data.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "Token is required")
    if identity.get("access_id"):
        from app.services.push import register_token
        register_token(db, identity["access_id"], token)
    return {"status": "ok"}


@router.get("/prefs")
def get_mobile_prefs(
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    """Return this user's saved app settings (synced across their devices)."""
    access_id = identity.get("access_id")
    if not access_id:
        return {}
    row = db.query(MobileAccess).filter(MobileAccess.id == access_id).first()
    if not row or not row.preferences:
        return {}
    try:
        data = json.loads(row.preferences)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@router.put("/prefs")
def put_mobile_prefs(
    data: dict,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    """Persist this user's app settings to all of their linked devices."""
    access_id = identity.get("access_id")
    if not access_id:
        return {"status": "skipped"}
    clean = {
        str(k)[:64]: str(v)[:256]
        for k, v in list(data.items())[:80]
        if v is not None
    }
    payload = json.dumps(clean)
    owner = identity.get("owner")
    query = db.query(MobileAccess)
    if owner:
        query = query.filter(MobileAccess.account_id == owner)
    else:
        query = query.filter(MobileAccess.id == access_id)
    for row in query.all():
        row.preferences = payload
    db.commit()
    return {"status": "ok"}


@router.post("/billing/verify")
def mobile_verify_subscription(
    data: dict,
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    purchase_token = str(data.get("purchase_token") or "")
    if not purchase_token:
        raise HTTPException(400, "Purchase token is required")
    if not identity["owner"] or not identity.get("access_id"):
        raise HTTPException(400, "A Play app account is required")
    try:
        return verify_subscription(db, identity["owner"], purchase_token)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Subscription verification failed: {exc}") from exc


@router.delete("/account")
def delete_mobile_account(
    identity: dict = Depends(_mobile_identity),
    db: Session = Depends(get_db),
):
    account_id = identity["owner"]
    if not account_id or not identity.get("access_id"):
        raise HTTPException(400, "Administrator and legacy accounts cannot be deleted here")

    jobs = db.query(Job).filter(Job.mobile_owner == account_id).all()
    for job in jobs:
        paths = [
            job.upload_path,
            job.output_video_path,
            job.thumbnail_path,
            job.thumbnail_path_fi,
            job.thumbnail_path_en,
        ]
        if job.upload_paths:
            try:
                paths.extend(json.loads(job.upload_paths))
            except (TypeError, json.JSONDecodeError):
                pass
        for candidate in (job.thumbnail_candidates or []):
            candidate_path = candidate.get("path")
            if candidate_path:
                paths.append(candidate_path)
        for path in paths:
            if path:
                Path(path).unlink(missing_ok=True)
        db.delete(job)

    for session_dir in _sessions_dir().iterdir():
        if not session_dir.is_dir():
            continue
        try:
            metadata = json.loads((session_dir / "session.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("mobile_owner") == account_id:
            shutil.rmtree(session_dir, ignore_errors=True)

    access_rows = db.query(MobileAccess).filter(MobileAccess.account_id == account_id).all()
    access_ids = [row.id for row in access_rows]
    if access_ids:
        db.query(MobileUsage).filter(MobileUsage.mobile_access_id.in_(access_ids)).delete(
            synchronize_session=False
        )
        db.query(OAuthConnection).filter(
            OAuthConnection.mobile_access_id.in_(access_ids)
        ).delete(synchronize_session=False)
        db.query(OAuthState).filter(
            OAuthState.mobile_access_id.in_(access_ids)
        ).delete(synchronize_session=False)
    for row in access_rows:
        db.delete(row)
    db.commit()
    return {
        "status": "deleted",
        "subscription_note": (
            "Deleting app data does not cancel Google Play billing. "
            "Manage the subscription in Google Play."
        ),
    }


@router.get("/app-update")
def mobile_app_update(
    installed_version_code: int = 0,
    identity: dict = Depends(_mobile_identity),
):
    edition = "creator" if identity["role"] == "creator" else "full"
    manifest_path = settings.assets_path / "public" / f"shortgen-{edition}-version.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Update manifest not found")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Update manifest is invalid") from exc
    releases = manifest.get("releases") or []
    manifest["missed_releases"] = [
        release
        for release in releases
        if int(release.get("version_code", 0)) > installed_version_code
    ]
    manifest["release_notes"] = "\n\n".join(
        f"{release.get('version_name', '')}: {release.get('notes', '')}"
        for release in manifest["missed_releases"]
    )
    manifest["update_available"] = manifest["version_code"] > installed_version_code
    manifest["edition"] = edition
    return manifest


@router.get("/jobs")
def list_mobile_jobs(
    limit: int = 30,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    limit = max(1, min(limit, 100))
    query = db.query(Job)
    if identity["owner"]:
        query = query.filter(Job.mobile_owner == identity["owner"])
    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()
    return {"jobs": [_job_payload(job) for job in jobs]}


@router.get("/jobs/{job_id}")
def get_mobile_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    payload = _job_payload(_job_or_404(job_id, db, identity), include_detail=True)
    payload["publishing_enabled"] = (
        entitlement(db, identity["owner"])["publishing_enabled"]
        if identity["owner"] and identity.get("access_id")
        else identity["publishing_enabled"]
    )
    return payload


@router.patch("/jobs/{job_id}")
def update_mobile_job(
    job_id: str,
    data: dict,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    job = _job_or_404(job_id, db, identity)
    if "title" in data:
        job.final_title = str(data["title"]).strip()[:255] or None
    if "description" in data:
        job.final_description = str(data["description"]).strip() or None
    db.commit()
    return _job_payload(job, include_detail=True)


@router.delete("/jobs/{job_id}")
def delete_mobile_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    job = _job_or_404(job_id, db, identity)
    paths = [
        job.upload_path,
        job.output_video_path,
        job.thumbnail_path,
        job.thumbnail_path_fi,
        job.thumbnail_path_en,
    ]
    if job.upload_paths:
        try:
            paths.extend(json.loads(job.upload_paths))
        except (TypeError, json.JSONDecodeError):
            pass
    for candidate in (job.thumbnail_candidates or []):
        candidate_path = candidate.get("path")
        if candidate_path:
            paths.append(candidate_path)
    for path in paths:
        if path:
            Path(path).unlink(missing_ok=True)
    db.delete(job)
    db.commit()
    return {"status": "deleted"}


@router.post("/jobs/{job_id}/retry")
def retry_mobile_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    _job_or_404(job_id, db, identity)
    return retry_job(job_id, db)


@router.post("/jobs/{job_id}/continue")
def continue_mobile_job(
    job_id: str,
    data: dict,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    _job_or_404(job_id, db, identity)
    return continue_job(job_id, data, db)


@router.post("/jobs/{job_id}/thumbnail")
def select_mobile_thumbnail(
    job_id: str,
    data: dict,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    _job_or_404(job_id, db, identity)
    return select_thumbnail(job_id, data, db)


@router.post("/jobs/{job_id}/publish")
def publish_mobile_job(
    job_id: str,
    data: dict,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    if identity["owner"] and identity.get("access_id"):
        _require_mobile_publishing(db, identity)
        selected = set(data.get("platforms") or [])
        statuses = connection_statuses(db, identity["owner"])
        required = {
            "youtube": "youtube",
            "instagram": "instagram",
            "facebook": "facebook",
            "tiktok": "tiktok",
        }
        missing = sorted(
            {
                required[platform]
                for platform in selected
                if platform in required and not statuses[required[platform]]["connected"]
            }
        )
        if missing:
            raise HTTPException(
                400,
                "Connect these accounts before publishing: "
                + ", ".join(provider.title() for provider in missing),
            )
    elif not identity["publishing_enabled"]:
        raise HTTPException(403, "Publishing is disabled for this mobile account")
    _job_or_404(job_id, db, identity)
    return queue_publish(job_id, data, db)


@router.get("/jobs/{job_id}/media/video")
def get_mobile_video(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    job = _job_or_404(job_id, db, identity)
    if not job.output_video_path or not Path(job.output_video_path).exists():
        raise HTTPException(404, "Video not ready")
    path = Path(job.output_video_path)
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            path,
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes"},
        )

    try:
        unit, requested = range_header.split("=", 1)
        start_text, end_text = requested.split("-", 1)
        if unit != "bytes" or not start_text:
            raise ValueError
        file_size = path.stat().st_size
        start = int(start_text)
        end = min(int(end_text) if end_text else file_size - 1, file_size - 1)
        if start < 0 or start > end:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(
            416,
            "Invalid byte range",
            headers={"Content-Range": f"bytes */{path.stat().st_size}"},
        )

    def read_range():
        remaining = end - start + 1
        with path.open("rb") as video:
            video.seek(start)
            while remaining > 0:
                chunk = video.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        read_range(),
        status_code=206,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        },
    )


@router.get("/jobs/{job_id}/media/candidate/{index}")
def get_mobile_candidate(
    job_id: str,
    index: int,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    job = _job_or_404(job_id, db, identity)
    candidate = next(
        (item for item in (job.thumbnail_candidates or []) if item["index"] == index),
        None,
    )
    if not candidate or not Path(candidate["path"]).exists():
        raise HTTPException(404, "Thumbnail candidate not found")
    return FileResponse(candidate["path"], media_type="image/jpeg")


@router.get("/jobs/{job_id}/media/thumbnail/{variant}")
def get_mobile_thumbnail(
    job_id: str,
    variant: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    job = _job_or_404(job_id, db, identity)
    paths = {
        "fi": job.thumbnail_path_fi,
        "en": job.thumbnail_path_en,
        "clean": job.thumbnail_path,
    }
    path = paths.get(variant)
    if not path or not Path(path).exists():
        raise HTTPException(404, "Thumbnail not ready")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/uploads")
def create_upload_session(
    data: dict,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    files = data.get("files") or []
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(400, f"files must contain between 1 and {MAX_FILES} items")

    # Fail fast before the client uploads anything: reject over-quota free
    # accounts now instead of after the full transfer at /complete.
    if identity.get("access_id"):
        ent = entitlement(db, identity["owner"])
        remaining = ent["usage"]["jobs_remaining"]
        if remaining is not None and remaining <= 0:
            raise HTTPException(
                402,
                "Monthly free processing limit reached. "
                "Upgrade to Beathill Studio Pro for unlimited videos.",
            )

    normalized_files = []
    for index, item in enumerate(files):
        name = Path(str(item.get("name") or "")).name
        try:
            size = int(item.get("size"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Invalid size for file {index + 1}") from exc
        if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type for file {index + 1}")
        if size <= 0:
            raise HTTPException(400, f"Invalid size for file {index + 1}")
        normalized_files.append({"name": name, "size": size, "uploaded": 0})

    session_id = str(uuid.uuid4())
    session_dir = _sessions_dir() / session_id
    session_dir.mkdir(mode=0o700)
    metadata = {
        "id": session_id,
        "status": "uploading",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mobile_owner": identity["owner"],
        "files": normalized_files,
        "options": {
            "context": str(data.get("context") or ""),
            "minimal_cuts": "true" if data.get("minimal_cuts") else "false",
            "burn_captions": "true" if data.get("burn_captions", True) else "false",
            "youtube_autopost": "true" if data.get("youtube_autopost") else "false",
            "precaptioned": "true" if data.get("precaptioned") else "false",
            "remove_outro_seconds": str(data.get("remove_outro_seconds", "3")),
            "caption_highlight_color": str(data.get("caption_highlight_color") or "").strip() or None,
            "caption_border": "false" if data.get("caption_border") is False else "true",
            "caption_border_color": str(data.get("caption_border_color") or "").strip() or None,
            "orientation": str(data.get("orientation") or "auto").strip() or "auto",
            "caption_position": str(data.get("caption_position") or "bottom").strip() or "bottom",
        },
    }
    _write_metadata(session_dir, metadata)
    return {
        "upload_id": session_id,
        "chunk_size": max(1, settings.mobile_upload_chunk_size_mb) * 1024 * 1024,
        "files": normalized_files,
    }


@router.get("/uploads/{session_id}")
def get_upload_session(
    session_id: str,
    identity: dict = Depends(_mobile_identity),
):
    metadata = _load_metadata(_session_dir(session_id))
    _authorize_session(metadata, identity)
    return metadata


@router.put("/uploads/{session_id}/files/{file_index}")
async def upload_chunk(
    session_id: str,
    file_index: int,
    request: Request,
    upload_offset: int = Header(..., alias="Upload-Offset"),
    identity: dict = Depends(_mobile_identity),
):
    session_dir = _session_dir(session_id)
    metadata = _load_metadata(session_dir)
    _authorize_session(metadata, identity)
    if metadata["status"] != "uploading":
        raise HTTPException(409, "Upload session is not accepting chunks")

    entry = _file_entry(metadata, file_index)
    part_path = session_dir / f"{file_index}.part"
    current_size = part_path.stat().st_size if part_path.exists() else 0
    if upload_offset != current_size or upload_offset != entry["uploaded"]:
        raise HTTPException(
            409,
            detail={"message": "Upload offset mismatch", "expected_offset": current_size},
        )

    remaining = entry["size"] - current_size
    received = 0
    with part_path.open("ab") as output:
        async for chunk in request.stream():
            if not chunk:
                continue
            if received + len(chunk) > remaining:
                output.truncate(current_size)
                raise HTTPException(413, "Chunk exceeds declared file size")
            output.write(chunk)
            received += len(chunk)
        output.flush()
        os.fsync(output.fileno())

    entry["uploaded"] = current_size + received
    _write_metadata(session_dir, metadata)
    return {
        "file_index": file_index,
        "uploaded": entry["uploaded"],
        "size": entry["size"],
        "complete": entry["uploaded"] == entry["size"],
    }


@router.post("/uploads/{session_id}/complete")
def complete_upload_session(
    session_id: str,
    db: Session = Depends(get_db),
    identity: dict = Depends(_mobile_identity),
):
    session_dir = _session_dir(session_id)
    metadata = _load_metadata(session_dir)
    _authorize_session(metadata, identity)
    if metadata["status"] == "completed":
        return {"job_id": metadata["job_id"], "status": "pending"}
    if metadata["status"] != "uploading":
        raise HTTPException(409, "Upload session cannot be completed")

    for index, entry in enumerate(metadata["files"]):
        part_path = session_dir / f"{index}.part"
        actual_size = part_path.stat().st_size if part_path.exists() else 0
        if actual_size != entry["size"]:
            raise HTTPException(
                409,
                detail={
                    "message": f"File {index + 1} is incomplete",
                    "uploaded": actual_size,
                    "size": entry["size"],
                },
            )

    upload_paths = []
    try:
        if identity["owner"]:
            try:
                consume_job_allowance(db, identity["owner"])
            except ValueError as exc:
                raise HTTPException(402, str(exc)) from exc
        for index, entry in enumerate(metadata["files"]):
            extension = Path(entry["name"]).suffix.lower()
            destination = settings.storage_path / "uploads" / f"{uuid.uuid4()}{extension}"
            shutil.move(str(session_dir / f"{index}.part"), destination)
            upload_paths.append(str(destination))

        job = create_and_queue_job(
            db,
            upload_paths,
            [entry["name"] for entry in metadata["files"]],
            mobile_owner=metadata.get("mobile_owner"),
            **metadata["options"],
        )
    except Exception:
        for path in upload_paths:
            Path(path).unlink(missing_ok=True)
        raise

    metadata["status"] = "completed"
    metadata["job_id"] = str(job.id)
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_metadata(session_dir, metadata)
    return {"job_id": str(job.id), "status": "pending"}


@router.delete("/uploads/{session_id}")
def cancel_upload_session(
    session_id: str,
    identity: dict = Depends(_mobile_identity),
):
    session_dir = _session_dir(session_id)
    metadata = _load_metadata(session_dir)
    _authorize_session(metadata, identity)
    if metadata["status"] == "completed":
        raise HTTPException(409, "Completed upload sessions cannot be deleted")
    shutil.rmtree(session_dir)
    return {"status": "deleted"}
