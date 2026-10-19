import os
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from . import api, auth, devices, recovery
from .db import get_db
from .db import init_app as init_db_app
from .db import init_db
from .security import _ago, _mask, csrf_protect, new_csrf_token

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _secret_key():
    env = os.environ.get("SMSGUARD_SECRET_KEY")
    if env:
        return env
    DATA_DIR.mkdir(exist_ok=True)
    key_file = DATA_DIR / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


def _bool_env(name):
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=_secret_key(),
        DATABASE=os.environ.get("SMSGUARD_DATABASE", str(DATA_DIR / "smsguard.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_bool_env("SMSGUARD_COOKIE_SECURE"),
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if _bool_env("SMSGUARD_TRUST_PROXY"):
        # Behind a reverse proxy (Render, Fly, nginx) the real client address
        # arrives in X-Forwarded-For. Without this every request looks like it
        # comes from the proxy, so IP-based rate limiting would apply to all
        # visitors at once.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db_app(app)
    with app.app_context():
        init_db()

    app.before_request(csrf_protect)

    @app.context_processor
    def inject_globals():
        unread = 0
        user_id = session.get("user_id")
        if user_id:
            row = get_db().execute(
                "SELECT COUNT(*) AS n FROM recovery_messages m "
                "JOIN devices d ON d.id = m.device_id "
                "WHERE d.user_id = ? AND m.is_read = 0",
                (user_id,),
            ).fetchone()
            unread = row["n"] if row else 0
        return {
            "csrf_token": new_csrf_token,
            "now": time.time(),
            "mask": _mask,
            "ago": _ago,
            "unread_total": unread,
        }

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=e.description), 400

    @app.route("/")
    def index():
        if session.get("user_id"):
            return redirect(url_for("devices.dashboard"))
        return render_template("index.html")

    app.register_blueprint(auth.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(recovery.bp)
    app.register_blueprint(api.bp)
    return app