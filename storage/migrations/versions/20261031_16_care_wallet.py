"""Account credit ledger, independent of deletable conversation history."""
from alembic import op
revision='20261031_16'
down_revision='20261031_15'
branch_labels=depends_on=None

def upgrade():
    op.execute('''CREATE TABLE care_wallets (
        owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        balance INTEGER NOT NULL CHECK(balance>=0), initial INTEGER NOT NULL,
        units_per_cny INTEGER NOT NULL, created REAL NOT NULL)''')
    op.execute('''CREATE TABLE care_ledger (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES care_wallets(owner) ON DELETE CASCADE,
        turn_id TEXT, kind TEXT NOT NULL, amount INTEGER NOT NULL,
        reserved INTEGER NOT NULL DEFAULT 0, cost_cny TEXT, created REAL NOT NULL)''')
    op.execute('CREATE INDEX care_ledger_owner ON care_ledger(owner,created)')

def downgrade():
    op.drop_table('care_ledger');op.drop_table('care_wallets')
