from alembic import op
import sqlalchemy as sa
revision='20261031_05'
down_revision='20261030_04'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('registration_profiles',sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),sa.Column('data',sa.JSON(),nullable=False),sa.Column('recorded_at',sa.Float(),nullable=False))

def downgrade():op.drop_table('registration_profiles')
