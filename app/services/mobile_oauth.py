import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MobileAccess, OAuthConnection, OAuthState
from app.services import instagram, meta, tiktok, youtube
from app.services.secure_data import decrypt_json, encrypt_json


def canonical_access(db: Session, account_id: str) -> MobileAccess:
    rows = db.query(MobileAccess).filter(MobileAccess.account_id == account_id).all()
    if not rows:
        raise ValueError("Account not found")
    return next((row for row in rows if row.google_subject), rows[0])


def connection(db: Session, account_id: str, provider: str) -> OAuthConnection | None:
    account = canonical_access(db, account_id)
    item = (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.mobile_access_id == account.id,
            OAuthConnection.provider == provider,
        )
        .first()
    )
    if not item and provider == "facebook":
        item = (
            db.query(OAuthConnection)
            .filter(
                OAuthConnection.mobile_access_id == account.id,
                OAuthConnection.provider == "meta",
            )
            .first()
        )
        if item:
            item.provider = "facebook"
            db.commit()
    return item


def connection_data(db: Session, account_id: str, provider: str) -> dict:
    item = connection(db, account_id, provider)
    if not item:
        raise ValueError(f"{provider.title()} is not connected")
    return decrypt_json(item.encrypted_credentials)


def fresh_connection_data(db: Session, account_id: str, provider: str) -> dict:
    item = connection(db, account_id, provider)
    if not item:
        raise ValueError(f"{provider.title()} is not connected")
    data = decrypt_json(item.encrypted_credentials)
    now = int(time.time())
    changed = False

    if provider == "youtube":
        credentials = Credentials.from_authorized_user_info(data, youtube.SCOPES)
        if credentials.expired:
            if not credentials.refresh_token:
                raise ValueError("YouTube must be reconnected")
            credentials.refresh(GoogleRequest())
            data = json.loads(credentials.to_json())
            changed = True
    elif provider == "instagram":
        expires_at = int(data.get("expires_at") or 0)
        if expires_at and expires_at <= now:
            raise ValueError("Instagram must be reconnected")
        if expires_at <= now + 7 * 86400:
            data = instagram.refresh_token(data)
            changed = True
    elif provider == "tiktok":
        refresh_expires_at = int(data.get("refresh_expires_at") or 0)
        if refresh_expires_at and refresh_expires_at <= now:
            raise ValueError("TikTok must be reconnected")
        if int(data.get("expires_at") or 0) <= now + 3600:
            data = tiktok.refresh_mobile_token(data)
            changed = True
    elif provider == "facebook":
        expires_at = int(data.get("expires_at") or 0)
        if expires_at and expires_at <= now:
            raise ValueError("Facebook must be reconnected")

    if changed:
        item.encrypted_credentials = encrypt_json(data)
        db.commit()
    return data


def connection_statuses(db: Session, account_id: str) -> dict:
    result = {}
    for provider in ("youtube", "facebook", "instagram", "tiktok"):
        item = connection(db, account_id, provider)
        metadata = dict(item.metadata_json or {}) if item else {}
        if item and provider == "facebook":
            data = decrypt_json(item.encrypted_credentials)
            metadata["selected_page_id"] = data.get("selected_page_id")
            metadata["pages"] = [
                {
                    "id": page.get("id"),
                    "name": page.get("name"),
                }
                for page in data.get("pages", [])
            ]
        if item:
            data = decrypt_json(item.encrypted_credentials)
            expires_at = int(data.get("expires_at") or 0)
            refresh_expires_at = int(data.get("refresh_expires_at") or 0)
            now = int(time.time())
            metadata["expires_at"] = expires_at or None
            needs_reconnect = bool(
                provider in {"facebook", "instagram"}
                and expires_at
                and expires_at <= now
            )
            if provider == "tiktok":
                needs_reconnect = bool(
                    refresh_expires_at and refresh_expires_at <= now
                )
            if provider == "youtube":
                credentials = Credentials.from_authorized_user_info(
                    data,
                    youtube.SCOPES,
                )
                needs_reconnect = credentials.expired and not credentials.refresh_token
            metadata["needs_reconnect"] = needs_reconnect
        result[provider] = {
            "connected": bool(item),
            "label": item.account_label if item else None,
            "metadata": metadata,
        }
    return result


def _new_state(db: Session, account_id: str, provider: str) -> str:
    account = canonical_access(db, account_id)
    raw = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            state_hash=hashlib.sha256(raw.encode()).hexdigest(),
            mobile_access_id=account.id,
            provider=provider,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
    )
    db.commit()
    return raw


def _state_record(db: Session, raw: str, provider: str) -> tuple[OAuthState, MobileAccess] | None:
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    state = (
        db.query(OAuthState)
        .filter(
            OAuthState.state_hash == hashed,
            OAuthState.provider == provider,
            OAuthState.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not state:
        return None
    account = db.query(MobileAccess).filter(MobileAccess.id == state.mobile_access_id).first()
    if not account:
        db.delete(state)
        db.commit()
        return None
    return state, account


def _finish_state(db: Session, state: OAuthState):
    db.delete(state)
    db.commit()


def authorization_url(db: Session, account_id: str, provider: str) -> str:
    state = _new_state(db, account_id, provider)
    if provider == "youtube":
        flow = Flow.from_client_secrets_file(
            youtube.CREDENTIALS_FILE,
            scopes=youtube.SCOPES,
            state=state,
        )
        flow.redirect_uri = f"{settings.base_url}/api/youtube/callback"
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return url
    if provider == "facebook":
        return meta.get_auth_url(state=state, persist_state=False)
    if provider == "instagram":
        return instagram.get_auth_url(state)
    if provider == "tiktok":
        return tiktok.get_auth_url(state=state, persist_state=False)
    raise ValueError("Unknown platform")


def _save(
    db: Session,
    account: MobileAccess,
    provider: str,
    credentials: dict,
    label: str | None,
    metadata: dict,
):
    item = (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.mobile_access_id == account.id,
            OAuthConnection.provider == provider,
        )
        .first()
    )
    if not item:
        item = OAuthConnection(mobile_access_id=account.id, provider=provider)
        db.add(item)
    item.encrypted_credentials = encrypt_json(credentials)
    item.account_label = label
    item.metadata_json = metadata
    db.commit()


def handle_youtube_callback(db: Session, code: str, state: str) -> bool:
    resolved = _state_record(db, state, "youtube")
    if not resolved:
        return False
    state_record, account = resolved
    flow = Flow.from_client_secrets_file(
        youtube.CREDENTIALS_FILE,
        scopes=youtube.SCOPES,
        state=state,
    )
    flow.redirect_uri = f"{settings.base_url}/api/youtube/callback"
    flow.fetch_token(code=code)
    creds = json.loads(flow.credentials.to_json())
    service = youtube.get_youtube_service(creds)
    channel = service.channels().list(part="snippet", mine=True).execute()
    first = (channel.get("items") or [{}])[0]
    label = (first.get("snippet") or {}).get("title") or "YouTube"
    _save(db, account, "youtube", creds, label, {"channel_id": first.get("id")})
    _finish_state(db, state_record)
    return True


def handle_meta_callback(db: Session, code: str, state: str) -> bool:
    resolved = _state_record(db, state, "facebook")
    if not resolved:
        return False
    state_record, account = resolved
    data = meta.exchange_mobile_code(code)
    label = data.get("selected_page_name") or data.get("user_name") or "Meta"
    metadata = {
        "page_id": data.get("selected_page_id"),
        "page_name": data.get("selected_page_name"),
        "instagram_username": data.get("instagram_username"),
    }
    _save(db, account, "facebook", data, label, metadata)
    _finish_state(db, state_record)
    return True


def handle_instagram_callback(db: Session, code: str, state: str) -> bool:
    resolved = _state_record(db, state, "instagram")
    if not resolved:
        return False
    state_record, account = resolved
    data = instagram.exchange_code(code)
    profile = instagram.get_profile(data)
    data["user_id"] = profile.get("user_id") or profile.get("id") or data.get("user_id")
    label = profile.get("username") or profile.get("name") or "Instagram"
    _save(
        db,
        account,
        "instagram",
        data,
        label,
        {
            "username": profile.get("username"),
            "account_type": profile.get("account_type"),
        },
    )
    _finish_state(db, state_record)
    return True


def handle_tiktok_callback(db: Session, code: str, state: str) -> bool:
    resolved = _state_record(db, state, "tiktok")
    if not resolved:
        return False
    state_record, account = resolved
    data = tiktok.exchange_mobile_code(code)
    user = tiktok.get_user_info(data)
    label = user.get("display_name") or "TikTok"
    _save(db, account, "tiktok", data, label, {"open_id": user.get("open_id")})
    _finish_state(db, state_record)
    return True


def disconnect(db: Session, account_id: str, provider: str):
    item = connection(db, account_id, provider)
    if item:
        db.delete(item)
        db.commit()


def disconnect_provider_user(db: Session, provider: str, provider_user_id: str) -> bool:
    items = db.query(OAuthConnection).filter(OAuthConnection.provider == provider).all()
    for item in items:
        try:
            data = decrypt_json(item.encrypted_credentials)
        except Exception:
            continue
        if str(data.get("user_id") or "") == str(provider_user_id):
            db.delete(item)
            db.commit()
            return True
    return False


def select_facebook_page(db: Session, account_id: str, page_id: str):
    item = connection(db, account_id, "facebook")
    if not item:
        raise ValueError("Facebook is not connected")
    data = decrypt_json(item.encrypted_credentials)
    page = next(
        (candidate for candidate in data.get("pages", []) if candidate.get("id") == page_id),
        None,
    )
    if not page:
        raise ValueError("Facebook Page is not available for this Meta account")
    data.update(meta._selected_page_payload(page))
    metadata = {
        "page_id": data.get("selected_page_id"),
        "page_name": data.get("selected_page_name"),
        "instagram_username": data.get("instagram_username"),
    }
    account = canonical_access(db, account_id)
    _save(
        db,
        account,
        "facebook",
        data,
        data.get("selected_page_name") or "Meta",
        metadata,
    )
