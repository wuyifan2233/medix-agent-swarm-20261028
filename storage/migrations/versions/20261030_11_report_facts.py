"""Report facts and revisions share the account database."""
from alembic import op
revision = '20261030_11'
down_revision = '20261030_10'
branch_labels = None
depends_on = None
SCHEMA = '\n        CREATE TABLE IF NOT EXISTS report_cases(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,created TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS report_bindings(owner TEXT REFERENCES users(id) ON DELETE CASCADE,chat_id TEXT,case_id TEXT,PRIMARY KEY(owner,chat_id));\n        CREATE TABLE IF NOT EXISTS report_facts(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,case_id TEXT NOT NULL,revision INTEGER NOT NULL,\n          data TEXT NOT NULL,source TEXT NOT NULL,quote TEXT NOT NULL,updated TEXT NOT NULL,dirty INTEGER NOT NULL DEFAULT 1);\n        CREATE TABLE IF NOT EXISTS report_versions(fact_id TEXT,revision INTEGER,data TEXT,source TEXT,quote TEXT,created TEXT,\n          PRIMARY KEY(fact_id,revision));\n        CREATE TABLE IF NOT EXISTS report_turns(owner TEXT REFERENCES users(id) ON DELETE CASCADE,request_id TEXT,case_id TEXT,outcome TEXT,PRIMARY KEY(owner,request_id));\n        CREATE TABLE IF NOT EXISTS report_analyses(id TEXT PRIMARY KEY,owner TEXT REFERENCES users(id) ON DELETE CASCADE,case_id TEXT,refs TEXT,answer TEXT,created TEXT);\n        CREATE INDEX IF NOT EXISTS facts_case ON report_facts(owner,case_id);\n        '

def upgrade():
    for statement in SCHEMA.split(';'):
        if statement.strip(): op.execute(statement)

def downgrade():
    for name in ['report_analyses','report_turns','report_versions','report_facts','report_bindings','report_cases']:
        op.drop_table(name)
