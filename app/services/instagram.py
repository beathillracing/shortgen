import time
from urllib.parse import urlencode

import httpx

from app.config import settings

SCOPES = ["instagram_business_basic", "instagram_business_content_publish"]
AUTH_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"


def _graph_base() -> str:
    return f"https://graph.instagram.com/{settings.meta_graph_version}"


def is_configured() -> bool:
    return bool(settings.instagram_app_id and settings.instagram_app_secret)


def get_auth_url(state: str) -> str | None:
    if not is_configured():
        return None
    return f"{AUTH_URL}?{urlencode({
        'enable_fb_login': '0',
        'force_reauth': 'true',
        'client_id': settings.instagram_app_id,
        'redirect_uri': f'{settings.base_url.rstrip("/")}/api/instagram/callback',
        'response_type': 'code',
        'scope': ','.join(SCOPES),
        'state': state,
    })}"


def exchange_code(code: str) -> dict:
    redirect_uri = f"{settings.base_url.rstrip('/')}/api/instagram/callback"
    with httpx.Client(timeout=30) as client:
        short_response = client.post(
            TOKEN_URL,
            data={
                "client_id": settings.instagram_app_id,
                "client_secret": settings.instagram_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        short_response.raise_for_status()
        short = short_response.json()
        long_response = client.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.instagram_app_secret,
                "access_token": short["access_token"],
            },
        )
        long_response.raise_for_status()
        token = long_response.json()
    token["user_id"] = short.get("user_id")
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    return token


def refresh_token(connection_data: dict) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": connection_data["access_token"],
            },
        )
    response.raise_for_status()
    refreshed = response.json()
    data = dict(connection_data)
    data.update(refreshed)
    data["expires_at"] = int(time.time()) + int(refreshed.get("expires_in", 0))
    return data


def get_profile(connection_data: dict) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{_graph_base()}/me",
            params={
                "fields": "user_id,username,name,account_type",
                "access_token": connection_data["access_token"],
            },
        )
    response.raise_for_status()
    return response.json()


def _graph_get(path: str, token: str, params: dict | None = None) -> dict:
    query = dict(params or {})
    query["access_token"] = token
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{_graph_base()}{path}", params=query)
    response.raise_for_status()
    return response.json()


def _graph_post(path: str, token: str, data: dict) -> dict:
    payload = dict(data)
    payload["access_token"] = token
    with httpx.Client(timeout=60) as client:
        response = client.post(f"{_graph_base()}{path}", data=payload)
    response.raise_for_status()
    return response.json()


def upload_reel(
    video_url: str,
    caption: str,
    connection_data: dict,
    cover_url: str | None = None,
) -> dict:
    token = connection_data["access_token"]
    user_id = connection_data.get("user_id")
    if not user_id:
        raise ValueError("Instagram account ID is missing")
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
    }
    if cover_url:
        payload["cover_url"] = cover_url
    container = _graph_post(f"/{user_id}/media", token, payload)
    creation_id = container["id"]
    last_status = None
    for _ in range(24):
        details = _graph_get(f"/{creation_id}", token, {"fields": "status_code"})
        last_status = details.get("status_code")
        if last_status in {"FINISHED", "PUBLISHED"}:
            break
        if last_status == "ERROR":
            raise ValueError("Instagram finished processing with ERROR status")
        time.sleep(5)
    published = _graph_post(
        f"/{user_id}/media_publish",
        token,
        {"creation_id": creation_id},
    )
    media_id = published["id"]
    permalink = _graph_get(f"/{media_id}", token, {"fields": "permalink"}).get(
        "permalink"
    )
    return {
        "media_id": media_id,
        "url": permalink,
        "status": last_status or "published",
    }
