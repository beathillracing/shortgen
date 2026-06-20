import hashlib
import json
import secrets
from datetime import datetime, timedelta

import httpx
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MobileAccess, OAuthConnection, OAuthState
from app.services import meta, tiktok, youtube
from app.services.secure_data import decrypt_json, encrypt_json


def canonical_access(db: Session, account_id: str) -> MobileAccess:
    rows = db.query(MobileAccess).filter(MobileAccess.account_id == account_id).all()
    if not rows:
        raise ValueError("Account not found")
    return next((row for row in rows if row.google_subject), rows[0])


def connection(db: Session, account_id: str, provider: str) -> OAuthConnection | None:
    account = canonical_access(db, account_id)
    return (
        db.query(OAuthConnection)
        .filter(
            OAuthConnection.mobile_access_id == account.id,
            OAuthConnection.provider == provider,
        )
        .first()
    )


def connection_data(db: Session, account_id: str, provider: str) -> dict:
    item = connection(db, account_id, provider)
    if not item:
        raise ValueError(f"{provider.title()} is not connected")
    return decrypt_json(item.encrypted_credentials)


def connection_statuses(db: Session, account_id: str) -> dict:
    result = {}
    for provider in ("youtube", "meta", "tiktok"):
        item = connection(db, account_id, provider)
        result[provider] = {
            "connected": bool(item),
            "label": item.account_label if item else None,
            "metadata": item.metadata_json if item else {},
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
    if provider == "meta":
        return meta.get_auth_url(state=state, persist_state=False)
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
    resolved = _state_record(db, state, "meta")
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
    _save(db, account, "meta", data, label, metadata)
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
