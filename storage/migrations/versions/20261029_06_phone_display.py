"""Separate display name from phone login identity."""
from alembic import op
revision="20261029_06"
down_revision="20261029_05"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("UPDATE users SET display_name = 'MediX ' || username WHERE phone_number IS NOT NULL AND substr(username,1,2) = '用户'")

def downgrade():
    pass
