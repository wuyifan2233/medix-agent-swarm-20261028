"""Track optional passwords on SMS accounts."""
from alembic import op
import sqlalchemy as sa
revision = "20261029_04"
down_revision = "20261029_03"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("has_password", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Earlier SMS accounts used generated sms_<24 hex> usernames and random passwords.
    op.execute("UPDATE users SET has_password = 0 WHERE length(username) = 28 AND substr(username,1,4) = 'sms_' AND display_name LIKE '用户%' AND phone_number IS NOT NULL")

def downgrade():
    op.drop_column("users", "has_password")
