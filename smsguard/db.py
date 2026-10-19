import sqlite3
from pathlib import Path

from flask import current_app, g

# Remote actions the web UI can queue for the Android app. The app polls
# /api/status (or checks in) and picks up whatever is pending.
REMOTE_ACTIONS = ("alarm", "locate", "lock")

# Column list shared by the devices rebuild migration below.
_DEVICES_COLUMNS = (
    "id, user_id, imei, model, color, notes, device_key, status, pending_action, "
    "lost_at, found_at, last_seen, last_lat, last_lon, last_battery, created_at"
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _table_sql(db, name):
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row["sql"] if row else None


def _rebuild_devices(db):
    """Recreate `devices` with the widened pending_action CHECK.

    SQLite cannot alter a CHECK constraint in place, so the table is copied.
    Foreign keys are switched off so the dependent rows (events, messages,
    locations) are not cascaded away by the DROP.
    """
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            CREATE TABLE devices_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                imei TEXT NOT NULL UNIQUE,
                model TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                device_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'lost')),
                pending_action TEXT NOT NULL DEFAULT ''
                    CHECK (pending_action IN ('', 'alarm', 'locate', 'lock')),
                lost_at TEXT,
                found_at TEXT,
                last_seen TEXT,
                last_lat REAL,
                last_lon REAL,
                last_battery INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO devices_new ({cols}) SELECT {cols} FROM devices;
            DROP TABLE devices;
            ALTER TABLE devices_new RENAME TO devices;
            CREATE INDEX IF NOT EXISTS idx_devices_imei ON devices(imei);
            CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
            CREATE INDEX IF NOT EXISTS idx_devices_key ON devices(device_key);
            """.format(cols=_DEVICES_COLUMNS)
        )
    finally:
        db.execute("PRAGMA foreign_keys = ON")
    db.commit()


def migrate_db():
    """Bring an existing database up to the current schema.

    `schema.sql` only creates missing objects, so columns and constraints that
    were added later need explicit handling here. Safe to run on every start.
    """
    db = get_db()

    # recovery_messages.is_read (added with unread finder-message tracking)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(recovery_messages)")}
    if columns and "is_read" not in columns:
        db.execute(
            "ALTER TABLE recovery_messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0"
        )
        db.commit()

    # The original pending_action CHECK only allowed '' / 'alarm'.
    devices_sql = _table_sql(db, "devices")
    if devices_sql and "'locate'" not in devices_sql:
        _rebuild_devices(db)


def init_db():
    db = get_db()
    base = Path(__file__).resolve().parent.parent
    with open(base / "schema.sql", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()
    migrate_db()


def init_app(app):
    app.teardown_appcontext(close_db)
