from flask import Blueprint, jsonify, request

from .db import get_db
from .security import limiter

bp = Blueprint("api", __name__, url_prefix="/api")

# How many historical fixes to keep per device.
MAX_TRAIL_POINTS = 200


def _find_device(key):
    if not key:
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM devices WHERE device_key = ?", (key,)
    ).fetchone()


@bp.get("/status")
def status():
    device = _find_device(request.args.get("key", ""))
    if not device:
        return jsonify(error="Unknown device key"), 401
    return jsonify(
        status=device["status"],
        pending_action=device["pending_action"],
        lost_at=device["lost_at"],
        imei=device["imei"],
    )


@bp.post("/checkin")
def checkin():
    data = request.get_json(silent=True) or {}
    device = _find_device(data.get("key", ""))
    if not device:
        return jsonify(error="Unknown device key"), 401
    if not limiter.allow("checkin:{}".format(device["id"]), 60, 60):
        return jsonify(error="Rate limited"), 429

    db = get_db()
    lat = data.get("lat")
    lon = data.get("lon")
    battery = data.get("battery")
    updates = ["last_seen = datetime('now')"]
    values = []
    battery_value = None
    has_fix = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    if has_fix:
        updates.append("last_lat = ?")
        values.append(float(lat))
        updates.append("last_lon = ?")
        values.append(float(lon))
    if isinstance(battery, int):
        battery_value = max(0, min(100, battery))
        updates.append("last_battery = ?")
        values.append(battery_value)
    values.append(device["id"])
    db.execute(
        "UPDATE devices SET {} WHERE id = ?".format(", ".join(updates)), values
    )
    if has_fix:
        db.execute(
            "INSERT INTO locations (device_id, lat, lon, battery) VALUES (?, ?, ?, ?)",
            (device["id"], float(lat), float(lon), battery_value),
        )
        # Keep the trail bounded: retain the most recent MAX_TRAIL_POINTS fixes.
        db.execute(
            "DELETE FROM locations WHERE device_id = ? AND id NOT IN ("
            "SELECT id FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT ?)",
            (device["id"], device["id"], MAX_TRAIL_POINTS),
        )
    db.commit()

    return jsonify(
        status=device["status"],
        pending_action=device["pending_action"],
        lost_at=device["lost_at"],
    )


@bp.post("/ack")
def ack():
    data = request.get_json(silent=True) or {}
    device = _find_device(data.get("key", ""))
    if not device:
        return jsonify(error="Unknown device key"), 401

    action = data.get("action", "")
    db = get_db()
    db.execute(
        "UPDATE devices SET pending_action = '' "
        "WHERE id = ? AND pending_action = ?",
        (device["id"], action),
    )
    if db.total_changes:
        db.execute(
            "INSERT INTO events (device_id, type, detail) VALUES (?, 'action_done', ?)",
            (device["id"], "Executed remote action: {}".format(action or "ack")),
        )
    db.commit()
    return jsonify(ok=True)