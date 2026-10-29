import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select, update, inspect

from auth.models import AuthSession, User
from auth.schemas import Registration
from auth.security import digest
from auth.service import AuthService
from auth.settings import AuthSettings
from storage.database import make_database
from storage.migrate import upgrade_database
from web.app import app, contexts, jobs

PASSWORD = "Test-Password2026!"
NEW_PASSWORD = "New-Password2026!"


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.url = "sqlite:///" + (Path(cls.temp.name) / "test.db").as_posix()
        upgrade_database(cls.url)
        upgrade_database(cls.url)  # idempotent upgrade
        cls.engine, cls.sessions = make_database(cls.url)
        cls.original_service = app.state.auth_service
        cls.settings = AuthSettings(cls.url, False, frozenset({"http://testserver"}), True, namespace="test")

    @classmethod
    def tearDownClass(cls):
        app.state.auth_service = cls.original_service
        cls.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.warmup_patch = patch("web.app.warmup")
        self.warmup_patch.start()
        with self.sessions() as db:
            from auth.models import AuthAttempt
            for model in [AuthAttempt, AuthSession, User]:
                db.query(model).delete()
            db.commit()
        app.state.auth_service = AuthService(self.sessions, self.settings)
        self.auth = app.state.auth_service
        jobs.clear(); contexts.clear()
        self.client = self.client_for()

    def tearDown(self):
        self.warmup_patch.stop()
        self.client.close()
        jobs.clear(); contexts.clear()

    def client_for(self):
        return TestClient(app, headers={"Origin": "http://testserver", "X-Medix-Request": "1"})

    def register(self, username="alice", role="user"):
        return self.auth.register(Registration(username=username, password=PASSWORD, display_name=username), role)

    def login(self, client=None, username="alice", password=PASSWORD):
        client = client or self.client
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response

    def test_migration_and_foreign_keys(self):
        self.assertIn("auth_attempts", inspect(self.engine).get_table_names())
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)

    def test_registration_normalizes_username_and_never_accepts_role(self):
        payload = {"username":"Alice", "password":PASSWORD, "display_name":"爱丽丝"}
        response = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["username"], "alice")
        self.assertNotIn("password_hash", response.json())
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 409)
        payload.update(username="mallory", role="admin")
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 422)

    def test_validation_does_not_echo_passwords(self):
        response = self.client.post("/api/auth/register", json={"username":"alice", "password":"short12", "display_name":"A"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("short12", response.text)

    def test_registration_defaults_display_name_to_username(self):
        response = self.client.post("/api/auth/register", json={"username":"Alice", "password":PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["display_name"], "alice")
        self.login()
        self.assertEqual(self.client.get("/api/auth/me").json()["display_name"], "alice")

    def test_new_password_length_and_composition(self):
        invalid = ["Aa1!aaa", "Aa1!" + "a" * 17, "abcdefgh", "ABCDEFGH", "12345678", "!!!!@@@@",
                   "abcd1234", "ABCD1234", "Abcdefgh", "abcd!!!!", "ABCD!!!!", "1234!!!!", "abcd123 "]
        for password in invalid:
            response = self.client.post("/api/auth/register", json={"username":"policy", "password":password})
            self.assertEqual(response.status_code, 422)
            self.assertIn("8–20", response.json()["detail"])
            self.assertNotIn(password, response.text)
        for index, password in enumerate(["Aa1!aaaa", "Aa1!" + "a" * 16,
                                          "Abcd1234", "abcd123!", "ABCD123!", "Abcdefg!"]):
            response = self.client.post("/api/auth/register", json={"username":f"valid_{index}", "password":password})
            self.assertEqual(response.status_code, 201, response.text)
        self.register(); self.login()
        for password in invalid:
            response = self.client.post("/api/auth/change-password", json={"current_password":PASSWORD, "new_password":password})
            self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/auth/change-password", json={"current_password":PASSWORD, "new_password":"Aa1!aaaa"})
        self.assertEqual(response.status_code, 204)
        self.login(password="Aa1!aaaa")

    def test_existing_long_password_can_still_log_in(self):
        from auth.security import passwords
        user = self.register()
        legacy = "a previously permitted long passphrase"
        with self.sessions() as db:
            db.get(User, user.id).password_hash = passwords.hash(legacy)
            db.commit()
        self.login(password=legacy)

    def test_registration_can_be_closed(self):
        from dataclasses import replace
        app.state.auth_service = AuthService(self.sessions, replace(self.settings, registration_enabled=False))
        self.assertEqual(self.client.post("/api/auth/register", json={"username":"alice", "password":PASSWORD, "display_name":"A"}).status_code, 403)

    def test_login_cookie_hash_and_current_user(self):
        user = self.register()
        response = self.login()
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie); self.assertIn("SameSite=lax", cookie)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], user.id)
        token = self.client.cookies.get(self.settings.cookie_name)
        with self.sessions() as db:
            record = db.scalar(select(AuthSession))
            self.assertEqual(record.token_hash, digest(token))
            self.assertNotEqual(record.token_hash, token)
            self.assertTrue(db.get(User, user.id).password_hash.startswith("$argon2id$"))

    def test_wrong_password_and_unknown_user_have_same_error(self):
        self.register()
        one = self.client.post("/api/auth/login", json={"username":"alice", "password":"wrong"})
        two = self.client.post("/api/auth/login", json={"username":"unknown", "password":"wrong"})
        self.assertEqual(one.status_code, 401); self.assertEqual(one.json(), two.json())

    def test_unauthenticated_and_forged_browser_cookie_rejected(self):
        self.client.cookies.set("medix_browser", "a" * 32)
        self.client.cookies.set(self.settings.cookie_name, "x" * 43)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/chat", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/jobs/anything").status_code, 401)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)
        response = self.client.get("/login", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?login=1")

    def test_csrf_all_writes_and_multitab_stability(self):
        self.register(); self.login()
        token = self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 403)
        self.client.headers["X-CSRF-Token"] = "x" * 64
        self.assertEqual(self.client.post("/api/chat", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/auth/csrf").json()["csrf_token"], token)
        self.assertEqual(self.client.get("/api/auth/csrf").json()["csrf_token"], token)
        self.client.headers["X-CSRF-Token"] = token
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 204)

    def test_origin_custom_header_and_content_type_required(self):
        payload = {"username":"alice", "password":PASSWORD}
        for headers in [{"Origin":"https://evil.example"}, {"Origin":""}, {"X-Medix-Request":""}, {"Content-Type":"text/plain"}]:
            self.assertEqual(self.client.post("/api/auth/login", json=payload, headers=headers).status_code, 403)

    def test_logout_revokes_old_cookie(self):
        self.register(); self.login()
        stolen = self.client.cookies.get(self.settings.cookie_name)
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 204)
        self.client.cookies.set(self.settings.cookie_name, stolen)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_login_replaces_previous_browser_session(self):
        self.register(); self.login()
        previous = self.client.cookies.get(self.settings.cookie_name)
        self.login()
        with self.client_for() as other:
            other.cookies.set(self.settings.cookie_name, previous)
            self.assertEqual(other.get("/api/auth/me").status_code, 401)

    def test_expired_idle_and_revoked_sessions(self):
        self.register()
        for changes in [{"expires_at":time.time()-1}, {"last_seen_at":time.time()-1801}, {"revoked_at":time.time()}]:
            self.login()
            with self.sessions() as db:
                db.execute(update(AuthSession).values(**changes)); db.commit()
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_logout_all_and_password_change_revoke_other_devices(self):
        self.register(); self.login()
        with self.client_for() as other:
            self.login(other)
            self.assertEqual(self.client.post("/api/auth/logout-all", json={}).status_code, 204)
            self.assertEqual(other.get("/api/auth/me").status_code, 401)
            self.login(); self.login(other)
            bad = self.client.post("/api/auth/change-password", json={"current_password":"wrong", "new_password":NEW_PASSWORD})
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(other.get("/api/auth/me").status_code, 200)
            response = self.client.post("/api/auth/change-password", json={"current_password":PASSWORD, "new_password":NEW_PASSWORD})
            self.assertEqual(response.status_code, 204)
            self.assertEqual(other.get("/api/auth/me").status_code, 401)
            self.login(password=NEW_PASSWORD)

    def test_admin_disable_reenable_and_no_admin_management(self):
        alice = self.register(); self.register("leader", "admin"); self.login()
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        with self.client_for() as admin:
            leader = self.login(admin, "leader").json()["user"]
            self.assertEqual(admin.get("/api/admin/users").json()["total"], 2)
            url = f"/api/admin/users/{alice.id}/status"
            self.assertEqual(admin.patch(url, json={"is_active":False}).status_code, 200)
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
            self.assertEqual(admin.patch(url, json={"is_active":True}).status_code, 200)
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
            self.assertEqual(admin.patch(f"/api/admin/users/{leader['id']}/status", json={"is_active":False}).status_code, 403)
        self.login()

    def test_login_rate_limit_and_expiry(self):
        payload = {"username":"unknown", "password":"wrong"}
        # Avoid repeated expensive password hashes; exercise the actual database limiter.
        for _ in range(10):
            self.auth.limit("login", "testclient", "unknown")
        self.assertEqual(self.client.post("/api/auth/login", json=payload).status_code, 429)
        with patch("auth.service.time.time", return_value=time.time()+901):
            self.auth.limit("login", "testclient", "unknown")

    def test_cross_user_jobs_and_context_namespace(self):
        alice = self.register(); self.register("bob"); self.login()
        chat_id = str(uuid.uuid4())
        with patch("web.app.executor.submit") as submit:
            response = self.client.post("/api/chat", json={"chat_id":chat_id, "message":"hello"})
            self.assertEqual(response.status_code, 202, response.text)
            job_id = response.json()["job_id"]
            self.assertEqual(submit.call_args.args[-2], f"web-{alice.id}-{chat_id}")
            self.assertEqual(submit.call_args.args[-1], f"medix:test:user:{alice.id}")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").status_code, 200)
        self.assertNotIn("owner_user_id", self.client.get(f"/api/jobs/{job_id}").json())
        with self.client_for() as other:
            self.login(other, "bob")
            self.assertEqual(other.get(f"/api/jobs/{job_id}").status_code, 404)
            with patch("web.app.executor.submit") as submit:
                other.post("/api/chat", json={"chat_id":chat_id, "message":"hello"})
                self.assertNotEqual(submit.call_args.args[-2], f"web-{alice.id}-{chat_id}")

    def test_production_cookie_and_security_headers(self):
        from dataclasses import replace
        app.state.auth_service = AuthService(self.sessions, replace(self.settings, production=True,
            origins=frozenset({"https://testserver"})))
        self.register()
        client = TestClient(app, base_url="https://testserver", headers={"Origin":"https://testserver", "X-Medix-Request":"1"})
        try:
            response = self.login(client)
            cookie = response.headers["set-cookie"]
            self.assertTrue(cookie.startswith("__Host-medix_session="))
            self.assertIn("Secure", cookie); self.assertNotIn("Domain=", cookie)
            self.assertEqual(response.headers["strict-transport-security"], "max-age=31536000")
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        finally:
            client.close()

    def test_auth_body_limit(self):
        response = self.client.post("/api/auth/login", content=b"x" * 17000, headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/api/auth/login", content=iter([b"x" * 9000, b"y" * 9000]),
                                    headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 413)

    def test_production_configuration_fails_closed(self):
        with patch.dict("os.environ", {"MEDIX_ENV":"production"}, clear=True):
            with self.assertRaises(ValueError):
                AuthSettings.from_env()
        with patch.dict("os.environ", {"MEDIX_ENV":"prod"}, clear=True):
            with self.assertRaises(ValueError):
                AuthSettings.from_env()

    def test_disabled_owner_does_not_start_queued_analysis(self):
        from web.app import run_job
        user = self.register()
        with self.sessions() as db:
            db.execute(update(User).where(User.id == user.id).values(is_active=False)); db.commit()
        job = {"owner_user_id":user.id}
        with patch("web.app.analyze") as analyze:
            run_job(job, {}, "session", "memory-user")
            analyze.assert_not_called()
        self.assertEqual(job["status"], "failed")

    def test_session_storage_survives_service_restart(self):
        user = self.register(); self.login()
        app.state.auth_service = AuthService(self.sessions, self.settings)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], user.id)


if __name__ == "__main__":
    unittest.main()
