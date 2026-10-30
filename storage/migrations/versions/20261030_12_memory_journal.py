"""Local memory journals share the account database; synthetic demo has separate tables."""
from alembic import op
revision='20261030_12'
down_revision='20261030_11'
branch_labels=None
depends_on=None
STATEMENTS=['CREATE TABLE IF NOT EXISTS memory_cases (\n            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, session TEXT NOT NULL,\n            patient TEXT NOT NULL, content TEXT NOT NULL, observations TEXT NOT NULL,\n            topics TEXT NOT NULL, created TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)', 'CREATE TABLE IF NOT EXISTS memory_exclusions (\n            owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, session TEXT NOT NULL, memory_id TEXT NOT NULL,\n            PRIMARY KEY(owner, session, memory_id))', 'CREATE TABLE IF NOT EXISTS memory_demo_seeds (owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE)', 'CREATE TABLE IF NOT EXISTS memory_case_edits(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, edited_at TEXT, revision INTEGER NOT NULL)', 'CREATE TABLE IF NOT EXISTS demo_memory_cases (\n            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, session TEXT NOT NULL,\n            patient TEXT NOT NULL, content TEXT NOT NULL, observations TEXT NOT NULL,\n            topics TEXT NOT NULL, created TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)', 'CREATE TABLE IF NOT EXISTS demo_memory_exclusions (\n            owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, session TEXT NOT NULL, memory_id TEXT NOT NULL,\n            PRIMARY KEY(owner, session, memory_id))', 'CREATE TABLE IF NOT EXISTS demo_memory_demo_seeds (owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE)', 'CREATE TABLE IF NOT EXISTS demo_memory_case_edits(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, edited_at TEXT, revision INTEGER NOT NULL)']
def upgrade():
    for sql in STATEMENTS: op.execute(sql)
def downgrade():
    for prefix in ['demo_memory_','memory_']:
        for name in ['case_edits','demo_seeds','exclusions','cases']: op.drop_table(prefix+name)
