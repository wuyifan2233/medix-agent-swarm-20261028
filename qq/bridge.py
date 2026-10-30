"""Bridge MediX conversations with a QQ account logged in through local OneBot."""
import base64
import json
import os
import queue
import threading
import time
from pathlib import Path

from loguru import logger

from messenger import current_channel
from wechat.ilink import text_chunks
from .onebot import OneBotClient, accept_event, action_ok, default_ws, fingerprint, run_ws
from .snowluma import SnowLumaHost

ROOT = Path(__file__).resolve().parents[1]
MEDIA_REPLY = "QQ 里暂时只能接收文字。图片可以在电脑上的 MediX 页面上传。"
IDLE_HINT = "输入要转发的好友 QQ 号。本机登录的 QQ 会把 MediX 的回复和提醒发到这个好友。"
PEER_INTRO = "你好，我是 MediX。之后在这个私聊里发消息，我会回复；提醒也会发到这里。"
TAKEN_HINT = "这台电脑已经有一个页面连接了 QQ MediX。"


def account_path():
    override = os.environ.get("MEDIX_QQ_ACCOUNT")
    if override:
        return Path(override)
    return ROOT / "data" / "qq_account.json"


class QQBridge:
    def __init__(self, path, client=None, reply=None, store_getter=None):
        self.path = str(path)
        self.client = client or OneBotClient(token=os.environ.get("MEDIX_QQ_TOKEN") or "")
        self.reply = reply
        self.store_getter = store_getter or _default_store
        self._lock = threading.RLock()
        self._jobs = queue.Queue()
        self._stop = threading.Event()
        self._generation = 0
        self._sender = None
        self._ws = None
        self._phase = "idle"
        self._status = "idle"
        self._error = ""
        self.owner = ""
        self._self_id = ""
        self._nickname = ""
        self._peer_user = ""
        self._peer_name = ""
        self._friend_note = ""
        self._outgoing = []
        self._seen = set()
        self._events = []
        self._seq = 0
        self._qr_image = ""
        self._detail = ""
        self._prepare = None
        self._ws_url = ""
        self._ws_token = ""
        self._ws_stop = threading.Event()

    def set_reply(self, reply):
        self.reply = reply

    def start(self):
        if os.environ.get("MEDIX_QQ_DISABLE") == "1":
            return
        self._load()
        self._stop.set()
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._stop = threading.Event()
        self._sender = threading.Thread(target=self._loop_send, args=(generation,), name="medix-qq-send", daemon=True)
        self._sender.start()
        if self._phase == "online" and isinstance(self.client, OneBotClient):
            threading.Thread(target=self._resume_host, name="medix-qq-resume", daemon=True).start()

    def _resume_host(self):
        try:
            result = SnowLumaHost().resume()
        except Exception:
            logger.warning("QQ resume failed")
            return
        if not result:
            return
        self.client.http_url = result["http"]
        self.client.token = result["http_token"]
        self._ws_url = result["ws"]
        self._ws_token = result["ws_token"]
        self._finish_client_login(retries=8)

    def stop(self):
        with self._lock:
            self._generation += 1
            self._phase = "idle"
        self._stop.set()
        self._ws_stop.set()
        sender = self._sender
        if sender and sender.is_alive() and threading.current_thread() is not sender:
            sender.join(timeout=2)

    def view(self, browser_id, after=0):
        with self._lock:
            return self._view_locked(browser_id, after)

    def begin_login(self, browser_id):
        with self._lock:
            if self._blocks(browser_id):
                return self._view_locked(browser_id, 0)
            self.owner = browser_id
            self._error = ""
            use_host = isinstance(self.client, OneBotClient) and os.environ.get("MEDIX_QQ_DISABLE") != "1"
            if use_host:
                if self._prepare and self._prepare.is_alive():
                    return self._view_locked(browser_id, 0)
                self._phase = "login"
                self._status = "waiting"
                self._detail = "正在打开 QQ 登录…"
                self._qr_image = ""
                self._prepare = threading.Thread(target=self._prepare_login, name="medix-qq-login", daemon=True)
                self._prepare.start()
                return self._view_locked(browser_id, 0)
            self._status = "connecting"
        return self._finish_client_login()

    def _prepare_login(self):
        def cancelled():
            with self._lock:
                return self._phase != "login"

        def on_qr(png):
            if cancelled():
                return
            with self._lock:
                self._qr_image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                self._detail = "请用手机 QQ 扫描二维码登录。"
                self._status = "waiting"

        try:
            result = SnowLumaHost().prepare(cancelled, on_qr)
        except RuntimeError as exc:
            if str(exc) == "已取消" or cancelled():
                return
            self._fail_login(str(exc))
            return
        except Exception:
            logger.exception("QQ login prepare failed")
            self._fail_login("打开 QQ 登录失败，请稍后重试。")
            return
        if cancelled():
            return
        self.client.http_url = result["http"]
        self.client.token = result["http_token"]
        self._ws_url = result["ws"]
        self._ws_token = result["ws_token"]
        self._finish_client_login(retries=8)

    def _fail_login(self, message):
        with self._lock:
            if self._phase != "login":
                return
            self._phase = "idle"
            self._status = "error"
            self._error = message
            self._detail = ""
            self._qr_image = ""

    def _finish_client_login(self, retries=1):
        status, body = "network", None
        for attempt in range(retries):
            try:
                status, body = self.client.get_login_info()
            except Exception:
                logger.warning("QQ login probe failed")
                status, body = "network", None
            if action_ok(status, body) or attempt == retries - 1:
                break
            time.sleep(0.4)
        with self._lock:
            if not action_ok(status, body):
                self._phase = "idle"
                self._status = "error"
                self._error = "QQ 已打开，但 OneBot 还没有就绪。请再点一次扫码登录。"
                self._detail = ""
                self._self_id = ""
                return self._view_locked(self.owner, 0)
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            user_id = str(data.get("user_id") or "")
            if not user_id.isdigit():
                self._phase = "idle"
                self._status = "error"
                self._error = "QQ 登录信息没有返回可用的账号。"
                return self._view_locked(self.owner, 0)
            self._self_id = user_id
            self._nickname = str(data.get("nickname") or "")[:40]
            self._phase = "online"
            self._status = "connected"
            self._error = ""
            self._detail = ""
            self._qr_image = ""
            self._save_locked()
        self._ensure_ws()
        logger.info("QQ MediX linked")
        return self.view(self.owner, 0)

    def add_friend(self, browser_id, raw_id):
        user_id = str(raw_id or "").strip()
        if not user_id.isdigit() or not 5 <= len(user_id) <= 11:
            raise ValueError("请输入 5 到 11 位的好友 QQ 号。")
        with self._lock:
            if self._blocks(browser_id):
                return self._view_locked(browser_id, 0)
            self.owner = browser_id
            online = self._phase == "online" and bool(self._self_id)
        if not online:
            self._ensure_local_qq()
        with self._lock:
            if self._phase != "online" or not self._self_id:
                if not self._error:
                    self._status = "error"
                    self._error = "电脑版 QQ 还没有登录。请先在电脑上登录 QQ，再添加好友。"
                return self._view_locked(browser_id, 0)
            if user_id == self._self_id:
                self._friend_note = "这是本机登录的 QQ，请填写对方的 QQ 号。"
                return self._view_locked(browser_id, 0)
        friends = self._friend_rows()
        match = next((row for row in friends if str(row.get("user_id") or "") == user_id), None)
        if not match:
            nick = self._stranger_name(user_id)
            label = nick or user_id
            with self._lock:
                self._friend_note = f"{label} 还不是好友。请先在电脑 QQ 里加上这个号码，对方通过后再回来确认。"
                return self._view_locked(browser_id, 0)
        name = str(match.get("remark") or match.get("nickname") or user_id)[:40]
        with self._lock:
            same = self._peer_user == user_id
            self._peer_user = user_id
            self._peer_name = name
            self._friend_note = ""
            self._error = ""
            self._status = "connected"
            self._save_locked()
        if not same:
            if not self._send_plain(user_id, PEER_INTRO):
                with self._lock:
                    self._friend_note = "已记下这个好友，但第一条消息没有发出去。请在 QQ 里打开这个私聊再试。"
        logger.info("QQ forward target set")
        return self.view(browser_id, 0)

    def _ensure_local_qq(self):
        if isinstance(self.client, OneBotClient) and os.environ.get("MEDIX_QQ_DISABLE") != "1":
            try:
                result = SnowLumaHost().resume()
            except Exception:
                logger.warning("QQ resume before add friend failed")
                result = None
            if result:
                self.client.http_url = result["http"]
                self.client.token = result["http_token"]
                self._ws_url = result["ws"]
                self._ws_token = result["ws_token"]
            self._finish_client_login(retries=4)
            return
        self._finish_client_login()

    def _friend_rows(self):
        getter = getattr(self.client, "get_friend_list", None)
        if getter is None:
            return []
        try:
            status, body = getter()
        except Exception:
            logger.warning("QQ friend list failed")
            return []
        if not action_ok(status, body) or not isinstance(body.get("data"), list):
            return []
        return body["data"]

    def _stranger_name(self, user_id):
        getter = getattr(self.client, "get_stranger_info", None)
        if getter is None:
            return ""
        try:
            status, body = getter(user_id)
        except Exception:
            return ""
        data = body.get("data") if action_ok(status, body) and isinstance(body, dict) else None
        if not isinstance(data, dict):
            return ""
        return str(data.get("nickname") or "")[:40]

    def logout(self, browser_id):
        with self._lock:
            if self.owner and self.owner != browser_id:
                return self._view_locked(browser_id, 0)
            self._wipe_locked()
        return self.view(browser_id, 0)

    def forward_local(self, user_id, question, answer):
        text = str(answer or "").strip()
        if not text:
            return False
        question = str(question or "（图片）").strip() or "（图片）"
        body = "你在电脑上问：" + question[:800] + "\n\n" + text
        with self._lock:
            if self._phase != "online" or not self.owner or user_id != "web-" + self.owner or not self._peer_user:
                return False
            self._jobs.put({"kind": "out", "user": self._peer_user, "text": body})
        return True

    def handle_event(self, event):
        now = time.monotonic()
        with self._lock:
            if self._phase != "online":
                return
            self._outgoing = [item for item in self._outgoing if item[0] > now]
            parsed = accept_event(event, self._self_id, self._outgoing, now)
            if not parsed or parsed["id"] in self._seen:
                return
            self._seen.add(parsed["id"])
            if len(self._seen) > 500:
                self._seen = set(list(self._seen)[-300:])
            if not self._peer_user or parsed["user"] != self._peer_user:
                return
            self._jobs.put({**parsed, "kind": "in"})

    def run_pending(self):
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            self.run_job(job)

    def run_job(self, job):
        if job.get("kind") == "out":
            self._send_plain(job.get("user"), job.get("text"))
            return
        user = job.get("user") or ""
        if job.get("media"):
            self._publish("user", "（在 QQ 发来了图片或文件）")
            self._send_plain(user, MEDIA_REPLY)
            self._publish("assistant", MEDIA_REPLY)
            return
        text = job.get("text") or ""
        self._publish("user", text)
        try:
            if self.reply is None:
                raise RuntimeError("MediX reply is not ready")
            answer = self.reply(self._memory_user(), self._memory_session(), text)
        except ValueError as exc:
            answer = str(exc) or "这次没能完成分析，请稍后再问我。"
        except Exception:
            logger.warning("QQ answer failed")
            answer = "这次没能完成分析，请稍后再问我。"
        answer = str(answer or "").strip() or "这次没能完成分析，请稍后再问我。"
        self._send_plain(user, answer)
        self._publish("assistant", answer)

    def flush_reminders(self):
        if current_channel() != "qq":
            return
        with self._lock:
            if self._phase != "online" or not self.owner or not self._peer_user:
                return
            user_id = "web-" + self.owner
            peer = self._peer_user
        if self.store_getter is None:
            return
        try:
            rows = self.store_getter().pending_wechat(user_id, limit=3)
        except Exception:
            logger.warning("QQ reminder lookup failed")
            return
        for row in rows:
            if not self._send_plain(peer, row.get("canonical_text") or ""):
                return
            try:
                self.store_getter().mark_wechat_sent(user_id, row["id"])
            except Exception:
                logger.warning("QQ reminder mark failed")
                return

    def _loop_send(self, generation):
        while generation == self._generation and not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=1)
            except queue.Empty:
                try:
                    self.flush_reminders()
                except Exception:
                    logger.exception("QQ reminder flush failed")
                continue
            try:
                self.run_job(job)
                self.flush_reminders()
            except Exception:
                logger.exception("QQ send failed")

    def _ensure_ws(self):
        if os.environ.get("MEDIX_QQ_DISABLE") == "1":
            return
        self._ws_stop.set()
        stopper = threading.Event()
        self._ws_stop = stopper
        url = self._ws_url or default_ws()
        if not url:
            return
        token = self._ws_token or self.client.token
        self._ws = threading.Thread(
            target=run_ws, args=(url, token, stopper, self.handle_event),
            name="medix-qq-ws", daemon=True)
        self._ws.start()

    def _who_locked(self):
        if self._nickname and self._self_id:
            return f"{self._nickname}（{self._self_id}）"
        return self._nickname or self._self_id or "这个 QQ"

    def _blocks(self, browser_id):
        return bool(self.owner) and self.owner != browser_id and self._phase == "online"

    def _memory_user(self):
        with self._lock:
            return "web-" + self.owner if self.owner else ""

    def _memory_session(self):
        user_id = self._memory_user()
        return user_id + "-qq" if user_id else ""

    def _view_locked(self, browser_id, after):
        taken = self._blocks(browser_id)
        mine = bool(self.owner) and browser_id == self.owner and not taken
        status = "taken" if taken else self._status
        can_push = status == "connected" and bool(self._peer_user)
        if self._friend_note and status == "connected":
            hint = self._friend_note
        elif status == "connected" and can_push:
            who = self._peer_name or self._peer_user
            hint = f"转发对象是 {who}（{self._peer_user}）。在 QQ 里打开和这个好友的私聊，那就是 MediX 的对话。"
        elif status == "connected":
            hint = f"本机 QQ 已登录 {self._who_locked()}。在下面输入好友 QQ 号，回复和提醒会发到这个好友。"
        elif status == "waiting":
            hint = self._detail or "正在打开 QQ 登录…"
        elif status == "error":
            hint = self._error or "暂时连不上本机 QQ。"
        elif status == "taken":
            hint = TAKEN_HINT
        else:
            hint = IDLE_HINT
        events = [dict(item) for item in self._events if item["id"] > after] if mine else []
        return {
            "name": "MediX",
            "status": status,
            "hint": hint,
            "linked": status == "connected",
            "can_push": can_push,
            "qr": self._qr_image if mine and status == "waiting" else "",
            "peer": {"user_id": self._peer_user, "name": self._peer_name} if mine and self._peer_user else None,
            "events": events,
            "cursor": self._events[-1]["id"] if mine and self._events else 0,
        }

    def _send_plain(self, user, text):
        if not str(user or "").isdigit() or not str(text or "").strip():
            return False
        for chunk in text_chunks(text):
            sent = False
            for _attempt in range(2):
                try:
                    status, body = self.client.send_private_text(user, chunk)
                except Exception:
                    status, body = "network", None
                if action_ok(status, body):
                    with self._lock:
                        now = time.monotonic()
                        self._outgoing = [item for item in self._outgoing if item[0] > now]
                        self._outgoing.append((now + 60, user, fingerprint(user, chunk)))
                        del self._outgoing[:-200]
                    sent = True
                    break
            if not sent:
                return False
        return True

    def _publish(self, role, text):
        with self._lock:
            self._seq += 1
            self._events.append({"id": self._seq, "role": role, "text": str(text)[:4000], "origin": "qq"})
            del self._events[:-80]

    def _wipe_locked(self):
        self._self_id = ""
        self._nickname = ""
        self._peer_user = ""
        self._peer_name = ""
        self._friend_note = ""
        self._outgoing.clear()
        self._seen.clear()
        self._events.clear()
        self._qr_image = ""
        self._detail = ""
        self._ws_url = ""
        self._ws_token = ""
        self._ws_stop.set()
        self.owner = ""
        self._phase = "idle"
        self._status = "idle"
        self._error = ""
        path = Path(self.path)
        if path.exists():
            path.unlink()
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break

    def _save_locked(self):
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "owner_browser": self.owner,
            "self_id": self._self_id,
            "nickname": self._nickname,
            "peer_user": self._peer_user,
            "peer_name": self._peer_name,
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _load(self):
        path = Path(self.path)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("QQ account file unreadable")
            return
        if not isinstance(payload, dict):
            return
        self_id = str(payload.get("self_id") or "")
        owner = str(payload.get("owner_browser") or "")
        with self._lock:
            self._self_id = self_id if self_id.isdigit() else ""
            self._nickname = str(payload.get("nickname") or "")[:40]
            self._peer_user = str(payload.get("peer_user") or "")
            self._peer_name = str(payload.get("peer_name") or "")[:40]
            self.owner = owner
            if self._self_id and owner:
                self._phase = "online"
                self._status = "connected"
            else:
                self._phase = "idle"
                self._status = "idle"


def _default_store():
    from reminders.service import get_service
    return get_service().store


_bridge = None
_bridge_lock = threading.Lock()


def get_bridge():
    global _bridge
    with _bridge_lock:
        path = str(account_path())
        if _bridge is None or _bridge.path != path:
            if _bridge is not None:
                _bridge.stop()
            _bridge = QQBridge(path)
        return _bridge


def reset_bridge():
    global _bridge
    with _bridge_lock:
        if _bridge is not None:
            _bridge.stop()
            _bridge = None
