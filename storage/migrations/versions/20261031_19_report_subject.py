"""Keep report history scoped to an account and a confirmed person."""
from alembic import op
import sqlalchemy as sa
revision = '20261031_19'
down_revision = '20261031_18'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('report_cases', sa.Column('subject', sa.String(16), nullable=False, server_default='unknown'))
    op.create_index('report_cases_owner_subject', 'report_cases', ['owner', 'subject'])

def downgrade():
    op.drop_index('report_cases_owner_subject', table_name='report_cases')
    op.drop_column('report_cases', 'subject')
