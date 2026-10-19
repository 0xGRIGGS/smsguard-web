import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import limiter, login_required

bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("devices.dashboard"))

    if request.method == "POST":
        if not limiter.allow("signup:{}".format(request.remote_addr), 5, 3600):
            flash("Too many sign-ups from this address. Try again later.", "error")
            return render_template("signup.html"), 429

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or len(name) > 80:
            flash("Please enter your name.", "error")
        elif not _EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if existing:
                flash("An account with that email already exists.", "error")
            else:
                cur = db.execute(
                    "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
                    (email, name, generate_password_hash(password)),
                )
                db.commit()
                session.clear()
                session["user_id"] = cur.lastrowid
                session["email"] = email
                flash("Welcome to SMSGuard ES. Register your device.", "success")
                return redirect(url_for("devices.dashboard"))

    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("devices.dashboard"))

    if request.method == "POST":
        if not limiter.allow("login:{}".format(request.remote_addr), 5, 300):
            flash("Too many attempts. Try again in a few minutes.", "error")
            return render_template("login.html"), 429

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
        else:
            limiter.clear("login:{}".format(request.remote_addr))
            session.clear()
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            return redirect(url_for("devices.dashboard"))

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@bp.route("/account")
@login_required
def account():
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    device_count = db.execute(
        "SELECT COUNT(*) AS n FROM devices WHERE user_id = ?", (session["user_id"],)
    ).fetchone()["n"]
    return render_template("account.html", user=user, device_count=device_count)


@bp.post("/account/password")
@login_required
def change_password():
    current = request.form.get("current", "")
    new = request.form.get("new", "")
    confirm = request.form.get("confirm", "")
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()

    if not user or not check_password_hash(user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif len(new) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    elif check_password_hash(user["password_hash"], new):
        flash("Please choose a password different from your current one.", "error")
    else:
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new), user["id"]),
        )
        db.commit()
        flash("Password updated.", "success")
    return redirect(url_for("auth.account"))