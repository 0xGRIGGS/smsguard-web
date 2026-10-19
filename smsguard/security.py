import re
import secrets
import time
from functools import wraps
from threading import RLock

from flask import abort, redirect, request, session, url_for

CSRF_FIELD = "_csrf_token"
IMPORTANT_COOKIES = {"SESSION_COOKIE_HTTPONLY", "SESSION_COOKIE_SAMESITE"}

_IMEI_RE = re.compile(r"^\d{15}$")


def validate_imei(imei):
    if isinstance(imei, str):
        imei = imei.strip()
    if not _IMEI_RE.match(imei or ""):
        return False
    total = 0
    for i, char in enumerate(reversed(imei)):
        digit = ord(char) - 48
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _mask(value):
    if not value or "@" not in value:
        return value
    local, _, domain = value.partition("@")
    return "{}***@{}".format(local[:2], domain)


def new_device_key():
    return secrets.token_hex(16)


def new_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def csrf_protect():
    if request.method == "POST" and not request.path.startswith("/api/"):
        token = request.form.get(CSRF_FIELD, "")
        if not token or token != session.get("_csrf_token"):
            abort(400, description="Invalid or missing CSRF token")
    new_csrf_token()


def _ago(ts):
    if not ts:
        return "never"
    if isinstance(ts, str):
        from datetime import datetime, timezone

        try:
            ts = datetime.fromisoformat(ts.replace(" ", "T")).replace(
                tzinfo=timezone.utc
            ).timestamp()
        except ValueError:
            return ts
    units = ((31536000, "y"), (86400, "d"), (3600, "h"), (60, "m"))
    for secs, label in units:
        if ts >= secs:
            return "{}{} ago".format(int(ts // secs), label)
    return "just now"


class RateLimiter:
    def __init__(self):
        self._hits = {}
        self._lock = RLock()

    def allow(self, key, limit, window_seconds):
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, [])
            bucket = [t for t in bucket if now - t < window_seconds]
            self._hits[key] = bucket
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)


limiter = RateLimiter()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped