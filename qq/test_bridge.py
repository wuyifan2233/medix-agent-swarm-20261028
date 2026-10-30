"""QQ bridge tests use a fake OneBot channel, not a live QQ account."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["MEDIX_QQ_DISABLE"] = "1"
os.environ["MEDIX_WECHAT_DISABLE"] = "1"

from reminders.store import ReminderStore
from qq.bridge import QQBridge, reset_bridge
from qq.onebot import accept_event, fingerprint, loopback_url
from qq.snowluma import read_endpoints


class FakeOneBot:
    def __init__(self):
        self.sent = []
        self.token = "secret-token"
        self.login = {"user_id": 10001, "nickname": "MediX"}
        self.fail = False
        self.friends = [{"user_id": 20002, "nickname": "小明", "remark": ""}]

    def get_login_info(self):
        if self.fail:
            return "network", None
        return 200, {"status": "ok", "retcode": 0, "data": dict(self.login)}

    def send_private_text(self, user_id, text):
        self.sent.append((str(user_id), text))
        return 200, {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    def get_friend_list(self):
        return 200, {"status": "ok", "retcode": 0, "data": self.friends}

    def get_stranger_info(self, user_id):
        return 200, {"status": "ok", "retcode": 0, "data": {"user_id": int(user_id), "nickname": "陌生人"}}


class QQBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "qq.json")
        self.fake = FakeOneBot()
        self.replies = []
        self.store = ReminderStore(os.path.join(self.tmp, "reminders.sqlite"))
        self.browser = "b" * 32
        self.bridge = QQBridge(self.path, client=self.fake, reply=self._reply, store_getter=lambda: self.store)
        self._channel = os.environ.get("MEDIX_CHANNEL")
        os.environ["MEDIX_CHANNEL"] = "qq"

    def tearDown(self):
        self.store.close()
        if self._channel is None:
            os.environ.pop("MEDIX_CHANNEL", None)
        else:
            os.environ["MEDIX_CHANNEL"] = self._channel
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reply(self, user_id, session_id, message, message_id=None):
        self.assertIsNotNone(message_id)
        self.replies.append((user_id, session_id, message))
        return "这是回复：" + message

    def _connect(self):
        view = self.bridge.begin_login(self.browser)
        self.assertEqual(view["status"], "connected")
        self.assertNotIn("secret-token", json.dumps(view))
        return view

    def test_private_text_is_answered_and_echoes_are_ignored(self):
        self._connect()
        added = self.bridge.add_friend(self.browser, "20002")
        self.assertEqual(added["peer"]["name"], "小明")
        self.assertIn("小明", added["hint"])
        self.fake.sent.clear()
        self.bridge.handle_event({
            "post_type": "message", "message_type": "private", "message_id": 11, "user_id": 20002,
            "message": [{"type": "text", "data": {"text": "你好"}}],
        })
        self.bridge.handle_event({
            "post_type": "message", "message_type": "group", "message_id": 12, "user_id": 20002,
            "group_id": 9, "message": [{"type": "text", "data": {"text": "群消息"}}],
        })
        self.bridge.handle_event({
            "post_type": "message", "message_type": "private", "message_id": 13, "user_id": 10001,
            "message": [{"type": "text", "data": {"text": "自己的消息"}}],
        })
        self.bridge.run_pending()
        self.assertEqual(self.replies, [(self.browser, "web-" + self.browser + "-qq", "你好")])
        self.assertEqual(self.fake.sent, [("20002", "这是回复：你好")])
        view = self.bridge.view(self.browser, 0)
        self.assertEqual([item["text"] for item in view["events"]], ["你好", "这是回复：你好"])
        self.assertTrue(view["can_push"])
        self.assertEqual(self.bridge.view("c" * 32, 0)["status"], "taken")
        self.bridge.handle_event({
            "post_type": "message", "message_type": "private", "message_id": 11, "user_id": 20002,
            "message": [{"type": "text", "data": {"text": "你好"}}],
        })
        self.bridge.run_pending()
        self.assertEqual(len(self.replies), 1)
        self.fake.sent.clear()
        self.assertTrue(self.bridge.forward_local(self.browser, "头痛", "先休息。"))
        self.bridge.run_pending()
        forwarded = self.fake.sent[0][1]
        self.assertIn("你在电脑上问：头痛", forwarded)
        self.bridge.handle_event({
            "post_type": "message", "message_type": "private", "message_id": 40, "user_id": 20002,
            "raw_message": forwarded,
        })
        self.bridge.run_pending()
        self.assertEqual(len(self.replies), 1)

    def test_login_failure_does_not_expose_the_token(self):
        self.fake.fail = True
        view = self.bridge.begin_login(self.browser)
        self.assertEqual(view["status"], "error")
        self.assertNotIn("secret-token", json.dumps(view))
        self.assertIn("OneBot", view["hint"])

    def test_reminder_goes_to_qq_once(self):
        self._connect()
        self.bridge.add_friend(self.browser, "20002")
        self.store.add_delivery(
            user_id=self.browser, session_id="web-" + self.browser + "-qq", reminder_id="r1",
            scheduled_fire_at="2026-10-30T09:00:00+08:00", canonical_text="用药提醒：该吃药了。",
            delivered_at="2026-10-30T09:00:01+08:00")
        before = len(self.fake.sent)
        self.bridge.flush_reminders()
        self.bridge.flush_reminders()
        reminders = [item for item in self.fake.sent[before:] if "用药提醒" in item[1]]
        self.assertEqual(reminders, [("20002", "用药提醒：该吃药了。")])

    def test_unknown_qq_is_not_bound(self):
        self._connect()
        view = self.bridge.add_friend(self.browser, "30003333")
        self.assertIsNone(view["peer"])
        self.assertIn("还不是好友", view["hint"])
        self.assertEqual(self.fake.sent, [])
        with self.assertRaises(ValueError):
            self.bridge.add_friend(self.browser, "12")

    def test_accept_event_drops_recent_outgoing_text(self):
        digest = fingerprint("20002", "原样转发")
        message = {"post_type": "message", "message_type": "private", "user_id": 20002,
                   "message": [{"type": "text", "data": {"text": "原样转发"}}]}
        self.assertIsNone(accept_event(message, "10001", [(10_000, "20002", digest)], 100))
        self.assertIsNotNone(accept_event(message, "10001", [(10, "20002", digest)], 100))


class OneBotAddressTests(unittest.TestCase):
    def test_onebot_config_uses_loopback_ports(self):
        found = read_endpoints({"networks": {
            "httpServers": [{"host": "127.0.0.1", "port": 3000, "accessToken": "http-token"}],
            "wsServers": [{"host": "127.0.0.1", "port": 3001, "accessToken": "ws-token"}],
        }})
        self.assertEqual(found["http"], "http://127.0.0.1:3000")
        self.assertEqual(found["ws"], "ws://127.0.0.1:3001")
        self.assertEqual(found["http_token"], "http-token")
        self.assertEqual(found["ws_token"], "ws-token")
        self.assertIsNone(read_endpoints({"networks": {
            "httpServers": [{"host": "0.0.0.0", "port": 3000, "accessToken": "x"}],
            "wsServers": [{"host": "127.0.0.1", "port": 3001, "accessToken": "y"}],
        }}))

    def test_only_loopback_onebot_addresses_are_used(self):
        self.assertEqual(loopback_url("http://127.0.0.1:3000", {"http"}), "http://127.0.0.1:3000")
        self.assertEqual(loopback_url("ws://127.0.0.1:3001", {"ws"}), "ws://127.0.0.1:3001")
        self.assertEqual(loopback_url("http://example.com:3000", {"http"}), "")
        self.assertEqual(loopback_url("https://127.0.0.1:3000", {"http"}), "")
        self.assertEqual(loopback_url("ws://127.0.0.1:3001/extra", {"ws"}), "")


class QQApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["MEDIX_QQ_DISABLE"] = "1"
        os.environ["MEDIX_WECHAT_DISABLE"] = "1"
        os.environ["MEDIX_QQ_ACCOUNT"] = os.path.join(self.tmp, "qq.json")
        os.environ["MEDIX_CHANNEL_PATH"] = os.path.join(self.tmp, "channel.json")
        reset_bridge()
        from wechat.bridge import reset_bridge as reset_wechat
        reset_wechat()

    def tearDown(self):
        reset_bridge()
        os.environ.pop("MEDIX_QQ_ACCOUNT", None)
        os.environ.pop("MEDIX_CHANNEL_PATH", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_login_and_channel_switch(self):
        from fastapi.testclient import TestClient
        from web.app import app
        from qq.bridge import get_bridge

        from storage.test_support import account_clients
        with account_clients() as accounts:
            client = accounts.clients[0]
            get_bridge().client = FakeOneBot()
            response = client.post("/api/qq/login",json={})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["status"], "connected")
            self.assertNotIn("secret-token", response.text)
            from messenger import load_channel_state
            saved = load_channel_state("qq")
            self.assertEqual(saved["self_id"], "10001")
            self.assertNotIn("token", saved)
            switched = client.post("/api/channel", json={"channel": "qq"})
            self.assertEqual(switched.status_code, 200)
            self.assertEqual(client.get("/api/channel").json()["channel"], "qq")
            bad = client.post("/api/channel", json={"channel": "telegram"})
            self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
