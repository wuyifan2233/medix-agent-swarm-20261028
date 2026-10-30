"""Bridge tests use a fake iLink channel, not a live WeChat account."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ["MEDIX_WECHAT_DISABLE"] = "1"
os.environ["MEDIX_QQ_DISABLE"] = "1"

from reminders.store import ReminderStore
from wechat.bridge import WeChatBridge, accept_message, fingerprint, reset_bridge
from wechat.ilink import ILinkClient, allowed_https_base, text_chunks


class FakeLink:
    def __init__(self):
        self.sent = []
        self.qr_status_body = {"status": "wait"}
        self.updates_body = {"ret": 0, "msgs": [], "get_updates_buf": "cursor"}
        self.baseurl = "https://ilinkai.weixin.qq.com"
        self.token = ""
        self.last_verify = ""
        self.update_calls = 0

    def get_qrcode(self, tokens):
        return 200, {"qrcode": "qr-secret", "qrcode_img_content": "https://liteapp.weixin.qq.com/q/demo"}

    def qr_status(self, qrcode, verify_code, base):
        self.last_verify = verify_code
        return 200, self.qr_status_body

    def get_updates(self, buf):
        self.update_calls += 1
        return 200, self.updates_body

    def send_text(self, user, token, text):
        self.sent.append((user, token, text))
        return 200, {"ret": 0}

    def get_config(self, user, token):
        return 200, {"ret": 0, "typing_ticket": "ticket"}

    def send_typing(self, user, ticket, status):
        return 200, {"ret": 0}

    def notify_start(self):
        return 200, {"ret": 0}

    def notify_stop(self):
        return 200, {"ret": 0}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "account.json")
        self.fake = FakeLink()
        self.replies = []
        self.store = ReminderStore(os.path.join(self.tmp, "reminders.sqlite"))
        self.browser = "a" * 32
        self.bridge = WeChatBridge(
            self.path, client=self.fake, reply=self._reply, store_getter=lambda: self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reply(self, user_id, session_id, message):
        self.replies.append((user_id, session_id, message))
        return "这是回复：" + message

    def _connect(self):
        self.bridge.begin_login(self.browser)
        self.fake.qr_status_body = {
            "status": "confirmed",
            "bot_token": "secret-token",
            "ilink_bot_id": "bot@im.bot",
            "ilink_user_id": "user@im.wechat",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }
        self.bridge.poll_login()

    def _incoming(self, text, message_id=11, token="ctx-1"):
        self.fake.updates_body = {"ret": 0, "get_updates_buf": "cursor-" + str(message_id), "msgs": [{
            "message_type": 1, "message_id": message_id, "from_user_id": "user@im.wechat",
            "context_token": token, "item_list": [{"type": 1, "text_item": {"text": text}}]}]}
        self.bridge.poll_updates()
        self.bridge.run_pending()

    def test_login_keeps_token_off_the_page(self):
        view = self.bridge.begin_login(self.browser)
        self.assertEqual(view["status"], "waiting")
        self.assertTrue(view["qr"].startswith("data:image/png;base64,"))
        self.assertNotIn("qr-secret", json.dumps(view))
        self._connect()
        view = self.bridge.view(self.browser, 0)
        self.assertEqual(view["status"], "connected")
        self.assertNotIn("secret-token", json.dumps(view))
        self.assertFalse(view["can_push"])
        saved = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertEqual(saved["bot_token"], "secret-token")
        other = self.bridge.view("b" * 32, 0)
        self.assertEqual(other["status"], "taken")
        self.assertEqual(other["qr"], "")
        self.assertEqual(other["events"], [])

    def test_phone_text_is_answered_and_echoes_are_ignored(self):
        self._connect()
        self.fake.updates_body = {"ret": 0, "get_updates_buf": "cursor-2", "msgs": [
            {"message_type": 1, "message_id": 11, "from_user_id": "user@im.wechat", "context_token": "ctx-1",
             "item_list": [{"type": 1, "text_item": {"text": "你好"}}]},
            {"message_type": 2, "message_id": 12, "from_user_id": "bot@im.bot", "context_token": "ctx-1",
             "item_list": [{"type": 1, "text_item": {"text": "自己的消息"}}]},
            {"message_type": 1, "message_id": 13, "group_id": "room", "from_user_id": "user@im.wechat",
             "context_token": "ctx-1", "item_list": [{"type": 1, "text_item": {"text": "群消息"}}]},
        ]}
        self.bridge.poll_updates()
        self.bridge.run_pending()
        self.assertEqual(self.replies, [("web-" + self.browser, "web-" + self.browser + "-wechat", "你好")])
        self.assertEqual(self.fake.sent, [("user@im.wechat", "ctx-1", "这是回复：你好")])
        view = self.bridge.view(self.browser, 0)
        self.assertEqual([item["text"] for item in view["events"]], ["你好", "这是回复：你好"])
        self.assertTrue(view["can_push"])
        self.bridge.poll_updates()
        self.bridge.run_pending()
        self.assertEqual(len(self.replies), 1)

        self.fake.sent.clear()
        self.assertTrue(self.bridge.forward_local("web-" + self.browser, "头痛", "先休息，观察变化。"))
        self.assertFalse(self.bridge.forward_local("web-" + "c" * 32, "头痛", "不应该发出去"))
        self.bridge.run_pending()
        self.assertEqual(len(self.fake.sent), 1)
        forwarded = self.fake.sent[0][2]
        self.assertIn("你在电脑上问：头痛", forwarded)
        self.assertIn("先休息，观察变化。", forwarded)
        self.fake.updates_body = {"ret": 0, "get_updates_buf": "cursor-echo", "msgs": [{
            "message_type": 1, "message_id": 40, "from_user_id": "user@im.wechat", "context_token": "ctx-1",
            "item_list": [{"type": 1, "text_item": {"text": forwarded}}]}]}
        self.bridge.poll_updates()
        self.bridge.run_pending()
        self.assertEqual(len(self.replies), 1)

    def test_accept_message_drops_recent_outgoing_text(self):
        digest = fingerprint("user@im.wechat", "原样转发")
        message = {"message_type": 1, "from_user_id": "user@im.wechat", "context_token": "ctx",
                   "item_list": [{"type": 1, "text_item": {"text": "原样转发"}}]}
        self.assertIsNone(accept_message(message, "bot", [(10_000, "user@im.wechat", digest)], 100))
        self.assertIsNotNone(accept_message(message, "bot", [(10, "user@im.wechat", digest)], 100))

    def test_media_gets_a_fixed_reply_without_the_model(self):
        self._connect()
        self.fake.updates_body = {"ret": 0, "get_updates_buf": "cursor-m", "msgs": [{
            "message_type": 1, "message_id": 7, "from_user_id": "user@im.wechat", "context_token": "ctx-1",
            "item_list": [{"type": 2, "image_item": {"media": {}}}]}]}
        self.bridge.poll_updates()
        self.bridge.run_pending()
        self.assertEqual(self.replies, [])
        self.assertIn("只能接收文字", self.fake.sent[0][2])

    def test_reminder_is_pushed_once(self):
        self._connect()
        self._incoming("先打个招呼")
        self.store.add_delivery(
            user_id="web-" + self.browser, session_id="web-" + self.browser + "-wechat", reminder_id="r1",
            scheduled_fire_at="2026-10-30T09:00:00+08:00", canonical_text="用药提醒：该吃药了。",
            delivered_at="2026-10-30T09:00:01+08:00")
        before = len(self.fake.sent)
        self.bridge.flush_reminders()
        self.bridge.flush_reminders()
        reminders = [item for item in self.fake.sent[before:] if "用药提醒" in item[2]]
        self.assertEqual(reminders, [("user@im.wechat", "ctx-1", "用药提醒：该吃药了。")])

    def test_rejected_token_stops_polling_work(self):
        self._connect()
        self.fake.updates_body = {"ret": -14, "msgs": []}
        self.bridge.poll_updates()
        self.assertEqual(self.bridge.view(self.browser, 0)["status"], "error")
        saved = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertEqual(saved["bot_token"], "")
        calls = self.fake.update_calls
        self.fake.updates_body = {"ret": 0, "get_updates_buf": "again", "msgs": [{
            "message_type": 1, "message_id": 3, "from_user_id": "user@im.wechat", "context_token": "ctx-1",
            "item_list": [{"type": 1, "text_item": {"text": "还在吗"}}]}]}
        self.bridge.poll_updates()
        self.bridge.run_pending()
        self.assertEqual(self.fake.update_calls, calls)
        self.assertEqual(self.replies, [])

    def test_pairing_code_is_sent_on_the_next_status_check(self):
        self.bridge.begin_login(self.browser)
        self.fake.qr_status_body = {"status": "need_verifycode"}
        self.bridge.poll_login()
        self.assertEqual(self.bridge.view(self.browser, 0)["status"], "need_code")
        with self.assertRaises(ValueError):
            self.bridge.submit_code(self.browser, "12ab")
        self.bridge.submit_code(self.browser, "123456")
        self.fake.qr_status_body = {"status": "scaned"}
        self.bridge.poll_login()
        self.assertEqual(self.fake.last_verify, "123456")
        self.assertEqual(self.bridge.view(self.browser, 0)["status"], "scanned")


class ProtocolTests(unittest.TestCase):
    def test_send_carries_context_token_and_bot_headers(self):
        calls = []

        def transport(method, url, body, headers, timeout):
            calls.append((method, url, body, headers, timeout))
            return 200, {"ret": 0}

        client = ILinkClient(transport)
        client.token = "secret-token"
        client.baseurl = "https://ilinkai.weixin.qq.com"
        client.send_text("user@im.wechat", "ctx-1", "你好")
        method, url, body, headers, timeout = calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/ilink/bot/sendmessage"))
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(headers["AuthorizationType"], "ilink_bot_token")
        self.assertEqual(headers["iLink-App-Id"], "bot")
        self.assertEqual(body["msg"]["context_token"], "ctx-1")
        self.assertEqual(body["msg"]["from_user_id"], "")
        self.assertEqual(body["msg"]["to_user_id"], "user@im.wechat")
        self.assertEqual(body["msg"]["message_type"], 2)
        self.assertEqual(body["msg"]["item_list"], [{"type": 1, "text_item": {"text": "你好"}}])
        self.assertNotIn("secret-token", url)

    def test_chunks_and_base_url(self):
        self.assertEqual(text_chunks("短"), ["短"])
        chunks = text_chunks("甲" * 1500 + "\n" + "乙" * 20, limit=1400, parts=3)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(item) <= 1400 for item in chunks))
        self.assertEqual(allowed_https_base("https://ilinkai.weixin.qq.com/path"), "https://ilinkai.weixin.qq.com")
        self.assertEqual(allowed_https_base("https://evil.example/ilink"), "")
        self.assertEqual(allowed_https_base("http://ilinkai.weixin.qq.com"), "")


class WeChatApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["MEDIX_WECHAT_DISABLE"] = "1"
        os.environ["MEDIX_WECHAT_ACCOUNT"] = os.path.join(self.tmp, "account.json")
        reset_bridge()

    def tearDown(self):
        reset_bridge()
        os.environ.pop("MEDIX_WECHAT_ACCOUNT", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_login_response_omits_secrets(self):
        from fastapi.testclient import TestClient
        from web.app import app
        from wechat.bridge import get_bridge

        with TestClient(app) as client:
            get_bridge().client = FakeLink()
            response = client.post("/api/wechat/login")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["status"], "waiting")
            self.assertTrue(body["qr"].startswith("data:image/png;base64,"))
            self.assertNotIn("qr-secret", response.text)
            self.assertNotIn("bot_token", response.text)
            bad = client.post("/api/wechat/code", json={"code": "nope"})
            self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
