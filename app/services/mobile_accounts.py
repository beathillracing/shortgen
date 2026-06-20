import hashlib
from datetime import datetime, timedelta, timezone

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MobileAccess, MobileUsage
from app.services.secure_data import decrypt_json, encrypt_json


ACTIVE_SUBSCRIPTION_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
}


def utcnow() -> datetime:
    return datetime.utcnow()


def parse_google_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def account_rows(db: Session, account_id: str) -> list[MobileAccess]:
    return db.query(MobileAccess).filter(MobileAccess.account_id == account_id).all()


def account_record(db: Session, account_id: str) -> MobileAccess:
    rows = account_rows(db, account_id)
    if not rows:
        raise ValueError("Account not found")
    return next((row for row in rows if row.google_subject), rows[0])


def entitlement(db: Session, account_id: str) -> dict:
    account = account_record(db, account_id)
    now = utcnow()
    admin_unlimited = bool(account.admin_unlimited) or (
        account.subscription_status == "admin_unlimited"
    )
    active = (
        admin_unlimited
        or account.subscription_status in {"active", "grace"}
        and (
            (account.subscription_expires_at and account.subscription_expires_at > now)
            or (account.subscription_grace_until and account.subscription_grace_until > now)
        )
    )
    period = now.strftime("%Y-%m")
    usage = (
        db.query(MobileUsage)
        .filter(
            MobileUsage.mobile_access_id == account.id,
            MobileUsage.period == period,
        )
        .first()
    )
    used = usage.jobs_started if usage else 0
    limit = account.monthly_job_limit or settings.free_monthly_job_limit
    return {
        "account_id": account_id,
        "email": account.email,
        "display_name": account.display_name,
        "google_linked": bool(account.google_subject),
        "plan": "unlimited" if admin_unlimited
        else "pro" if active else "free",
        "subscription_status": account.subscription_status,
        "subscription_expires_at": (
            account.subscription_expires_at.isoformat() + "Z"
            if account.subscription_expires_at else None
        ),
        "subscription_grace_until": (
            account.subscription_grace_until.isoformat() + "Z"
            if account.subscription_grace_until else None
        ),
        "subscription_checked_at": (
            account.subscription_checked_at.isoformat() + "Z"
            if account.subscription_checked_at else None
        ),
        "publishing_enabled": active or bool(account.publishing_enabled),
        "usage": {
            "period": period,
            "jobs_used": used,
            "jobs_limit": None if active else limit,
            "jobs_remaining": None if active else max(limit - used, 0),
        },
    }


def consume_job_allowance(db: Session, account_id: str):
    record = account_record(db, account_id)
    account = (
        db.query(MobileAccess)
        .filter(MobileAccess.id == record.id)
        .with_for_update()
        .one()
    )
    current = entitlement(db, account_id)
    if current["usage"]["jobs_remaining"] is None:
        return current

    period = current["usage"]["period"]
    usage = (
        db.query(MobileUsage)
        .filter(
            MobileUsage.mobile_access_id == account.id,
            MobileUsage.period == period,
        )
        .with_for_update()
        .first()
    )
    if not usage:
        usage = MobileUsage(
            mobile_access_id=account.id,
            period=period,
            jobs_started=0,
        )
        db.add(usage)
    limit = account.monthly_job_limit or settings.free_monthly_job_limit
    if usage.jobs_started >= limit:
        db.rollback()
        raise ValueError("Free monthly processing limit reached")
    usage.jobs_started += 1
    db.commit()
    return entitlement(db, account_id)


def link_google_identity(db: Session, access_id: str, credential: str) -> dict:
    if not settings.google_web_client_id:
        raise RuntimeError("Google Sign-In client ID is not configured")
    claims = id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.google_web_client_id,
    )
    subject = claims["sub"]
    current = db.query(MobileAccess).filter(MobileAccess.id == access_id).first()
    if not current or not current.active:
        raise ValueError("Access credential not found")

    existing = (
        db.query(MobileAccess)
        .filter(
            MobileAccess.google_subject == subject,
            MobileAccess.active.is_(True),
        )
        .first()
    )
    if existing and existing.account_id != current.account_id:
        current.account_id = existing.account_id
        current.label = existing.label
    else:
        current.google_subject = subject
        current.email = claims.get("email")
        current.display_name = claims.get("name")
        current.label = claims.get("name") or claims.get("email") or "Beathill Studio"
    db.commit()
    return entitlement(db, current.account_id)


def _publisher_service():
    if not settings.google_play_service_account_file:
        raise RuntimeError("Google Play service account is not configured")
    credentials = service_account.Credentials.from_service_account_file(
        settings.google_play_service_account_file,
        scopes=["https://www.googleapis.com/auth/androidpublisher"],
    )
    return build("androidpublisher", "v3", credentials=credentials, cache_discovery=False)


def _subscription_purchase(purchase_token: str) -> dict:
    service = _publisher_service()
    return service.purchases().subscriptionsv2().get(
        packageName=settings.google_play_package_name,
        token=purchase_token,
    ).execute()


def _apply_subscription(
    db: Session,
    account_id: str,
    purchase_token: str,
    purchase: dict,
) -> dict:
    line_items = purchase.get("lineItems") or []
    product_ids = {item.get("productId") for item in line_items}
    if settings.google_play_subscription_product_id not in product_ids:
        raise ValueError("Purchase is not for Beathill Studio Pro")

    state = purchase.get("subscriptionState", "")
    expiries = [parse_google_time(item.get("expiryTime")) for item in line_items]
    expiries = [value for value in expiries if value]
    expires_at = max(expiries) if expiries else None
    account = account_record(db, account_id)
    account.subscription_product_id = settings.google_play_subscription_product_id
    account.subscription_purchase_token_hash = hashlib.sha256(
        purchase_token.encode("utf-8")
    ).hexdigest()
    account.subscription_purchase_token_encrypted = encrypt_json(
        {"purchase_token": purchase_token}
    )
    account.subscription_checked_at = utcnow()
    account.subscription_expires_at = expires_at
    account.subscription_status = (
        "grace" if state == "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"
        else "active" if state in ACTIVE_SUBSCRIPTION_STATES
        else "expired"
    )
    account.subscription_grace_until = expires_at if account.subscription_status == "grace" else None
    db.commit()
    return entitlement(db, account_id)


def verify_subscription(db: Session, account_id: str, purchase_token: str) -> dict:
    return _apply_subscription(
        db,
        account_id,
        purchase_token,
        _subscription_purchase(purchase_token),
    )


def refresh_subscription_if_due(
    db: Session,
    account_id: str,
    max_age: timedelta = timedelta(hours=6),
) -> dict:
    account = account_record(db, account_id)
    if account.admin_unlimited or account.subscription_status == "admin_unlimited":
        return entitlement(db, account_id)
    if not account.subscription_purchase_token_encrypted:
        return entitlement(db, account_id)
    if (
        account.subscription_checked_at
        and account.subscription_checked_at > utcnow() - max_age
    ):
        return entitlement(db, account_id)

    purchase_token = decrypt_json(
        account.subscription_purchase_token_encrypted
    )["purchase_token"]
    return _apply_subscription(
        db,
        account_id,
        purchase_token,
        _subscription_purchase(purchase_token),
    )
