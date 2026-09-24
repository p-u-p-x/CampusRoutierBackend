import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

_firebase_app = None


def _get_firebase_app():
    """
    Initializes the Firebase connection once, the first time it's needed,
    reusing it after that. Reads the service account key from the
    FIREBASE_CREDENTIALS_JSON environment variable, same pattern as
    DATABASE_URL, never committed to git.
    """
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    raw = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if not raw:
        logger.warning("FIREBASE_CREDENTIALS_JSON not set, push notifications are disabled")
        return None

    try:
        cred_dict = json.loads(raw)
        cred = credentials.Certificate(cred_dict)
        _firebase_app = firebase_admin.initialize_app(cred)
        return _firebase_app
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        return None


def send_push(device_token: str, title: str, body: str, data: dict = None) -> bool:
    """
    Sends one push notification to one device. Returns True if it was
    actually sent, False if it failed or Firebase isn't configured.
    Never raises - a failed notification should never break the request
    that triggered it (picking a student shouldn't fail just because
    their phone is unreachable).
    """
    app = _get_firebase_app()
    if app is None or not device_token:
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=device_token,
        )
        messaging.send(message, app=app)
        return True
    except Exception as e:
        logger.warning(f"Push notification failed for token ending ...{device_token[-6:]}: {e}")
        return False