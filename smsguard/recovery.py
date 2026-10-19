from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db
from .security import limiter, validate_imei

bp = Blueprint("recovery", __name__)


@bp.get("/r/<imei>")
def recovery_page(imei):
    imei = imei.strip()
    if not validate_imei(imei):
        abort(404)
    db = get_db()
    device = db.execute("SELECT * FROM devices WHERE imei = ?", (imei,)).fetchone()
    if not device or device["status"] != "lost":
        return render_template("recovery.html", found=False, imei=imei)
    owner = db.execute(
        "SELECT email FROM users WHERE id = ?", (device["user_id"],)
    ).fetchone()
    return render_template(
        "recovery.html",
        found=True,
        imei=imei,
        device=device,
        owner_email=owner["email"] if owner else None,
    )


@bp.post("/r/<imei>/contact")
def contact_owner(imei):
    imei = imei.strip()
    if not validate_imei(imei):
        abort(404)
    if not limiter.allow("contact:{}:{}".format(request.remote_addr, imei), 3, 900):
        flash("Too many messages. Try again later.", "error")
        return redirect(url_for("recovery.recovery_page", imei=imei)), 429

    db = get_db()
    device = db.execute(
        "SELECT * FROM devices WHERE imei = ? AND status = 'lost'", (imei,)
    ).fetchone()
    if not device:
        abort(404)

    from_name = request.form.get("from_name", "").strip()[:80]
    from_phone = request.form.get("from_phone", "").strip()[:30]
    message = request.form.get("message", "").strip()[:1000]

    if not from_name or not message:
        flash("Please include your name and a message.", "error")
        return redirect(url_for("recovery.recovery_page", imei=imei))

    db.execute(
        "INSERT INTO recovery_messages (device_id, from_name, from_phone, message) "
        "VALUES (?, ?, ?, ?)",
        (device["id"], from_name, from_phone, message),
    )
    db.execute(
        "INSERT INTO events (device_id, type, detail) VALUES (?, 'finder_message', ?)",
        (device["id"], "Finder: {}".format(from_name)),
    )
    db.commit()
    flash("Message sent to the owner. Thank you for helping.", "success")
    return redirect(url_for("recovery.recovery_page", imei=imei))