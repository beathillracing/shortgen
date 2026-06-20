import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text

from app.database import engine, Base, get_db
from app.models import Job
from app.api import upload, jobs, youtube, billing, social, public, mobile, mobile_admin
from app.config import settings

security = HTTPBasic()


def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """Check basic auth credentials."""
    if not settings.admin_password:
        return True  # Auth disabled if no password set

    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.admin_password.encode("utf8")
    )
    if not correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# Create tables
Base.metadata.create_all(bind=engine)


def ensure_job_columns():
    """Add nullable job columns when models evolve without a migration run."""
    columns = {
        "instagram_autopost": "VARCHAR(10) DEFAULT 'false'",
        "instagram_media_id": "VARCHAR(100)",
        "instagram_url": "VARCHAR(300)",
        "instagram_status": "TEXT",
        "facebook_autopost": "VARCHAR(10) DEFAULT 'false'",
        "facebook_video_id": "VARCHAR(100)",
        "facebook_url": "VARCHAR(300)",
        "facebook_status": "TEXT",
        "tiktok_autopost": "VARCHAR(10) DEFAULT 'false'",
        "tiktok_publish_id": "VARCHAR(100)",
        "tiktok_url": "VARCHAR(300)",
        "tiktok_status": "TEXT",
        "youtube_content_type": "VARCHAR(20)",
        "youtube_thumbnail_status": "VARCHAR(50)",
        "youtube_thumbnail_error": "TEXT",
        "publish_queue_id": "VARCHAR(100)",
        "publish_status": "JSONB",
        "mobile_owner": "VARCHAR(50)",
        "suggested_thumbnail_text_fi": "VARCHAR(255)",
        "suggested_thumbnail_text_en": "VARCHAR(255)",
    }
    with engine.begin() as conn:
        for name, ddl in columns.items():
            conn.execute(text(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {name} {ddl}"))
        conn.execute(text("ALTER TABLE jobs ALTER COLUMN current_step TYPE VARCHAR(200)"))


ensure_job_columns()


def ensure_mobile_access_columns():
    with engine.begin() as conn:
        columns = {
            "installation_id": "VARCHAR(64)",
            "account_id": "VARCHAR(50)",
            "google_subject": "VARCHAR(255)",
            "email": "VARCHAR(255)",
            "display_name": "VARCHAR(255)",
            "admin_unlimited": "BOOLEAN DEFAULT FALSE NOT NULL",
            "subscription_status": "VARCHAR(30) DEFAULT 'free' NOT NULL",
            "subscription_product_id": "VARCHAR(100)",
            "subscription_purchase_token_hash": "VARCHAR(64)",
            "subscription_purchase_token_encrypted": "TEXT",
            "subscription_checked_at": "TIMESTAMP",
            "subscription_expires_at": "TIMESTAMP",
            "subscription_grace_until": "TIMESTAMP",
            "monthly_job_limit": "INTEGER",
            "deleted_at": "TIMESTAMP",
        }
        for name, ddl in columns.items():
            conn.execute(text(f"ALTER TABLE mobile_access ADD COLUMN IF NOT EXISTS {name} {ddl}"))
        conn.execute(text("UPDATE mobile_access SET account_id = owner WHERE account_id IS NULL"))
        conn.execute(
            text(
                "UPDATE mobile_access SET admin_unlimited = TRUE, subscription_status = 'free' "
                "WHERE subscription_status = 'admin_unlimited'"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_mobile_access_installation_id "
                "ON mobile_access (installation_id)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_mobile_access_google_subject "
                "ON mobile_access (google_subject) WHERE google_subject IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_mobile_access_purchase_token "
                "ON mobile_access (subscription_purchase_token_hash) "
                "WHERE subscription_purchase_token_hash IS NOT NULL"
            )
        )


ensure_mobile_access_columns()

app = FastAPI(title="ShortGen", description="Short-form video automation")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require basic auth for all routes except YouTube callback."""
    if request.url.path.startswith("/api/mobile/"):
        return await call_next(request)

    # Skip auth if no password configured
    if not settings.admin_password:
        return await call_next(request)

    # Allow OAuth callbacks and signed public media fetches without admin auth.
    if request.url.path in [
        "/api/youtube/callback",
        "/api/meta/callback",
        "/api/instagram/callback",
        "/api/instagram/deauthorize",
        "/api/instagram/data-deletion",
        "/api/tiktok/callback",
    ]:
        return await call_next(request)
    if request.url.path.startswith("/api/instagram/data-deletion/"):
        return await call_next(request)
    if request.url.path.startswith("/public/"):
        return await call_next(request)

    # Check for basic auth header
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if secrets.compare_digest(password, settings.admin_password):
                return await call_next(request)
        except Exception:
            pass

    # Return 401 if no valid auth
    return Response(
        content="Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="ShortGen"'},
    )


# Mount static files
app.mount("/static", StaticFiles(directory=str(settings.storage_path)), name="static")

# Templates
templates = Jinja2Templates(directory="/var/www/shortgen/app/templates")

# Include API routers
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(youtube.router, prefix="/api", tags=["youtube"])
app.include_router(billing.router, prefix="/api", tags=["billing"])
app.include_router(social.router, prefix="/api", tags=["social"])
app.include_router(mobile.router, prefix="/api/mobile", tags=["mobile"])
app.include_router(mobile_admin.router, prefix="/api/admin", tags=["mobile-admin"])
app.include_router(public.router, tags=["public"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Upload page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    """Job detail/review page."""
    db = next(get_db())
    job = db.query(Job).filter(Job.id == job_id).first()
    db.close()

    if not job:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Job not found"}
        )

    import time
    return templates.TemplateResponse(
        "job.html",
        {"request": request, "job": job, "now": int(time.time())}
    )


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request):
    """List all jobs."""
    db = next(get_db())
    jobs_list = db.query(Job).order_by(Job.created_at.desc()).limit(50).all()
    db.close()

    return templates.TemplateResponse(
        "jobs.html",
        {"request": request, "jobs": [j.to_dict() for j in jobs_list]}
    )


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    return templates.TemplateResponse("billing.html", {"request": request})


@app.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request):
    return templates.TemplateResponse(
        "mobile.html",
        {
            "request": request,
            "mobile_api_token": settings.mobile_api_token,
            "mobile_creator_api_token": settings.mobile_creator_api_token,
        },
    )
