from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .db import REMOTE_ACTIONS, get_db
from .security import login_required, new_device_key, validate_imei

bp = Blueprint("devices", __name__)


def _own_device(device_id):
    db = get_db()
    device = db.execute(
        "SELECT * FROM devices WHERE id = ? AND user_id = ?",
        (device_id, session["user_id"]),
    ).fetchone()
    if not device:
        abort(404)
    return device


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    devices = db.execute(
        "SELECT d.*, ("
        "  SELECT COUNT(*) FROM recovery_messages m "
        "  WHERE m.device_id = d.id AND m.is_read = 0"
        ") AS unread "
        "FROM devices d WHERE d.user_id = ? ORDER BY d.created_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("dashboard.html", devices=devices)


@bp.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        imei = request.form.get("imei", "").strip()
        model = request.form.get("model", "").strip()[:60]
        color = request.form.get("color", "").strip()[:30]
        notes = request.form.get("notes", "").strip()[:300]

        if not validate_imei(imei):
            flash("Invalid IMEI. It must be a 15-digit number with a valid check digit.", "error")
        else:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM devices WHERE imei = ?", (imei,)
            ).fetchone()
            if existing:
                flash("This IMEI is already registered.", "error")
            else:
                key = new_device_key()
                cur = db.execute(
                    "INSERT INTO devices (user_id, imei, model, color, notes, device_key) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (session["user_id"], imei, model, color, notes, key),
                )
                db.execute(
                    "INSERT INTO events (device_id, type, detail) VALUES (?, ?, ?)",
                    (cur.lastrowid, "registered", model or imei),
                )
                db.commit()
                flash("Device registered.", "success")
                return redirect(url_for("devices.device_detail", device_id=cur.lastrowid))

    return render_template("register.html")


@bp.get("/device/<int:device_id>")
@login_required
def device_detail(device_id):
    device = _own_device(device_id)
    db = get_db()
    events = db.execute(
        "SELECT * FROM events WHERE device_id = ? ORDER BY created_at DESC LIMIT 50",
        (device_id,),
    ).fetchall()
    messages = db.execute(
        "SELECT * FROM recovery_messages WHERE device_id = ? ORDER BY created_at DESC LIMIT 50",
        (device_id,),
    ).fetchall()
    # Remember which finder messages had not been seen yet, then mark them read
    # so the dashboard badge clears once the owner opens this page.
    unread_ids = {m["id"] for m in messages if not m["is_read"]}
    if unread_ids:
        db.execute(
            "UPDATE recovery_messages SET is_read = 1 "
            "WHERE device_id = ? AND is_read = 0",
            (device_id,),
        )
        db.commit()
    locations = db.execute(
        "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 25",
        (device_id,),
    ).fetchall()
    return render_template(
        "device_detail.html",
        device=device,
        events=events,
        messages=messages,
        unread_ids=unread_ids,
        locations=locations,
    )


@bp.post("/device/<int:device_id>/action/<action>")
@login_required
def request_action(device_id, action):
    device = _own_device(device_id)
    if action not in REMOTE_ACTIONS:
        abort(404)
    db = get_db()
    db.execute(
        "UPDATE devices SET pending_action = ? WHERE id = ?", (action, device_id)
    )
    db.execute(
        "INSERT INTO events (device_id, type, detail) VALUES (?, 'action_requested', ?)",
        (device_id, "Requested {}".format(action)),
    )
    db.commit()
    flash(
        "{} requested. It will run the next time the app checks in.".format(
            action.capitalize()
        ),
        "success",
    )
    return redirect(url_for("devices.device_detail", device_id=device_id))


@bp.post("/device/<int:device_id>/lost")
@login_required
def mark_lost(device_id):
    device = _own_device(device_id)
    db = get_db()
    db.execute(
        "UPDATE devices SET status = 'lost', pending_action = 'alarm', "
        "lost_at = datetime('now') WHERE id = ?",
        (device_id,),
    )
    db.execute(
        "INSERT INTO events (device_id, type, detail) VALUES (?, 'flag_lost', ?)",
        (device_id, "Device flagged as lost"),
    )
    db.commit()
    flash("{} marked as lost. Recovery link active and alarm pending.".format(device["model"]), "success")
    return redirect(url_for("devices.device_detail", device_id=device_id))


@bp.post("/device/<int:device_id>/found")
@login_required
def mark_found(device_id):
    device = _own_device(device_id)
    db = get_db()
    db.execute(
        "UPDATE devices SET status = 'active', pending_action = '', "
        "found_at = datetime('now') WHERE id = ? AND status = 'lost'",
        (device_id,),
    )
    if db.total_changes:
        db.execute(
            "INSERT INTO events (device_id, type, detail) VALUES (?, 'mark_found', ?)",
            (device_id, "Device marked as found"),
        )
    db.commit()
    flash("{} marked as found.".format(device["model"]), "success")
    return redirect(url_for("devices.device_detail", device_id=device_id))


@bp.post("/device/<int:device_id>/delete")
@login_required
def delete_device(device_id):
    device = _own_device(device_id)
    db = get_db()
    db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    db.commit()
    flash("{} removed.".format(device["model"]), "success")
    return redirect(url_for("devices.dashboard"))