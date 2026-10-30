"""Short randomized default nicknames; retain customized names and identities."""
from alembic import op
import sqlalchemy as sa
import secrets
import string
revision="20261029_07"
down_revision="20261029_06"
branch_labels=None
depends_on=None

def upgrade():
    conn=op.get_bind()
    rows=conn.execute(sa.text("SELECT id, username, display_name FROM users")).mappings().all()
    used={r['display_name'] for r in rows}
    for row in rows:
        if row['display_name'] != 'MediX '+row['username'] or not row['username'].startswith('用户'):
            continue
        while True:
            name='用户_'+''.join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(4))
            if name not in used:break
        used.add(name)
        conn.execute(sa.text("UPDATE users SET display_name=:name WHERE id=:id"),{'name':name,'id':row['id']})

def downgrade():
    pass
