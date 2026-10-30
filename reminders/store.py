"""SQLite storage for reminders and their deliveries."""
import sqlite3
import threading
from pathlib import Path

from .schedule import iso_local, now_shanghai


SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('medication', 'visit', 'followup')),
    repeat TEXT NOT NULL CHECK (repeat IN ('once', 'daily', 'weekly')),
    schedule TEXT NOT NULL,
    timezone TEXT NOT NULL,
    next_fire_at TEXT NOT NULL,
    canonical_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'cancelled', 'completed')),
    drug TEXT NOT NULL DEFAULT '',
    dose TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    reminder_id TEXT NOT NULL,
    scheduled_fire_at TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    canonical_text TEXT NOT NULL,
    wechat_sent INTEGER NOT NULL DEFAULT 0,
    UNIQUE (reminder_id, scheduled_fire_at)
);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_deliveries_user_read ON deliveries(user_id, read);
"""


class ReminderStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(deliveries)")}
        if "wechat_sent" not in columns:
            self.conn.execute("ALTER TABLE deliveries ADD COLUMN wechat_sent INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def close(self):
        with self.lock:
            if self.conn is None:
                return
            self.conn.close()
            self.conn = None

    def insert_reminder(self, row):
        moment = iso_local(now_shanghai())
        with self.lock:
            self.conn.execute(
                """INSERT INTO reminders (
                    id, user_id, session_id, kind, repeat, schedule, timezone, next_fire_at,
                    canonical_text, status, drug, dose, location, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                (row["id"], row["user_id"], row["session_id"], row["kind"], row["repeat"], row["schedule"],
                 row["timezone"], row["next_fire_at"], row["canonical_text"], row["drug"], row["dose"],
                 row["location"], row["note"], moment, moment))
            self.conn.commit()

    def get(self, reminder_id):
        with self.lock:
            found = self.conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return dict(found) if found else None

    def get_for_user(self, reminder_id, user_id):
        with self.lock:
            found = self.conn.execute(
                "SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)).fetchone()
        return dict(found) if found else None

    def active_rows(self):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE status = 'active' ORDER BY next_fire_at").fetchall()
        return [dict(row) for row in rows]

    def active_for_user(self, user_id):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND status = 'active' ORDER BY next_fire_at",
                (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def save_state(self, reminder_id, *, status, next_fire_at, canonical_text, schedule=None, repeat=None,
                   kind=None, drug=None, dose=None, location=None, note=None):
        assignments = ["status = ?", "next_fire_at = ?", "canonical_text = ?", "updated_at = ?"]
        values = [status, next_fire_at, canonical_text, iso_local(now_shanghai())]
        for column, value in (("schedule", schedule), ("repeat", repeat), ("kind", kind), ("drug", drug),
                              ("dose", dose), ("location", location), ("note", note)):
            if value is not None:
                assignments.append(column + " = ?")
                values.append(value)
        values.append(reminder_id)
        with self.lock:
            self.conn.execute(f"UPDATE reminders SET {', '.join(assignments)} WHERE id = ?", values)
            self.conn.commit()

    def add_delivery(self, *, user_id, session_id, reminder_id, scheduled_fire_at, canonical_text, delivered_at):
        with self.lock:
            before = self.conn.total_changes
            self.conn.execute(
                """INSERT OR IGNORE INTO deliveries (
                    user_id, session_id, reminder_id, scheduled_fire_at, delivered_at, read, canonical_text
                ) VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (user_id, session_id, reminder_id, scheduled_fire_at, delivered_at, canonical_text))
            self.conn.commit()
            return self.conn.total_changes > before

    def unread_for_user(self, user_id):
        with self.lock:
            rows = self.conn.execute(
                """SELECT d.*, r.kind FROM deliveries d
                   JOIN reminders r ON r.id = d.reminder_id
                   WHERE d.user_id = ? AND d.read = 0
                   ORDER BY d.id""",
                (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def pending_wechat(self, user_id, limit=3):
        with self.lock:
            rows = self.conn.execute(
                """SELECT id, canonical_text FROM deliveries
                   WHERE user_id = ? AND wechat_sent = 0
                   ORDER BY id LIMIT ?""",
                (user_id, int(limit))).fetchall()
        return [dict(row) for row in rows]

    def mark_wechat_sent(self, user_id, delivery_id):
        with self.lock:
            self.conn.execute(
                "UPDATE deliveries SET wechat_sent = 1 WHERE user_id = ? AND id = ?",
                (user_id, delivery_id))
            self.conn.commit()

    def mark_read(self, user_id, delivery_ids):
        if not delivery_ids:
            return
        marks = ",".join("?" for _ in delivery_ids)
        with self.lock:
            self.conn.execute(
                f"UPDATE deliveries SET read = 1 WHERE user_id = ? AND id IN ({marks})",
                (user_id, *delivery_ids))
            self.conn.commit()

    def count_reminders(self):
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]

    def count_deliveries(self, reminder_id=None):
        with self.lock:
            if reminder_id is None:
                return self.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
            return self.conn.execute(
                "SELECT COUNT(*) FROM deliveries WHERE reminder_id = ?", (reminder_id,)).fetchone()[0]
