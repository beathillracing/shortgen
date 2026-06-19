import hashlib
import hmac

from app.config import settings


def _secret() -> str:
    return settings.public_media_secret or settings.secret_key


def media_token(job_id: str, kind: str) -> str:
    payload = f"{job_id}:{kind}".encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_media_token(job_id: str, kind: str, token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(media_token(job_id, kind), token)


def media_url(job_id: str, kind: str) -> str:
    token = media_token(job_id, kind)
    base_url = str(settings.base_url).rstrip("/")
    return f"{base_url}/public/jobs/{job_id}/{kind}?token={token}"
