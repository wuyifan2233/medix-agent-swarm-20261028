"""Use one public and login username; preserve user IDs."""
from alembic import op
import sqlalchemy as sa
import uuid
revision="20261029_05"
down_revision="20261029_04"
branch_labels=None
depends_on=None

def upgrade():
    conn=op.get_bind()
    rows=conn.execute(sa.text("SELECT id, username, phone_number FROM users")).mappings().all()
    used={r['username'] for r in rows}
    for row in rows:
        name=row['username']
        if name.startswith('sms_') and len(name)==28:
            candidate='用户'+(row['phone_number'][-4:] if row['phone_number'] else row['id'][:6])
            while candidate in used:
                candidate='用户_'+uuid.uuid4().hex[:10]
            used.add(candidate);name=candidate
        conn.execute(sa.text("UPDATE users SET username=:name, display_name=:name WHERE id=:id"),{'name':name,'id':row['id']})

def downgrade():
    pass
