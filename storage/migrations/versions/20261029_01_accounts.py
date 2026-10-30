"""Accounts, revocable login sessions and shared rate limits."""
from alembic import op
import sqlalchemy as sa

revision = "20261029_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"))
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("last_seen_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("revoked_at", sa.Float(), nullable=True))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("auth_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bucket", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False))
    op.create_index("ix_auth_attempt_bucket_time", "auth_attempts", ["bucket", "created_at"])


def downgrade():
    op.drop_table("auth_attempts")
    op.drop_table("auth_sessions")
    op.drop_table("users")
