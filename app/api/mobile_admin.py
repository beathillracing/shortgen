from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MobileAccess, MobileUsage
from app.services.mobile_accounts import entitlement

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
        accounts.append(entitlement(db, row.account_id))
    return {"accounts": accounts}


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

    account.subscription_status = "admin_unlimited" if unlimited else "free"
    account.publishing_enabled = publishing
    account.monthly_job_limit = monthly_limit
    db.commit()
    return entitlement(db, account.account_id)


@router.delete("/mobile-access/{email}")
def revoke_mobile_account(email: str, db: Session = Depends(get_db)):
    account = _account_by_email(db, email)
    account.subscription_status = "free"
    account.publishing_enabled = False
    account.monthly_job_limit = None
    db.commit()
    return entitlement(db, account.account_id)
