import hashlib
import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import MobileAccess


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access(
    db: Session,
    label: str,
    publishing_enabled: bool = False,
) -> tuple[MobileAccess, str]:
    token = f"bst_{secrets.token_urlsafe(24)}"
    access = MobileAccess(
        token_hash=token_hash(token),
        label=label.strip()[:100],
        owner=f"friend-{secrets.token_hex(8)}",
        role="friend",
        publishing_enabled=publishing_enabled,
    )
    access.account_id = access.owner
    db.add(access)
    db.commit()
    db.refresh(access)
    return access, token


def register_installation(
    db: Session,
    installation_id: str,
    token: str,
) -> MobileAccess:
    hashed = token_hash(token)
    existing = (
        db.query(MobileAccess)
        .filter(MobileAccess.installation_id == installation_id)
        .first()
    )
    if existing:
        if existing.token_hash != hashed or not existing.active:
            raise ValueError("Installation is already registered")
        return existing

    access = MobileAccess(
        token_hash=hashed,
        installation_id=installation_id,
        label="Beathill Studio",
        owner=f"play-{secrets.token_hex(12)}",
        role="free",
        publishing_enabled=False,
    )
    access.account_id = access.owner
    db.add(access)
    db.commit()
    db.refresh(access)
    return access


def resolve_access(db: Session, token: str) -> dict | None:
    access = (
        db.query(MobileAccess)
        .filter(
            MobileAccess.token_hash == token_hash(token),
            MobileAccess.active.is_(True),
        )
        .first()
    )
    if not access:
        return None

    access.last_used_at = datetime.utcnow()
    db.commit()
    return {
        "role": access.role,
        "owner": access.account_id or access.owner,
        "access_id": str(access.id),
        "publishing_enabled": bool(access.publishing_enabled),
        "label": access.label,
    }
