"""Profile history and temporary report candidates."""
from alembic import op
import sqlalchemy as sa

revision = '20261030_09'
down_revision = '20261030_08'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('health_profile_revisions',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('revision',sa.Integer(),primary_key=True),
        sa.Column('profile_data',sa.JSON(),nullable=False),
        sa.Column('saved_at',sa.Float(),nullable=False),
        sa.Column('confirmed_at',sa.Float(),nullable=True),
        sa.Column('action',sa.String(20),nullable=False))
    op.execute('INSERT INTO health_profile_revisions (user_id,revision,profile_data,saved_at,confirmed_at,action) SELECT user_id,revision,profile_data,updated_at,confirmed_at,\'baseline\' FROM health_profiles')
    op.create_table('health_profile_imports',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('base_revision',sa.Integer(),nullable=False),
        sa.Column('candidates',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.Float(),nullable=False),
        sa.Column('expires_at',sa.Float(),nullable=False),
        sa.Column('consumed',sa.Boolean(),nullable=False))
    op.create_index('ix_health_profile_imports_user_id','health_profile_imports',['user_id'])


def downgrade():
    op.drop_table('health_profile_imports')
    op.drop_table('health_profile_revisions')
