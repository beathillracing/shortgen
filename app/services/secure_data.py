import base64
import hashlib
import json

from cryptography.fernet import Fernet

from app.config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode("utf-8")).decode("ascii")


def decrypt_json(value: str) -> dict:
    return json.loads(_fernet().decrypt(value.encode("ascii")).decode("utf-8"))
