from conftest import (
    INVALID_IMEI,
    VALID_IMEI,
    csrf,
    login,
    logout,
    register_device,
    signup,
)


def device_key(app, imei=VALID_IMEI):
    from smsguard.db import get_db

    with app.app_context():
        return get_db().execute(
            "SELECT id, device_key FROM devices WHERE imei = ?", (imei,)
        ).fetchone()


def test_health(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_index_loads(client):
    body = client.get("/").data.decode()
    assert "SMSGuard" in body


def test_signup_login_logout(client):
    assert "Register your device" in signup(client).data.decode()
    logout(client)
    r = login(client)
    assert r.status_code == 200
    assert "My devices" in r.data.decode()


def test_signup_weak_password_rejected(client):
    r = client.get("/signup")
    r = client.post(
        "/signup",
        data={
            "_csrf_token": csrf(r.data),
            "name": "A",
            "email": "a@b.com",
            "password": "short",
            "confirm": "short",
        },
        follow_redirects=True,
    )
    assert "at least 8 characters" in r.data.decode()


def test_signup_mismatched_password(client):
    r = client.get("/signup")
    r = client.post(
        "/signup",
        data={
            "_csrf_token": csrf(r.data),
            "name": "A",
            "email": "a@b.com",
            "password": "password1",
            "confirm": "password2",
        },
        follow_redirects=True,
    )
    assert "do not match" in r.data.decode()


def test_duplicate_email_rejected(app, client):
    signup(client)
    other = app.test_client()
    r = signup(other, email="alice@example.com")
    assert "already exists" in r.data.decode()


def test_login_wrong_password(client):
    signup(client)
    logout(client)
    r = login(client, password="nope")
    assert "Invalid email or password" in r.data.decode()


def test_login_rate_limited(client):
    r = client.get("/login")
    token = csrf(r.data)
    for _ in range(5):
        client.post(
            "/login",
            data={"_csrf_token": token, "email": "x@y.z", "password": "wrong"},
        )
    r = client.post(
        "/login",
        data={"_csrf_token": token, "email": "x@y.z", "password": "wrong"},
    )
    assert r.status_code == 429


def test_register_valid_device(client):
    signup(client)
    r = register_device(client)
    assert "Pixel 8" in r.data.decode()


def test_register_invalid_imei_rejected(client):
    signup(client)
    r = register_device(client, imei=INVALID_IMEI)
    assert "Invalid IMEI" in r.data.decode()


def test_register_duplicate_imei_rejected(client):
    signup(client)
    register_device(client)
    r = register_device(client)
    assert "already registered" in r.data.decode()


def test_malformed_inputs_do_not_crash(client):
    signup(client)
    r = client.get("/register")
    r = client.post(
        "/register",
        data={"_csrf_token": csrf(r.data), "imei": "a" * 5000, "model": "x" * 5000},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Invalid IMEI" in r.data.decode()


def test_csrf_required_on_post(client):
    signup(client)
    r = client.post("/register", data={"imei": VALID_IMEI})
    assert r.status_code == 400


def test_lost_flow_and_recovery(client, app):
    signup(client)
    register_device(client)
    did = device_key(app)["id"]

    r = client.get(f"/device/{did}")
    r = client.post(f"/device/{did}/lost", data={"_csrf_token": csrf(r.data)}, follow_redirects=True)
    assert "flagged as lost" in r.data.decode().lower()

    body = client.get(f"/r/{VALID_IMEI}").data.decode()
    assert "reported lost" in body and "Send to owner" in body

    r = client.post(
        f"/r/{VALID_IMEI}/contact",
        data={"_csrf_token": csrf(body), "from_name": "Bob", "message": "found it"},
        follow_redirects=True,
    )
    assert "sent to the owner" in r.data.decode()


def test_recovery_hidden_when_not_lost(client):
    signup(client)
    register_device(client)
    body = client.get(f"/r/{VALID_IMEI}").data.decode()
    assert "No report found" in body
    assert "Pixel 8" not in body


def test_recovery_invalid_imei_404(client):
    assert client.get("/r/123").status_code == 404


def test_cross_user_access_denied(client, app):
    signup(client)
    register_device(client)
    did = device_key(app)["id"]

    other = app.test_client()
    signup(other, email="bob@example.com")
    assert other.get(f"/device/{did}").status_code == 404


def test_api_status_and_ack(client, app):
    signup(client)
    register_device(client)
    key = device_key(app)["device_key"]

    assert client.get("/api/status?key=bad").status_code == 401

    r = client.get(f"/api/status?key={key}")
    assert r.get_json()["status"] == "active"

    did = device_key(app)["id"]
    page = client.get(f"/device/{did}").data.decode()
    client.post(f"/device/{did}/lost", data={"_csrf_token": csrf(page)})

    r = client.post(
        "/api/checkin", json={"key": key, "lat": 9.01, "lon": 38.7, "battery": 82}
    )
    body = r.get_json()
    assert body["status"] == "lost" and body["pending_action"] == "alarm"

    client.post("/api/ack", json={"key": key, "action": "alarm"})
    assert client.get(f"/api/status?key={key}").get_json()["pending_action"] == ""


def test_api_checkin_ignores_bad_types(client, app):
    signup(client)
    register_device(client)
    key = device_key(app)["device_key"]
    r = client.post(
        "/api/checkin",
        json={"key": key, "lat": "not-a-number", "lon": None, "battery": "high"},
    )
    assert r.status_code == 200


def test_api_checkin_rate_limited(client, app):
    signup(client)
    register_device(client)
    key = device_key(app)["device_key"]
    last = None
    for _ in range(62):
        last = client.post("/api/checkin", json={"key": key})
    assert last.status_code == 429


def test_pages_require_login(client):
    for path in ("/dashboard", "/register"):
        r = client.get(path)
        assert r.status_code == 302


# --- change password --------------------------------------------------------


def _account_token(client):
    return csrf(client.get("/account").data)


def test_account_requires_login(client):
    assert client.get("/account").status_code == 302


def test_change_password_rejects_wrong_current(client):
    signup(client)
    r = client.post(
        "/account/password",
        data={
            "_csrf_token": _account_token(client),
            "current": "not-it",
            "new": "brandnew1",
            "confirm": "brandnew1",
        },
        follow_redirects=True,
    )
    assert "current password is incorrect" in r.data.decode().lower()


def test_change_password_rejects_short_and_mismatch(client):
    signup(client)
    r = client.post(
        "/account/password",
        data={
            "_csrf_token": _account_token(client),
            "current": "password1",
            "new": "short",
            "confirm": "short",
        },
        follow_redirects=True,
    )
    assert "at least 8 characters" in r.data.decode()

    r = client.post(
        "/account/password",
        data={
            "_csrf_token": _account_token(client),
            "current": "password1",
            "new": "brandnew1",
            "confirm": "brandnew2",
        },
        follow_redirects=True,
    )
    assert "do not match" in r.data.decode()


def test_change_password_then_login_with_new(client):
    signup(client)
    r = client.post(
        "/account/password",
        data={
            "_csrf_token": _account_token(client),
            "current": "password1",
            "new": "brandnew1",
            "confirm": "brandnew1",
        },
        follow_redirects=True,
    )
    assert "Password updated" in r.data.decode()

    logout(client)
    assert "Invalid email or password" in login(client, password="password1").data.decode()
    assert "My devices" in login(client, password="brandnew1").data.decode()


# --- remote actions ---------------------------------------------------------


def test_remote_action_queued_and_acknowledged(client, app):
    signup(client)
    register_device(client)
    row = device_key(app)
    did = row["id"]
    page = client.get(f"/device/{did}").data.decode()

    r = client.post(
        f"/device/{did}/action/locate",
        data={"_csrf_token": csrf(page)},
        follow_redirects=True,
    )
    assert "Locate requested" in r.data.decode()
    assert (
        client.get(f"/api/status?key={row['device_key']}").get_json()["pending_action"]
        == "locate"
    )

    client.post("/api/ack", json={"key": row["device_key"], "action": "locate"})
    assert (
        client.get(f"/api/status?key={row['device_key']}").get_json()["pending_action"]
        == ""
    )


def test_remote_action_invalid_is_404(client, app):
    signup(client)
    register_device(client)
    did = device_key(app)["id"]
    page = client.get(f"/device/{did}").data.decode()
    r = client.post(f"/device/{did}/action/explode", data={"_csrf_token": csrf(page)})
    assert r.status_code == 404


# --- location trail ---------------------------------------------------------


def test_location_trail_recorded_and_shown(client, app):
    signup(client)
    register_device(client)
    key = device_key(app)["device_key"]
    client.post(
        "/api/checkin",
        json={"key": key, "lat": 9.01234, "lon": 38.76543, "battery": 77},
    )

    did = device_key(app)["id"]
    body = client.get(f"/device/{did}").data.decode()
    assert "Location trail" in body
    assert "9.01234" in body and "38.76543" in body

    from smsguard.db import get_db

    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) AS n FROM locations WHERE device_id = ?", (did,)
        ).fetchone()["n"]
    assert n == 1


# --- unread finder messages -------------------------------------------------


def test_unread_finder_message_is_flagged(client, app):
    signup(client)
    register_device(client)
    did = device_key(app)["id"]
    page = client.get(f"/device/{did}").data.decode()
    client.post(f"/device/{did}/lost", data={"_csrf_token": csrf(page)})

    rec = client.get(f"/r/{VALID_IMEI}").data.decode()
    client.post(
        f"/r/{VALID_IMEI}/contact",
        data={"_csrf_token": csrf(rec), "from_name": "Bob", "message": "I found it"},
    )

    assert "1 new message" in client.get("/dashboard").data.decode()

    detail = client.get(f"/device/{did}").data.decode()
    assert "NEW" in detail and "I found it" in detail

    # Opening the device page marks it read, so the badge is gone afterwards.
    assert "new message" not in client.get("/dashboard").data.decode()


# --- signup abuse protection ------------------------------------------------


def test_signup_rate_limited(client):
    for i in range(5):
        signup(client, email=f"user{i}@example.com")
        logout(client)
    r = signup(client, email="user5@example.com")
    assert r.status_code == 429
    assert "Too many sign-ups" in r.data.decode()


# --- schema migration -------------------------------------------------------

OLD_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    imei TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    device_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'lost')),
    pending_action TEXT NOT NULL DEFAULT '' CHECK (pending_action IN ('', 'alarm')),
    lost_at TEXT,
    found_at TEXT,
    last_seen TEXT,
    last_lat REAL,
    last_lon REAL,
    last_battery INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE recovery_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    from_name TEXT NOT NULL DEFAULT '',
    from_phone TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def test_migrates_old_database(tmp_path):
    import sqlite3

    from smsguard import create_app as make_app
    from smsguard.db import get_db
    from smsguard.security import limiter

    db_path = str(tmp_path / "old.db")
    con = sqlite3.connect(db_path)
    con.executescript(OLD_SCHEMA)
    con.execute(
        "INSERT INTO users (email, name, password_hash) VALUES ('a@b.com', 'Al', 'x')"
    )
    con.execute(
        "INSERT INTO devices (user_id, imei, model, device_key) "
        "VALUES (1, ?, 'Old Phone', 'k1')",
        (VALID_IMEI,),
    )
    con.execute(
        "INSERT INTO events (device_id, type, detail) "
        "VALUES (1, 'registered', 'Old Phone')"
    )
    con.execute(
        "INSERT INTO recovery_messages (device_id, from_name, message) "
        "VALUES (1, 'Bob', 'hi')"
    )
    con.commit()
    con.close()

    limiter._hits.clear()
    app = make_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE": db_path})

    with app.app_context():
        db = get_db()
        # Existing rows survived the devices rebuild.
        assert db.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"] == 1
        assert db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 1
        assert (
            db.execute("SELECT COUNT(*) AS n FROM recovery_messages").fetchone()["n"]
            == 1
        )
        # New column and widened CHECK are in place.
        cols = {r["name"] for r in db.execute("PRAGMA table_info(recovery_messages)")}
        assert "is_read" in cols
        db.execute("UPDATE devices SET pending_action = 'locate' WHERE id = 1")
        db.commit()
        assert (
            db.execute(
                "SELECT pending_action FROM devices WHERE id = 1"
            ).fetchone()["pending_action"]
            == "locate"
        )
        assert db.execute("SELECT COUNT(*) AS n FROM locations").fetchone()["n"] == 0
