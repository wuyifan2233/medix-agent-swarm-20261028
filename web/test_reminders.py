import os
os.environ.setdefault("MEDIX_WECHAT_DISABLE", "1")
os.environ.setdefault("MEDIX_QQ_DISABLE", "1")
import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from reminders.context import bind_identity
from reminders.schedule import SHANGHAI
from reminders.service import ReminderService, get_service, reset_service
from web.app import app


def at(year, month, day, hour, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=SHANGHAI)


class ReminderScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "reminders.sqlite")
        self.path_patch=patch("reminders.service.default_db_path",return_value=self.db)
        self.path_patch.start()
        reset_service()
        self.service = get_service()
        self.user = "web-" + "a" * 32
        self.session = self.user + "-chat"

    def tearDown(self):
        reset_service()
        self.path_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create(self, **kwargs):
        moment = kwargs.pop("now")
        return self.service.handle(self.user, self.session, action="create", now=moment, **kwargs)

    def test_next_fire_at_is_correct(self):
        moment = at(2026, 10, 29, 10, 0)
        daily = self.create(kind="medication", drug="阿司匹林", times="20:00,08:00", now=moment)
        self.assertTrue(daily["success"])
        self.assertEqual(daily["next_fire_at"], "2026-10-29 20:00")
        self.assertIn("现在该服用阿司匹林。", daily["canonical_text"])
        self.assertNotIn("100", daily["canonical_text"])

        dosed = self.create(kind="medication", drug="阿司匹林", dose="100mg", repeat="once",
                            fire_at="2026-10-30T09:30:00+08:00", now=moment)
        self.assertEqual(dosed["next_fire_at"], "2026-10-30 09:30")
        self.assertIn("现在该服用阿司匹林100mg。", dosed["canonical_text"])

        visit = self.create(kind="visit", fire_at="11-05 09:30", location="心内科", now=moment)
        self.assertEqual(visit["next_fire_at"], "2026-11-05 09:30")
        self.assertIn("你预约的心内科就诊时间是 2026-11-05 09:30", visit["canonical_text"])

        followup = self.create(kind="followup", fire_at="下周三 09:00", location="心内科", now=moment)
        self.assertEqual(followup["next_fire_at"], "2026-11-04 09:00")
        self.assertIn("2026-11-04 09:00心内科", followup["canonical_text"])

        tomorrow = self.create(kind="medication", drug="维生素C", fire_at="明天 08:00", now=moment)
        self.assertEqual(tomorrow["next_fire_at"], "2026-10-30 08:00")

    def test_vague_or_incomplete_time_is_not_stored(self):
        moment = at(2026, 10, 29, 10, 0)
        before = self.service.store.count_reminders()
        cases = [
            {"kind": "visit", "fire_at": "有空再去", "location": "内科"},
            {"kind": "medication", "drug": "阿司匹林", "repeat": "daily", "times": "早晚"},
            {"kind": "medication", "repeat": "daily", "times": "08:00"},
            {"kind": "visit", "note": "我胸痛，帮我记一下"},
            {"kind": "medication", "drug": "维生素C", "fire_at": "2020-01-01T08:00:00+08:00"},
        ]
        for case in cases:
            result = self.create(now=moment, **case)
            self.assertFalse(result["success"], case)
            self.assertNotIn("reminder_id", result)
        self.assertEqual(self.service.store.count_reminders(), before)

    def test_periodic_fire_advances_next_time(self):
        created = self.create(kind="medication", drug="阿司匹林", times="08:00,20:00", now=at(2026, 10, 29, 7, 0))
        self.service.sync(now=at(2026, 10, 29, 8, 0, 10))
        row = self.service.store.get(created["reminder_id"])
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["next_fire_at"][:16], "2026-10-29T20:00")
        self.assertIn("20:00", row["canonical_text"])
        self.assertEqual(self.service.store.count_deliveries(created["reminder_id"]), 1)
        delivery = self.service.store.unread_for_user(self.user)[0]
        self.assertIn("2026-10-29 08:00", delivery["canonical_text"])
        self.assertNotIn("补发", delivery["canonical_text"])

    def test_idempotent_delivery(self):
        created = self.create(kind="medication", drug="维生素C", times="08:00", now=at(2026, 10, 29, 7, 0))
        row = self.service.store.get(created["reminder_id"])
        payload = {"user_id": self.user, "session_id": self.session, "reminder_id": row["id"],
                   "scheduled_fire_at": row["next_fire_at"], "canonical_text": row["canonical_text"],
                   "delivered_at": row["next_fire_at"]}
        self.assertTrue(self.service.store.add_delivery(**payload))
        self.assertFalse(self.service.store.add_delivery(**payload))
        self.service.sync(now=at(2026, 10, 29, 8, 0, 5))
        self.assertEqual(self.service.store.count_deliveries(row["id"]), 1)
        self.assertGreater(self.service.store.get(row["id"])["next_fire_at"], row["next_fire_at"])

    def test_misfire_delivers_once(self):
        created = self.create(kind="medication", drug="阿司匹林", times="08:00,20:00", now=at(2026, 10, 26, 7, 0))
        later = at(2026, 10, 29, 10, 0)
        self.service.sync(now=later)
        self.service.sync(now=later)
        self.assertEqual(self.service.store.count_deliveries(created["reminder_id"]), 1)
        delivery = self.service.store.unread_for_user(self.user)[0]
        self.assertIn("原定时间 2026-10-26 08:00", delivery["canonical_text"])
        self.assertIn("补发", delivery["canonical_text"])
        row = self.service.store.get(created["reminder_id"])
        self.assertEqual(row["next_fire_at"][:16], "2026-10-29T20:00")
        self.assertEqual(row["status"], "active")

    def test_jobs_survive_restart(self):
        self.service.start(sync_seconds=3600)
        created = self.service.handle(
            self.user, self.session, action="create", kind="visit", fire_at="2030-01-02T09:00:00+08:00",
            location="口腔科")
        self.assertIsNotNone(self.service.scheduler.get_job(created["reminder_id"]))
        self.service.stop()
        restored = ReminderService(self.db)
        restored.start(sync_seconds=3600)
        try:
            self.assertIsNotNone(restored.scheduler.get_job(created["reminder_id"]))
            self.assertEqual(restored.store.get(created["reminder_id"])["status"], "active")
        finally:
            restored.stop()

    def test_scheduler_fires_without_waiting_for_the_clock(self):
        self.service.start(sync_seconds=3600)
        from datetime import timedelta
        import time
        moment = datetime.now(SHANGHAI)
        created = self.service.handle(
            self.user, self.session, action="create", kind="medication", drug="维生素C", repeat="once",
            fire_at=(moment + timedelta(seconds=1)).isoformat(), now=moment)
        self.assertTrue(created["success"])
        for _ in range(40):
            if self.service.store.count_deliveries(created["reminder_id"]):
                break
            time.sleep(0.1)
        self.assertEqual(self.service.store.count_deliveries(created["reminder_id"]), 1)
        self.assertEqual(self.service.store.get(created["reminder_id"])["status"], "completed")


class ReminderWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path_patch=patch("reminders.service.default_db_path",return_value=os.path.join(self.tmp,"reminders.sqlite"))
        self.path_patch.start()
        reset_service()
        self.service = get_service()

    def tearDown(self):
        reset_service()
        self.path_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_other_account_cannot_read_or_cancel(self):
        from storage.test_support import account_clients
        with account_clients() as accounts:
            alice, bob = accounts.clients
            owner=accounts.users[0].id
            created=self.service.handle(owner,owner+'-chat',action='create',kind='medication',drug='维生素C',repeat='once',fire_at='2030-01-02T09:00:00+08:00')
            self.assertTrue(created['success'])
            hidden=bob.get('/api/reminders')
            self.assertEqual(hidden.status_code,200)
            self.assertEqual(hidden.json()['upcoming'],[])
            self.assertEqual(bob.post('/api/reminders/'+created['reminder_id']+'/cancel',json={}).status_code,404)
            self.assertEqual(len(alice.get('/api/reminders').json()['upcoming']),1)

    def test_anonymous_cannot_read_reminders(self):
        self.assertEqual(TestClient(app).get('/api/reminders').status_code,401)

    def test_frontmatter_parameters_override_the_signature(self):
        from agents.skill_registry_mixin import SkillRegistryMixin, parameters_from_frontmatter
        from core.skill_loader import parse_skill_md
        path = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "scheduled-reminder" / "SKILL.md"
        metadata = parse_skill_md(path)
        params = {item.name: item for item in parameters_from_frontmatter(metadata)}
        self.assertEqual(params["action"].enum, ["create", "list", "update", "cancel"])
        self.assertTrue(params["action"].required)
        self.assertIn("medication", params["kind"].enum)
        self.assertNotIn("user_id", params)
        self.assertNotIn("session_id", params)

        def dummy(action, session_id="model-supplied"):
            return session_id

        inferred = SkillRegistryMixin._infer_skill_parameters(None, {"function": dummy, "metadata": metadata})
        self.assertEqual(inferred[0].enum, ["create", "list", "update", "cancel"])
        self.assertTrue(all(item.name != "session_id" for item in inferred))

    def test_prompt_and_route_keep_reminders_on_the_consultation_agent(self):
        prompt = Path(__file__).resolve().parents[1].joinpath("agents", "consultation_agent.py").read_text(encoding="utf-8")
        route = Path(__file__).resolve().parents[1].joinpath("swarm", "lead_agent.py").read_text(encoding="utf-8")
        self.assertIn("scheduled_reminder", prompt)
        self.assertIn("Asia/Shanghai", prompt)
        self.assertIn("可用 Skills（10个）", prompt)
        self.assertIn("定时提醒", route)
        self.assertIn("不要把这类日程交给 DiagnosticAgent", route)



if __name__ == "__main__":
    unittest.main()
