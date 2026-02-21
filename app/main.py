import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.database import engine, Base, get_db
from app.models import Job
from app.api import upload, jobs, youtube
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

app = FastAPI(title="ShortGen", description="Short-form video automation")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require basic auth for all routes except YouTube callback."""
    # Skip auth if no password configured
    if not settings.admin_password:
        return await call_next(request)

    # Allow YouTube callback without auth (OAuth redirect)
    if request.url.path == "/api/youtube/callback":
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

    return templates.TemplateResponse(
        "job.html",
        {"request": request, "job": job.to_dict()}
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
