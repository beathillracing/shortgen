from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job
from app.services.public_media import verify_media_token

router = APIRouter()
templates = Jinja2Templates(directory="/var/www/shortgen/app/templates")


@router.get("/public/app", response_class=HTMLResponse)
def public_app_page(request: Request):
    return templates.TemplateResponse("public_app.html", {"request": request})


@router.get("/public/privacy", response_class=HTMLResponse)
def public_privacy_page(request: Request):
    return templates.TemplateResponse("public_privacy.html", {"request": request})


@router.get("/public/terms", response_class=HTMLResponse)
def public_terms_page(request: Request):
    return templates.TemplateResponse("public_terms.html", {"request": request})


@router.get("/public/delete-account", response_class=HTMLResponse)
def public_delete_account_page(request: Request):
    return templates.TemplateResponse("public_delete.html", {"request": request})


@router.get("/public/beathill-studio-v10.apk")
def public_beathill_studio_apk():
    return FileResponse(
        "/var/www/shortgen/assets/public/beathill-studio-v10.apk",
        media_type="application/vnd.android.package-archive",
        filename="beathill-studio-v10.apk",
    )


@router.get("/public/shortgen-logo-1024.png")
def public_logo():
    return FileResponse(
        "/var/www/shortgen/assets/public/shortgen-logo-1024.png",
        media_type="image/png",
    )


@router.get("/public/shortgen-android.apk")
def public_android_app():
    return FileResponse(
        "/var/www/shortgen/assets/public/shortgen-android.apk",
        media_type="application/vnd.android.package-archive",
        filename="ShortGen.apk",
    )


@router.get("/public/shortgen-creator-android.apk")
def public_creator_android_app():
    return FileResponse(
        "/var/www/shortgen/assets/public/shortgen-creator-android.apk",
        media_type="application/vnd.android.package-archive",
        filename="ShortGen-Creator.apk",
    )


@router.get("/public/beathill-studio-v0.8.0-8.aab")
def public_beathill_studio_bundle():
    return FileResponse(
        "/var/www/shortgen/assets/public/beathill-studio-v0.8.0-8.aab",
        media_type="application/octet-stream",
        filename="beathill-studio-v0.8.0-8.aab",
    )


@router.get("/public/beathill-studio-v0.9.0-9.aab")
def public_beathill_studio_bundle_v9():
    return FileResponse(
        "/var/www/shortgen/assets/public/beathill-studio-v0.9.0-9.aab",
        media_type="application/octet-stream",
        filename="beathill-studio-v0.9.0-9.aab",
    )


@router.get("/public/beathill-studio-v0.10.0-10.aab")
def public_beathill_studio_bundle_v10():
    return FileResponse(
        "/var/www/shortgen/assets/public/beathill-studio-v0.10.0-10.aab",
        media_type="application/octet-stream",
        filename="beathill-studio-v0.10.0-10.aab",
    )


@router.get("/public/jobs/{job_id}/{kind}")
def public_job_media(job_id: str, kind: str, token: str, db: Session = Depends(get_db)):
    if not verify_media_token(job_id, kind, token):
        raise HTTPException(403, "Invalid media token")

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    media_type = "video/mp4"
    if kind == "video":
        path = job.output_video_path
    elif kind == "thumbnail-fi":
        path = job.thumbnail_path_fi
        media_type = "image/jpeg"
    elif kind == "thumbnail-en":
        path = job.thumbnail_path_en
        media_type = "image/jpeg"
    elif kind == "thumbnail":
        path = job.thumbnail_path
        media_type = "image/jpeg"
    else:
        raise HTTPException(404, "Unknown media kind")

    if not path or not Path(path).exists():
        raise HTTPException(404, "Media not ready")

    return FileResponse(path, media_type=media_type)
