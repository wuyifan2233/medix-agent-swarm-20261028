"""Account-owned conversations, resumable events and provider usage."""
from alembic import op

revision = '20261031_15'
down_revision = '20261030_14'
branch_labels = depends_on = None


def upgrade():
    op.execute('''CREATE TABLE chat_sessions (
        owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        id TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        PRIMARY KEY(owner,id))''')
    op.execute('''CREATE TABLE chat_turns (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, chat_id TEXT NOT NULL,
        request_id TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
        result TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
        UNIQUE(owner,request_id),
        FOREIGN KEY(owner,chat_id) REFERENCES chat_sessions(owner,id) ON DELETE CASCADE)''')
    op.execute('CREATE INDEX chat_turns_session ON chat_turns(owner,chat_id,created)')
    op.execute('''CREATE TABLE chat_events (
        turn_id TEXT NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(turn_id,seq))''')
    op.execute('''CREATE TABLE chat_contexts (
        owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(owner,key))''')
    op.execute('''CREATE TABLE model_usage (
        id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
        agent TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
        input_tokens INTEGER, output_tokens INTEGER, cache_hit_tokens INTEGER,
        usage_known INTEGER NOT NULL DEFAULT 0, cost TEXT, price TEXT NOT NULL,
        created REAL NOT NULL, updated REAL NOT NULL)''')


def downgrade():
    for table in ('model_usage','chat_contexts','chat_events','chat_turns','chat_sessions'):
        op.drop_table(table)
