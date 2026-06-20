import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import settings

TOKEN_FILE = Path("/var/www/shortgen/meta_token.json")
STATE_FILE = Path("/var/www/shortgen/meta_oauth_state")
SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
]


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}"


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


def _graph_get(path: str, token: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    params["access_token"] = token
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{_graph_base()}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _graph_post(path: str, token: str, data: dict | None = None) -> dict:
    payload = dict(data or {})
    payload["access_token"] = token
    with httpx.Client(timeout=60) as client:
        response = client.post(f"{_graph_base()}{path}", data=payload)
    response.raise_for_status()
    return response.json()


def is_configured() -> bool:
    return bool(settings.meta_app_id and settings.meta_app_secret)


def get_auth_url(state: str | None = None, persist_state: bool = True) -> str | None:
    if not is_configured():
        return None

    state = state or secrets.token_urlsafe(24)
    if persist_state:
        STATE_FILE.write_text(state, encoding="utf-8")
        os.chmod(STATE_FILE, 0o600)

    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": f"{settings.base_url.rstrip('/')}/api/meta/callback",
        "state": state,
        "response_type": "code",
    }
    if settings.meta_configuration_id:
        params["config_id"] = settings.meta_configuration_id
    else:
        params["scope"] = ",".join(SCOPES)
    return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(params)}"


def _exchange_code(code: str) -> dict:
    params = {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "redirect_uri": f"{settings.base_url.rstrip('/')}/api/meta/callback",
        "code": code,
    }
    with httpx.Client(timeout=30) as client:
        short = client.get(f"{_graph_base()}/oauth/access_token", params=params)
        short.raise_for_status()
        short_token = short.json()["access_token"]

        long = client.get(
            f"{_graph_base()}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )
        long.raise_for_status()
        return long.json()


def handle_callback(code: str, state: str | None):
    if not STATE_FILE.exists() or STATE_FILE.read_text(encoding="utf-8") != (state or ""):
        raise ValueError("Invalid Meta OAuth state")

    token_data = _exchange_code(code)
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in")
    profile = _graph_get("/me", access_token, {"fields": "id,name"})
    pages = list_pages(access_token)

    selected_page = None
    if settings.meta_page_id:
        selected_page = next((p for p in pages if p["id"] == settings.meta_page_id), None)
    if not selected_page:
        selected_page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not selected_page and pages:
        selected_page = pages[0]

    data = {
        "access_token": access_token,
        "user_id": profile.get("id"),
        "user_name": profile.get("name"),
        "expires_at": int(time.time()) + int(expires_in) if expires_in else None,
        "pages": pages,
    }
    if selected_page:
        data.update(_selected_page_payload(selected_page))

    _save_json(TOKEN_FILE, data)
    STATE_FILE.unlink(missing_ok=True)


def exchange_mobile_code(code: str) -> dict:
    token_data = _exchange_code(code)
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in")
    profile = _graph_get("/me", access_token, {"fields": "id,name"})
    pages = list_pages(access_token)
    selected_page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not selected_page and pages:
        selected_page = pages[0]
    data = {
        "access_token": access_token,
        "user_id": profile.get("id"),
        "user_name": profile.get("name"),
        "expires_at": int(time.time()) + int(expires_in) if expires_in else None,
        "pages": pages,
    }
    if selected_page:
        data.update(_selected_page_payload(selected_page))
    return data


def list_pages(access_token: str | None = None) -> list[dict]:
    token = access_token or _load_token().get("access_token")
    if not token:
        return []
    response = _graph_get(
        "/me/accounts",
        token,
        {
            "fields": (
                "id,name,access_token,tasks,"
                "instagram_business_account{id,username,name}"
            ),
            "limit": 100,
        },
    )
    return response.get("data", [])


def _selected_page_payload(page: dict) -> dict:
    ig = page.get("instagram_business_account") or {}
    return {
        "selected_page_id": page.get("id"),
        "selected_page_name": page.get("name"),
        "page_access_token": page.get("access_token"),
        "instagram_user_id": ig.get("id"),
        "instagram_username": ig.get("username") or ig.get("name"),
    }


def select_page(page_id: str) -> dict:
    data = _load_token()
    if not data.get("access_token"):
        raise ValueError("Meta is not authenticated")

    pages = list_pages(data["access_token"])
    page = next((p for p in pages if p["id"] == page_id), None)
    if not page:
        raise ValueError("Page not found for this Meta login")

    data["pages"] = pages
    data.update(_selected_page_payload(page))
    _save_json(TOKEN_FILE, data)
    return status()


def status() -> dict:
    data = _load_token()
    return {
        "configured": is_configured(),
        "configuration_id_set": bool(settings.meta_configuration_id),
        "authenticated": bool(data.get("access_token")),
        "user_name": data.get("user_name"),
        "selected_page_id": data.get("selected_page_id"),
        "selected_page_name": data.get("selected_page_name"),
        "instagram_user_id": data.get("instagram_user_id"),
        "instagram_username": data.get("instagram_username"),
        "pages": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "instagram_username": (p.get("instagram_business_account") or {}).get("username"),
                "selected": p.get("id") == data.get("selected_page_id"),
            }
            for p in data.get("pages", [])
        ],
    }


def disconnect():
    TOKEN_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)


def _selected_tokens(connection_data: dict | None = None) -> tuple[str, str, str]:
    data = connection_data or _load_token()
    page_id = data.get("selected_page_id")
    page_token = data.get("page_access_token")
    ig_user_id = data.get("instagram_user_id")
    if not page_id or not page_token:
        raise ValueError("Meta Page is not selected")
    return page_id, page_token, ig_user_id


def upload_instagram_reel(
    video_url: str,
    caption: str,
    cover_url: str | None = None,
    connection_data: dict | None = None,
) -> dict:
    _, page_token, ig_user_id = _selected_tokens(connection_data)
    if not ig_user_id:
        raise ValueError("Selected Facebook Page has no linked Instagram professional account")

    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
    }
    if cover_url:
        payload["cover_url"] = cover_url

    container = _graph_post(f"/{ig_user_id}/media", page_token, payload)
    creation_id = container["id"]

    last_status = None
    for _ in range(24):
        details = _graph_get(f"/{creation_id}", page_token, {"fields": "status_code"})
        last_status = details.get("status_code")
        if last_status in ["FINISHED", "PUBLISHED"]:
            break
        if last_status == "ERROR":
            raise ValueError("Instagram finished processing with ERROR status")
        time.sleep(5)

    published = _graph_post(f"/{ig_user_id}/media_publish", page_token, {"creation_id": creation_id})
    media_id = published["id"]
    permalink = _graph_get(f"/{media_id}", page_token, {"fields": "permalink"}).get("permalink")
    return {
        "media_id": media_id,
        "url": permalink,
        "status": last_status or "published",
    }


def set_facebook_video_thumbnail(
    video_id: str,
    thumbnail_path: str,
    connection_data: dict | None = None,
) -> bool:
    _, page_token, _ = _selected_tokens(connection_data)
    path = Path(thumbnail_path)
    if not path.exists():
        raise ValueError("Facebook thumbnail file is missing")

    with path.open("rb") as thumbnail_file:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{_graph_base()}/{video_id}/thumbnails",
                data={
                    "access_token": page_token,
                    "is_preferred": "true",
                },
                files={
                    "source": ("thumbnail.jpg", thumbnail_file, "image/jpeg"),
                },
            )
    response.raise_for_status()
    return bool(response.json().get("success"))


def upload_facebook_reel(
    video_url: str,
    description: str,
    thumbnail_path: str | None = None,
    connection_data: dict | None = None,
) -> dict:
    page_id, page_token, _ = _selected_tokens(connection_data)
    started = _graph_post(f"/{page_id}/video_reels", page_token, {"upload_phase": "start"})
    video_id = started["video_id"]
    upload_url = started["upload_url"]

    with httpx.Client(timeout=60) as client:
        uploaded = client.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {page_token}",
                "file_url": video_url,
            },
        )
    uploaded.raise_for_status()

    finished = _graph_post(
        f"/{page_id}/video_reels",
        page_token,
        {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description[:5000],
        },
    )
    thumbnail_uploaded = False
    thumbnail_error = None
    if thumbnail_path:
        try:
            thumbnail_uploaded = set_facebook_video_thumbnail(
                video_id,
                thumbnail_path,
                connection_data,
            )
        except Exception as exc:
            thumbnail_error = str(exc)

    return {
        "video_id": video_id,
        "url": f"https://www.facebook.com/{page_id}/videos/{video_id}",
        "status": finished.get("success", "published"),
        "thumbnail_uploaded": thumbnail_uploaded,
        "thumbnail_error": thumbnail_error,
    }
