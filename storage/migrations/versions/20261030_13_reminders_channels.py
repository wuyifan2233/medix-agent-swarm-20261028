"""Reminders, deliveries and verified channel state use the account database."""
from alembic import op
revision='20261030_13'
down_revision='20261030_12'
branch_labels=None
depends_on=None
SCHEMA="\nCREATE TABLE IF NOT EXISTS reminders (\n    id TEXT PRIMARY KEY,\n    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n    session_id TEXT NOT NULL,\n    kind TEXT NOT NULL CHECK (kind IN ('medication', 'visit', 'followup')),\n    repeat TEXT NOT NULL CHECK (repeat IN ('once', 'daily', 'weekly')),\n    schedule TEXT NOT NULL,\n    timezone TEXT NOT NULL,\n    next_fire_at TEXT NOT NULL,\n    canonical_text TEXT NOT NULL,\n    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'cancelled', 'completed')),\n    drug TEXT NOT NULL DEFAULT '',\n    dose TEXT NOT NULL DEFAULT '',\n    location TEXT NOT NULL DEFAULT '',\n    note TEXT NOT NULL DEFAULT '',\n    created_at TEXT NOT NULL,\n    updated_at TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS reminder_deliveries (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n    session_id TEXT NOT NULL,\n    reminder_id TEXT NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,\n    scheduled_fire_at TEXT NOT NULL,\n    delivered_at TEXT NOT NULL,\n    read INTEGER NOT NULL DEFAULT 0,\n    canonical_text TEXT NOT NULL,\n    wechat_sent INTEGER NOT NULL DEFAULT 0,\n    UNIQUE (reminder_id, scheduled_fire_at)\n);\nCREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, status);\nCREATE INDEX IF NOT EXISTS idx_deliveries_user_read ON reminder_deliveries(user_id, read);\n\nCREATE TABLE channel_bindings(channel TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,payload TEXT NOT NULL,updated_at REAL NOT NULL);\nCREATE TABLE channel_preferences(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,channel TEXT NOT NULL);\n"
def upgrade():
    for sql in SCHEMA.split(';'):
        if sql.strip():op.execute(sql)
def downgrade():
    for name in ['channel_preferences','channel_bindings','reminder_deliveries','reminders']:op.drop_table(name)
