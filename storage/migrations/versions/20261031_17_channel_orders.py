"""Channel accounting and recharge orders with payment intentionally disabled."""
from alembic import op

revision = '20261031_17'
down_revision = '20261031_16'
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE chat_sessions ADD COLUMN channel TEXT NOT NULL DEFAULT 'web'")
    op.execute("ALTER TABLE care_ledger ADD COLUMN channel TEXT NOT NULL DEFAULT 'web'")
    op.execute('''CREATE TABLE care_orders (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, plan_id TEXT NOT NULL, points INTEGER NOT NULL CHECK(points>0),
        amount_fen INTEGER NOT NULL CHECK(amount_fen>0), currency TEXT NOT NULL DEFAULT 'CNY',
        status TEXT NOT NULL CHECK(status IN ('awaiting_payment','cancelled','expired')),
        created REAL NOT NULL, expires REAL NOT NULL, updated REAL NOT NULL,
        UNIQUE(owner,request_id))''')
    op.execute('CREATE INDEX care_orders_owner ON care_orders(owner,created)')


def downgrade():
    op.drop_table('care_orders')
    op.drop_column('care_ledger', 'channel')
    op.drop_column('chat_sessions', 'channel')
