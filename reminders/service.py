"""Validate reminders, persist them, and keep APScheduler aligned with SQLite."""
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from .schedule import (
    Clarification, KIND_LABELS, SHANGHAI, asks_emergency, canonical_text, catch_up_text,
    clean_text, display_local, format_times, iso_local, next_occurrence, now_shanghai,
    parse_fire_at, parse_times, parse_weekdays,
)
from .store import ReminderStore

ROOT = Path(__file__).resolve().parents[1]
SYNC_JOB = "medix-reminder-sync"
MISFIRE_GRACE_SECONDS = 60 * 60


def default_db_path():
    return None  # Production uses the shared account database; tests inject explicit paths.


def _clarify(question):
    return {"success": False, "needs_clarification": True, "question": question}


class ReminderService:
    def __init__(self, path=None):
        from storage.business import database_url
        self._explicit_path = path
        self.db_path = str(path) if path else database_url()
        self.store = ReminderStore(path)
        self.scheduler = None

    def start(self, sync_seconds=30):
        if self.scheduler is not None:
            return
        if self.store.conn is None:
            self.store = ReminderStore(self._explicit_path)
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(
            timezone=SHANGHAI,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": MISFIRE_GRACE_SECONDS})
        scheduler.add_job(self.sync, "interval", seconds=sync_seconds, id=SYNC_JOB,
                          replace_existing=True, coalesce=True, max_instances=1)
        scheduler.start()
        self.scheduler = scheduler
        self.sync()

    def stop(self):
        scheduler = self.scheduler
        self.scheduler = None
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        self.store.close()

    def handle(self, user_id, session_id, *, action, kind=None, repeat=None, fire_at=None, times=None,
               weekdays=None, drug=None, dose=None, location=None, note=None, reminder_id=None, now=None):
        action = clean_text(action).lower()
        moment = now_shanghai(now)
        if action == "list":
            return self._list(user_id)
        if action == "cancel":
            return self._cancel(user_id, clean_text(reminder_id))
        if action == "update":
            return self._update(user_id, clean_text(reminder_id), kind, repeat, fire_at, times, weekdays,
                                drug, dose, location, note, moment)
        if action == "create":
            return self._create(user_id, session_id, kind, repeat, fire_at, times, weekdays, drug, dose,
                                location, note, moment)
        return _clarify("请说明是要创建、查看、修改还是取消提醒。")

    def snapshot(self, user_id):
        upcoming = []
        for row in self.store.active_for_user(user_id):
            upcoming.append({"id": row["id"], "kind": row["kind"], "label": KIND_LABELS[row["kind"]],
                             "next_fire_at": display_local(datetime.fromisoformat(row["next_fire_at"])),
                             "repeat": row["repeat"], "session_id": row["session_id"]})
        unread = []
        for row in self.store.unread_for_user(user_id):
            unread.append({"id": row["id"], "reminder_id": row["reminder_id"], "kind": row["kind"],
                           "label": KIND_LABELS[row["kind"]], "canonical_text": row["canonical_text"],
                           "session_id": row["session_id"],
                           "scheduled_fire_at": display_local(datetime.fromisoformat(row["scheduled_fire_at"]))})
        return {"upcoming": upcoming, "unread": unread}

    def mark_read(self, user_id, delivery_ids):
        safe = [item for item in delivery_ids if isinstance(item, int)]
        self.store.mark_read(user_id, safe)

    def cancel(self, user_id, reminder_id):
        result = self._cancel(user_id, reminder_id)
        return bool(result.get("success"))

    def sync(self, now=None):
        moment = now_shanghai(now)
        with self.store.lock:
            for row in self.store.active_rows():
                due = datetime.fromisoformat(row["next_fire_at"])
                if due <= moment:
                    self._settle_locked(row["id"], moment)
                else:
                    self._arm_locked(row["id"], due)
            active_ids = {row["id"] for row in self.store.active_rows()}
            self._drop_inactive_jobs_locked(active_ids)

    def _create(self, user_id, session_id, kind, repeat, fire_at, times, weekdays, drug, dose, location, note, moment):
        built = self._build(kind, repeat, fire_at, times, weekdays, drug, dose, location, note, moment)
        if built.get("success") is False:
            return built
        reminder_id = uuid.uuid4().hex
        with self.store.lock:
            self.store.insert_reminder({
                "id": reminder_id, "user_id": user_id, "session_id": session_id, **built,
                "timezone": "Asia/Shanghai", "status": "active"})
            self._arm_locked(reminder_id, datetime.fromisoformat(built["next_fire_at"]))
        logger.info("Reminder created id={} kind={}", reminder_id, built["kind"])
        return self._success(reminder_id, built["next_fire_at"], built["canonical_text"])

    def _update(self, user_id, reminder_id, kind, repeat, fire_at, times, weekdays, drug, dose, location, note, moment):
        if not reminder_id:
            return _clarify("修改提醒需要先查看列表，并使用返回的 reminder_id。")
        current = self.store.get_for_user(reminder_id, user_id)
        if not current:
            return _clarify("没有找到这个提醒编号。请先查看当前提醒列表，再用返回的 reminder_id 修改。")
        if not any(clean_text(value) for value in (kind, repeat, fire_at, times, weekdays, drug, dose, location, note)):
            return _clarify("请告诉我要改的时间或内容。")
        built = self._build(
            kind or current["kind"],
            repeat or current["repeat"],
            fire_at if clean_text(fire_at) else (current["schedule"] if current["repeat"] == "once" else None),
            times if clean_text(times) else (current["schedule"] if current["repeat"] == "daily" else None),
            weekdays if clean_text(weekdays) else (current["schedule"].split("@", 1)[0] if current["repeat"] == "weekly" else None),
            drug if clean_text(drug) else current["drug"],
            dose if dose is not None and clean_text(dose) else current["dose"],
            location if location is not None and clean_text(location) else current["location"],
            note if note is not None and clean_text(note) else current["note"],
            moment,
            weekly_times=current["schedule"].split("@", 1)[1] if current["repeat"] == "weekly" and not clean_text(times) else None)
        if built.get("success") is False:
            return built
        with self.store.lock:
            self.store.save_state(
                reminder_id, status="active", next_fire_at=built["next_fire_at"], canonical_text=built["canonical_text"],
                schedule=built["schedule"], repeat=built["repeat"], kind=built["kind"], drug=built["drug"],
                dose=built["dose"], location=built["location"], note=built["note"])
            self._arm_locked(reminder_id, datetime.fromisoformat(built["next_fire_at"]))
        return self._success(reminder_id, built["next_fire_at"], built["canonical_text"])

    def _cancel(self, user_id, reminder_id):
        if not reminder_id:
            return _clarify("取消提醒需要先查看列表，并使用返回的 reminder_id。")
        current = self.store.get_for_user(reminder_id, user_id)
        if not current or current["status"] in {"cancelled", "completed"}:
            return _clarify("没有找到这个提醒编号。请先查看当前提醒列表，再用返回的 reminder_id 取消。")
        with self.store.lock:
            self.store.save_state(reminder_id, status="cancelled", next_fire_at=current["next_fire_at"],
                                   canonical_text=current["canonical_text"])
            self._disarm(reminder_id)
        return {"success": True, "reminder_id": reminder_id, "status": "cancelled"}

    def _list(self, user_id):
        reminders = []
        for row in self.store.active_for_user(user_id):
            reminders.append({
                "reminder_id": row["id"], "kind": row["kind"], "label": KIND_LABELS[row["kind"]],
                "repeat": row["repeat"], "next_fire_at": display_local(datetime.fromisoformat(row["next_fire_at"])),
                "timezone": row["timezone"], "canonical_text": row["canonical_text"], "status": row["status"]})
        return {"success": True, "reminders": reminders}

    def _build(self, kind, repeat, fire_at, times, weekdays, drug, dose, location, note, moment, weekly_times=None):
        kind = clean_text(kind).lower()
        repeat = clean_text(repeat).lower()
        drug = clean_text(drug)
        dose = clean_text(dose)
        location = clean_text(location)
        note = clean_text(note)
        if asks_emergency(drug, dose, location, note, fire_at, times, weekdays):
            return {"success": False, "needs_clarification": False, "emergency": True,
                    "question": "你描述的情况需要立即就医，不要等提醒。请马上联系急救或前往最近的急诊。这不是处方，也不能代替急诊处理。"}
        if kind not in KIND_LABELS:
            return _clarify("请说明这是用药、就诊还是复诊提醒。")
        if kind == "medication" and not drug:
            return _clarify("请告诉我要提醒服用的药品名称。没有说的剂量可以留空，我不会编造剂量。")
        if not repeat:
            if kind in {"visit", "followup"}:
                repeat = "once"
            elif clean_text(weekdays):
                repeat = "weekly"
            elif clean_text(times) and not clean_text(fire_at):
                repeat = "daily"
            elif clean_text(fire_at):
                repeat = "once"
        if repeat not in {"once", "daily", "weekly"}:
            return _clarify("请说明提醒是一次、每天，还是每周。")
        if repeat == "once":
            parsed = parse_fire_at(fire_at, moment)
            if isinstance(parsed, Clarification):
                return _clarify(parsed.question)
            schedule = iso_local(parsed)
            nxt = parsed
        elif repeat == "daily":
            parsed = parse_times(times)
            if isinstance(parsed, Clarification):
                return _clarify(parsed.question)
            schedule = format_times(parsed)
            nxt = next_occurrence("daily", schedule, moment)
        else:
            days = parse_weekdays(weekdays)
            if isinstance(days, Clarification):
                return _clarify(days.question)
            parsed_times = parse_times(times or weekly_times)
            if isinstance(parsed_times, Clarification):
                return _clarify(parsed_times.question)
            schedule = ",".join(str(day) for day in days) + "@" + format_times(parsed_times)
            nxt = next_occurrence("weekly", schedule, moment)
        if nxt is None or nxt <= moment:
            return _clarify("这个时间已经过去了。请给一个未来的时间。")
        return {"kind": kind, "repeat": repeat, "schedule": schedule, "next_fire_at": iso_local(nxt),
                "canonical_text": canonical_text(kind, nxt, drug, dose, location),
                "drug": drug, "dose": dose, "location": location, "note": note}

    def _settle_locked(self, reminder_id, moment):
        row = self.store.get(reminder_id)
        if not row or row["status"] != "active":
            return
        if self._explicit_path is None:
            account = self.store.conn.execute("SELECT is_active FROM users WHERE id=?", (row["user_id"],)).fetchone()
            if not account or not account["is_active"]:
                self._disarm(reminder_id)
                return
        scheduled = datetime.fromisoformat(row["next_fire_at"])
        if scheduled > moment:
            self._arm_locked(reminder_id, scheduled)
            return
        body = row["canonical_text"]
        if moment - scheduled > timedelta(minutes=2):
            body = catch_up_text(body, scheduled)
        self.store.add_delivery(
            user_id=row["user_id"], session_id=row["session_id"], reminder_id=reminder_id,
            scheduled_fire_at=iso_local(scheduled), canonical_text=body, delivered_at=iso_local(moment))
        if row["repeat"] == "once":
            self.store.save_state(reminder_id, status="completed", next_fire_at=iso_local(scheduled),
                                   canonical_text=row["canonical_text"])
            self._disarm(reminder_id)
            return
        late = moment - scheduled > timedelta(minutes=2)
        anchor = moment if late else scheduled
        nxt = next_occurrence(row["repeat"], row["schedule"], anchor)
        if nxt is None or nxt <= moment:
            nxt = next_occurrence(row["repeat"], row["schedule"], moment)
        if nxt is None:
            self.store.save_state(reminder_id, status="completed", next_fire_at=iso_local(scheduled),
                                   canonical_text=row["canonical_text"])
            self._disarm(reminder_id)
            return
        text = canonical_text(row["kind"], nxt, row["drug"], row["dose"], row["location"])
        self.store.save_state(reminder_id, status="active", next_fire_at=iso_local(nxt), canonical_text=text)
        self._arm_locked(reminder_id, nxt)

    def _arm_locked(self, reminder_id, when):
        if self.scheduler is None:
            return
        self.scheduler.add_job(
            self._on_fire, "date", run_date=when, args=[reminder_id], id=reminder_id,
            replace_existing=True, coalesce=True, max_instances=1, misfire_grace_time=MISFIRE_GRACE_SECONDS)

    def _disarm(self, reminder_id):
        if self.scheduler is None or reminder_id == SYNC_JOB:
            return
        try:
            if self.scheduler.get_job(reminder_id) is not None:
                self.scheduler.remove_job(reminder_id)
        except Exception:
            logger.debug("Reminder job already gone id={}", reminder_id)

    def _drop_inactive_jobs_locked(self, active_ids):
        if self.scheduler is None:
            return
        for job in list(self.scheduler.get_jobs()):
            if job.id != SYNC_JOB and job.id not in active_ids:
                self.scheduler.remove_job(job.id)

    def _on_fire(self, reminder_id):
        try:
            with self.store.lock:
                self._settle_locked(reminder_id, now_shanghai())
        except Exception:
            logger.exception("Reminder fire failed id={}", reminder_id)

    def _success(self, reminder_id, next_fire_at, text):
        return {"success": True, "reminder_id": reminder_id,
                "next_fire_at": display_local(datetime.fromisoformat(next_fire_at)),
                "timezone": "Asia/Shanghai", "canonical_text": text}


_service = None


def get_service():
    global _service
    from storage.business import database_url
    path = default_db_path()
    key = str(path) if path else database_url()
    if _service is None or _service.db_path != key:
        if _service is not None:
            _service.stop()
        _service = ReminderService(path)
    return _service


def reset_service():
    global _service
    if _service is not None:
        _service.stop()
        _service = None
