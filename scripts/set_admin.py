"""Promote an existing local account; never create passwords or print phone numbers."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, update
from auth.models import User, AuthSession
from auth.settings import AuthSettings
from storage.database import make_database
from storage.migrate import upgrade_database
import time

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phone',required=True,help='Exact registered phone number')
    args=parser.parse_args()
    settings=AuthSettings.from_env();upgrade_database(settings.database_url)
    engine,sessions=make_database(settings.database_url)
    try:
        with sessions() as db:
            user=db.scalar(select(User).where(User.phone_number==args.phone))
            if not user or not user.is_active:
                raise SystemExit('Active registered account not found')
            user.role='admin';user.updated_at=time.time()
            db.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=time.time()))
            db.commit()
            print('Administrator configured. Sign in again. User ID:',user.id)
    finally:
        engine.dispose()

if __name__=='__main__':main()
