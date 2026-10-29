import time
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from personalization.models import HealthProfile
from personalization.schemas import ProfileData

# Product review interval, not a statement of clinical validity.
REVIEW_SECONDS = 90 * 86400


def public(row):
    if row is None:
        return dict(data=ProfileData().model_dump(), revision=0, updated_at=None,
                    confirmed_at=None, status="empty", usable=False)
    status = "draft" if row.confirmed_at is None else (
        "review_required" if time.time() - row.confirmed_at > REVIEW_SECONDS else "confirmed")
    return dict(data=row.profile_data, revision=row.revision, updated_at=row.updated_at,
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
        now = time.time()
        with self.sessions() as db:
            if command.expected_revision == 0:
                db.add(HealthProfile(user_id=user_id, profile_data=command.data.model_dump(),
                                    revision=1, updated_at=now, confirmed_at=None))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    conflict()
            else:
                result = db.execute(update(HealthProfile).where(
                    HealthProfile.user_id == user_id, HealthProfile.revision == command.expected_revision
                ).values(profile_data=command.data.model_dump(), revision=command.expected_revision + 1,
                         updated_at=now, confirmed_at=None))
                if result.rowcount != 1:
                    conflict()
                db.commit()
            return public(db.get(HealthProfile, user_id))

    def confirm(self, user_id, revision):
        with self.sessions() as db:
            result = db.execute(update(HealthProfile).where(
                HealthProfile.user_id == user_id, HealthProfile.revision == revision
            ).values(confirmed_at=time.time()))
            if result.rowcount != 1:
                conflict()
            db.commit()
            return public(db.get(HealthProfile, user_id))

    def delete(self, user_id, revision):
        # Keep a blank tombstone and monotonic revision to invalidate old requests.
        from personalization.schemas import SaveProfile
        return self.save(user_id, SaveProfile(expected_revision=revision, data=ProfileData()))

    def snapshot(self, user_id, revision):
        result = self.load(user_id)
        if result["revision"] != revision or not result["usable"]:
            raise HTTPException(409, "请重新加载并主动确认档案，再选择本次使用。")
        return result
