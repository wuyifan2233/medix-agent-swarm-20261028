import time
from fastapi import HTTPException
from sqlalchemy import update, select, delete
from sqlalchemy.exc import IntegrityError
from personalization.models import HealthProfile, ProfileRevision, ProfileImport
from personalization.schemas import ProfileData

# Product review interval, not a statement of clinical validity.
REVIEW_SECONDS = 90 * 86400


def public(row):
    if row is None:
        return dict(data=ProfileData().model_dump(), revision=0, updated_at=None,
                    confirmed_at=None, status="empty", usable=False)
    status = "draft" if row.confirmed_at is None else (
        "review_required" if time.time() - row.confirmed_at > REVIEW_SECONDS else "confirmed")
    return dict(data=ProfileData.model_validate(row.profile_data).model_dump(mode='json'), revision=row.revision, updated_at=row.updated_at,
                confirmed_at=row.confirmed_at, status=status, usable=status == "confirmed")


def conflict():
    raise HTTPException(409, "档案版本已变化，请重新加载并核对后再操作。")


class ProfileStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def load(self, user_id):
        with self.sessions() as db:
            return public(db.get(HealthProfile, user_id))

    def save(self, user_id, command):
        with self.sessions() as db:
            self.write(db, user_id, command.data, command.expected_revision)
            db.commit()
            return public(db.get(HealthProfile, user_id))

    def write(self, db, user_id, data, expected_revision, action='edit'):
        now = time.time()
        values = data.model_dump(mode='json')
        if expected_revision == 0:
            db.add(HealthProfile(user_id=user_id, profile_data=values,
                                revision=1, updated_at=now, confirmed_at=None))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                conflict()
        else:
            result = db.execute(update(HealthProfile).where(
                HealthProfile.user_id == user_id, HealthProfile.revision == expected_revision
            ).values(profile_data=values, revision=expected_revision + 1,
                     updated_at=now, confirmed_at=None))
            if result.rowcount != 1:
                conflict()
        db.add(ProfileRevision(user_id=user_id, revision=expected_revision + 1,
                               profile_data=values, saved_at=now, confirmed_at=None, action=action))
        db.flush()

    def confirm(self, user_id, revision):
        with self.sessions() as db:
            now = time.time()
            result = db.execute(update(HealthProfile).where(
                HealthProfile.user_id == user_id, HealthProfile.revision == revision
            ).values(confirmed_at=now))
            if result.rowcount != 1:
                conflict()
            db.execute(update(ProfileRevision).where(ProfileRevision.user_id==user_id,
                       ProfileRevision.revision==revision).values(confirmed_at=now))
            db.commit()
            return public(db.get(HealthProfile, user_id))

    def delete(self, user_id, revision):
        # Keep a blank tombstone and monotonic revision to invalidate old requests.
        with self.sessions() as db:
            self.write(db,user_id,ProfileData(),revision,action='clear')
            db.execute(delete(ProfileRevision).where(ProfileRevision.user_id==user_id,
                       ProfileRevision.revision<=revision))
            db.execute(delete(ProfileImport).where(ProfileImport.user_id==user_id))
            db.commit()
            return public(db.get(HealthProfile,user_id))

    def history(self, user_id):
        with self.sessions() as db:
            rows=db.scalars(select(ProfileRevision).where(ProfileRevision.user_id==user_id)
                            .order_by(ProfileRevision.revision.desc()).limit(50)).all()
            return [dict(revision=row.revision, data=ProfileData.model_validate(row.profile_data).model_dump(mode='json'),
                         saved_at=row.saved_at, confirmed_at=row.confirmed_at, action=row.action) for row in rows]

    def restore(self,user_id,command):
        with self.sessions() as db:
            target=db.get(ProfileRevision,(user_id,command.target_revision))
            if target is None:
                raise HTTPException(404,'未找到本账号的档案版本。')
            self.write(db,user_id,ProfileData.model_validate(target.profile_data),command.expected_revision,action='restore')
            db.commit()
            return public(db.get(HealthProfile,user_id))

    def snapshot(self, user_id, revision):
        result = self.load(user_id)
        if result["revision"] != revision or not result["usable"]:
            raise HTTPException(409, "请重新加载并主动确认档案，再选择本次使用。")
        return result
