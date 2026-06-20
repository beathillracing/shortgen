import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import settings

TOKEN_FILE = Path("/var/www/shortgen/tiktok_token.json")
STATE_FILE = Path("/var/www/shortgen/tiktok_oauth_state")
API_BASE = "https://open.tiktokapis.com/v2"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = ["user.info.basic", "video.upload"]


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def _load_token() -> dict:
    if not TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_configured() -> bool:
    return bool(settings.tiktok_client_key and settings.tiktok_client_secret)


def get_auth_url(state: str | None = None, persist_state: bool = True) -> str | None:
    if not is_configured():
        return None

    state = state or secrets.token_urlsafe(24)
    if persist_state:
        STATE_FILE.write_text(state, encoding="utf-8")
        os.chmod(STATE_FILE, 0o600)
    params = {
        "client_key": settings.tiktok_client_key,
        "redirect_uri": f"{settings.base_url.rstrip('/')}/api/tiktok/callback",
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def handle_callback(code: str, state: str | None):
    if not STATE_FILE.exists() or STATE_FILE.read_text(encoding="utf-8") != (state or ""):
        raise ValueError("Invalid TikTok OAuth state")

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{API_BASE}/oauth/token/",
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{settings.base_url.rstrip('/')}/api/tiktok/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    response.raise_for_status()
    token = response.json()
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    _save_json(TOKEN_FILE, token)
    STATE_FILE.unlink(missing_ok=True)


def exchange_mobile_code(code: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{API_BASE}/oauth/token/",
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{settings.base_url.rstrip('/')}/api/tiktok/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    response.raise_for_status()
    token = response.json()
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    return token


def _access_token(connection_data: dict | None = None) -> str:
    token = connection_data or _load_token()
    access_token = token.get("access_token")
    if not access_token:
        raise ValueError("TikTok is not authenticated")
    return access_token


def _authorized_scopes() -> set[str]:
    scope = _load_token().get("scope") or ""
    if isinstance(scope, list):
        return set(scope)
    return {item.strip() for item in scope.split(",") if item.strip()}


def get_user_info(connection_data: dict | None = None) -> dict:
    access_token = _access_token(connection_data)
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{API_BASE}/user/info/",
            params={"fields": "open_id,union_id,avatar_url,display_name"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error", {}).get("code") not in [None, "ok"]:
        raise ValueError(payload.get("error", {}).get("message") or payload["error"]["code"])
    return payload.get("data", {}).get("user", {})


def status() -> dict:
    token = _load_token()
    user = {}
    if token.get("access_token"):
        try:
            user = get_user_info()
        except Exception:
            user = {}
    scopes = _authorized_scopes()
    return {
        "configured": is_configured(),
        "authenticated": bool(token.get("access_token")),
        "open_id": token.get("open_id"),
        "scope": token.get("scope"),
        "post_mode": settings.tiktok_post_mode,
        "display_name": user.get("display_name"),
        "avatar_url": user.get("avatar_url"),
        "draft_upload_authorized": "video.upload" in scopes,
        "direct_post_authorized": "video.publish" in scopes,
    }


def disconnect():
    TOKEN_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)


def upload_video_draft(video_path: str, connection_data: dict | None = None) -> dict:
    path = Path(video_path)
    if not path.exists():
        raise ValueError("Video file is missing")

    file_size = path.stat().st_size
    access_token = _access_token(connection_data)
    init_body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        }
    }

    with httpx.Client(timeout=60) as client:
        init = client.post(
            f"{API_BASE}/post/publish/inbox/video/init/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=init_body,
        )
        init.raise_for_status()
        init_data = init.json()
        if init_data.get("error", {}).get("code") not in [None, "ok"]:
            raise ValueError(init_data.get("error", {}).get("message") or init_data["error"]["code"])

        data = init_data.get("data", {})
        upload_url = data["upload_url"]
        publish_id = data["publish_id"]

        with path.open("rb") as video_file:
            upload = client.put(
                upload_url,
                content=video_file,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(file_size),
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                },
            )
        upload.raise_for_status()

    return {
        "publish_id": publish_id,
        "status": "draft_uploaded",
        "url": None,
    }


def get_publish_status(publish_id: str) -> dict:
    access_token = _access_token()
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{API_BASE}/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error", {}).get("code") not in [None, "ok"]:
        raise ValueError(payload.get("error", {}).get("message") or payload["error"]["code"])
    return payload.get("data", {})
