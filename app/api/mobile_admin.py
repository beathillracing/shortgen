from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Job, MobileAccess, MobileUsage
from app.services import instagram, meta, tiktok, youtube
from app.services.mobile_accounts import _publisher_service, entitlement
from app.services.mobile_oauth import connection_statuses

router = APIRouter()


def _account_by_email(db: Session, email: str) -> MobileAccess:
    account = (
        db.query(MobileAccess)
        .filter(
            MobileAccess.email.ilike(email.strip()),
            MobileAccess.active.is_(True),
        )
        .first()
    )
    if not account:
        raise HTTPException(
            404,
            "No linked Beathill Studio account found for that email. "
            "The user must link Google in the app first.",
        )
    return account


@router.get("/mobile-access")
def list_mobile_accounts(db: Session = Depends(get_db)):
    canonical = (
        db.query(MobileAccess)
        .filter(
            MobileAccess.active.is_(True),
            MobileAccess.email.isnot(None),
        )
        .order_by(MobileAccess.created_at.desc())
        .all()
    )
    seen = set()
    accounts = []
    for row in canonical:
        if row.account_id in seen:
            continue
        seen.add(row.account_id)
        payload = entitlement(db, row.account_id)
        try:
            payload["connections"] = connection_statuses(db, row.account_id)
        except Exception:
            payload["connections"] = {}
        payload["sessions"] = (
            db.query(MobileAccess)
            .filter(
                MobileAccess.account_id == row.account_id,
                MobileAccess.active.is_(True),
            )
            .count()
        )
        payload["jobs_total"] = (
            db.query(Job).filter(Job.mobile_owner == row.account_id).count()
        )
        accounts.append(payload)
    return {"accounts": accounts}


@router.get("/mobile-health")
def mobile_health(db: Session = Depends(get_db)):
    play_ok = False
    play_error = None
    try:
        _publisher_service().monetization().subscriptions().get(
            packageName=settings.google_play_package_name,
            productId=settings.google_play_subscription_product_id,
        ).execute()
        play_ok = True
    except Exception as exc:
        play_error = str(exc)

    redis_ok = False
    try:
        redis_ok = bool(Redis.from_url(settings.redis_url).ping())
    except Exception:
        pass

    return {
        "play_subscription": {
            "ok": play_ok,
            "product_id": settings.google_play_subscription_product_id,
            "error": play_error,
        },
        "providers": {
            "youtube": youtube.Path(youtube.CREDENTIALS_FILE).exists(),
            "facebook": meta.is_configured(),
            "instagram": instagram.is_configured(),
            "tiktok": tiktok.is_configured(),
        },
        "redis": redis_ok,
        "accounts": (
            db.query(MobileAccess.account_id)
            .filter(
                MobileAccess.active.is_(True),
                MobileAccess.email.isnot(None),
            )
            .distinct()
            .count()
        ),
        "jobs": db.query(Job).filter(Job.mobile_owner.isnot(None)).count(),
    }


@router.put("/mobile-access")
def update_mobile_account(data: dict, db: Session = Depends(get_db)):
    email = str(data.get("email") or "").strip()
    if not email:
        raise HTTPException(400, "Email is required")
    account = _account_by_email(db, email)
    unlimited = bool(data.get("unlimited"))
    publishing = bool(data.get("publishing_enabled"))
    monthly_limit = data.get("monthly_job_limit")
    if monthly_limit in ("", None):
        monthly_limit = None
    else:
        try:
            monthly_limit = max(1, int(monthly_limit))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Monthly limit must be a positive number") from exc

    account.admin_unlimited = unlimited
    account.publishing_enabled = publishing
    account.monthly_job_limit = monthly_limit
    db.commit()
    return entitlement(db, account.account_id)


@router.delete("/mobile-access/{email}")
def revoke_mobile_account(email: str, db: Session = Depends(get_db)):
    account = _account_by_email(db, email)
    account.admin_unlimited = False
    account.publishing_enabled = False
    account.monthly_job_limit = None
    db.commit()
    return entitlement(db, account.account_id)
