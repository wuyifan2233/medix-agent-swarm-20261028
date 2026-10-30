"""Confirmed health profiles, isolated by the existing account ID."""
from alembic import op
import sqlalchemy as sa

revision = "20261030_08"
down_revision = "20261029_07"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("health_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile_data", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("confirmed_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_table("health_profiles")
