"""Local per-user avatar, with existing accounts retaining their default avatar."""
from alembic import op
import sqlalchemy as sa

revision = "20261029_02"
down_revision = "20261029_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_data", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("users", "avatar_data")
