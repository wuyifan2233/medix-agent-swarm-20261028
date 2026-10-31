"""Account-scoped answer presentation preferences, separate from health facts."""
from alembic import op
import sqlalchemy as sa
revision='20261030_10'
down_revision='20261030_09'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('reply_preferences',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('data',sa.JSON(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('updated_at',sa.Float(),nullable=False))

def downgrade():
    op.drop_table('reply_preferences')
