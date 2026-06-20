import os
import threading

import firebase_admin
from firebase_admin import credentials, messaging

from app.config import settings
from app.models import MobileAccess

_app = None
_lock = threading.Lock()


def _ensure_app():
    global _app
    if _app is not None:
        return _app
    path = settings.firebase_credentials_file
    if not path or not os.path.exists(path):
        raise RuntimeError('Firebase credentials not configured')
    with _lock:
        if _app is None:
            _app = firebase_admin.initialize_app(credentials.Certificate(path))
    return _app


def register_token(db, access_id, token):
    row = db.query(MobileAccess).filter(MobileAccess.id == access_id).first()
    if row:
        row.fcm_token = token
        db.commit()


def _send(db, account_id, title, body, data):
    rows = (
        db.query(MobileAccess)
        .filter(MobileAccess.account_id == account_id, MobileAccess.active.is_(True))
        .all()
    )
    targets = [(r, r.fcm_token) for r in rows if r.fcm_token]
    if not targets:
        return
    _ensure_app()
    for row, token in targets:
        payload = {'title': title, 'body': body}
        payload.update({k: str(v) for k, v in (data or {}).items()})
        message = messaging.Message(
            token=token,
            data=payload,
            android=messaging.AndroidConfig(priority='high'),
        )
        try:
            messaging.send(message)
        except messaging.UnregisteredError:
            row.fcm_token = None
            db.commit()
        except Exception:
            pass


def notify_job(db, job):
    account_id = getattr(job, 'mobile_owner', None)
    if not account_id:
        return
    status = job.status
    if status == 'thumbnail_selection':
        title, body = 'Video ready', 'Choose your thumbnail and review'
    elif status in ('review', 'completed'):
        title, body = 'Video ready', job.original_filename or 'Your video is ready'
    elif status == 'failed':
        title, body = 'Processing failed', job.error_message or 'Open Beathill Studio for details'
    else:
        return
    try:
        _send(db, account_id, title, body, {'job_id': str(job.id)})
    except Exception:
        pass
