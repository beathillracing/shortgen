from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import youtube as yt_service
from app.config import settings

router = APIRouter()


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
def youtube_callback(request: Request):
    """Handle OAuth callback from Google."""
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
