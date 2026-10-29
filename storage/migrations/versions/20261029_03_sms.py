"""Optional bound phone identities and single-use SMS challenges."""
from alembic import op
import sqlalchemy as sa

revision = "20261029_03"
down_revision = "20261029_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("phone_number", sa.String(11), nullable=True))
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
    op.create_table("sms_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("phone_number", sa.String(11), nullable=False),
        sa.Column("purpose", sa.String(8), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("scheme", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table("sms_challenges")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_phone_number")
        batch.drop_column("phone_number")
