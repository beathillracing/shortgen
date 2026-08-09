from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import youtube as yt_service
from app.services import mobile_oauth
from app.config import settings

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


@router.get("/youtube/status")
def youtube_status():
    """Check if YouTube is authenticated."""
    return {
        "authenticated": yt_service.is_authenticated(),
        "credentials_configured": yt_service.Path(yt_service.CREDENTIALS_FILE).exists()
    }


@router.get("/youtube/auth")
def youtube_auth():
    """Start YouTube OAuth flow."""
    auth_url = yt_service.get_auth_url()
    if not auth_url:
        raise HTTPException(400, "YouTube client secret not configured. Upload youtube_client_secret.json first.")
    return RedirectResponse(auth_url)


@router.get("/youtube/callback")
def youtube_callback(request: Request, db: Session = Depends(get_db)):
    """Handle OAuth callback from Google."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if code and state:
        try:
            if mobile_oauth.handle_youtube_callback(db, code, state):
                return _mobile_oauth_complete("YouTube")
        except Exception as exc:
            raise HTTPException(400, f"OAuth failed: {exc}") from exc

    # Get the full URL for token exchange
    authorization_response = str(request.url)

    try:
        yt_service.handle_oauth_callback(authorization_response)
        # Redirect back to home with success message
        return RedirectResponse("/?youtube=connected")
    except Exception as e:
        raise HTTPException(400, f"OAuth failed: {str(e)}")


@router.post("/youtube/disconnect")
def youtube_disconnect():
    """Disconnect YouTube (remove token)."""
    token_path = yt_service.Path(yt_service.TOKEN_FILE)
    if token_path.exists():
        token_path.unlink()
    return {"status": "disconnected"}
