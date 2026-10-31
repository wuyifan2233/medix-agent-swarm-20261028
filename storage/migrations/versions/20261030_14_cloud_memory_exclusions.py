"""Account-scoped suppression of cloud source sessions."""
from alembic import op

revision = '20261030_14'
down_revision = '20261030_13'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE TABLE IF NOT EXISTS mem0_exclusions('
               'owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,'
               'session TEXT NOT NULL,source_session TEXT NOT NULL,'
               'PRIMARY KEY(owner,session,source_session))')


def downgrade():
    op.drop_table('mem0_exclusions')
