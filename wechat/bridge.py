"""Bridge MediX conversations with a WeChat bot the phone adds by scanning.

Inbound WeChat text is answered by the local assistant and sent back.
Local answers and due reminders are pushed into that same WeChat chat.
"""
import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path

from loguru import logger

from .ilink import ILinkClient, allowed_https_base, login_fields, result_code, text_chunks
from .qr import qr_data_url

ROOT = Path(__file__).resolve().parents[1]
MEDIA_REPLY = "微信里暂时只能接收文字。图片可以在电脑上的 MediX 页面上传。"
HINTS = {
    "idle": "用微信扫码，把 MediX 加到聊天列表。手机上的对话会同步到这里，提醒也会发到微信。",
    "waiting": "请用微信扫描二维码，并在手机上确认添加 MediX。",
    "scanned": "已扫码，请在手机上确认添加。",
    "need_code": "请输入手机微信上显示的配对码。",
    "expired": "二维码已过期，请重新获取。",
    "taken": "这台电脑已经有一个页面连接了微信 MediX。",
}


def _default_store():
    from reminders.service import get_service
    return get_service().store


def account_path():
    override = os.environ.get("MEDIX_WECHAT_ACCOUNT")
    if override:
        return Path(override)
    return ROOT / "data" / "wechat_account.json"


def fingerprint(user, text):
    return hashlib.sha256((str(user) + "\n" + str(text).strip()).encode("utf-8")).hexdigest()


def accept_message(msg, bot_id, outgoing, now):
    """Keep a new private user text. Drop echoes, groups, and the bot's own sends."""
    if not isinstance(msg, dict) or msg.get("group_id"):
        return None
    try:
        kind = int(msg.get("message_type") or 0)
    except (TypeError, ValueError):
        return None
    if kind != 1:
        return None
    user = str(msg.get("from_user_id") or "")
    token = str(msg.get("context_token") or "")
    if not user or user == str(bot_id or "") or not token:
        return None
    texts = []
    had_item = False
    for item in msg.get("item_list") or []:
        if not isinstance(item, dict):
            continue
        had_item = True
        for key in ("text_item", "voice_item"):
            block = item.get(key)
            if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip():
                texts.append(block["text"].strip())
    text = "\n".join(texts).strip()
    if text:
        digest = fingerprint(user, text)
        if any(expiry > now and owner == user and previous == digest for expiry, owner, previous in outgoing):
            return None
    elif not had_item:
        return None
    message_id = str(msg.get("message_id") or msg.get("client_id") or msg.get("seq") or "")
    if not message_id:
        message_id = fingerprint(user, text or token)
    return {"id": message_id, "user": user, "token": token, "text": text[:8000], "media": not bool(text)}


class WeChatBridge:
    def __init__(self, path, client=None, reply=None, store_getter=None):
        self.path = str(path)
        self.database_backed = False
        self.client = client or ILinkClient()
        self.reply = reply
        self.store_getter = _default_store if store_getter is None else store_getter
        self._lock = threading.RLock()
        self._jobs = queue.Queue()
        self._stop = threading.Event()
        self._generation = 0
        self._poller = None
        self._sender = None
        self._phase = "idle"
        self._status = "idle"
        self._error = ""
        self.owner = ""
        self._token = ""
        self._bot_id = ""
        self._login_user = ""
        self._buf = ""
        self._peers = {}
        self._peer_user = ""
        self._qrcode = ""
        self._qr_image = ""
        self._verify_code = ""
        self._status_base = ""
        self._refreshes = 0
        self._outgoing = []
        self._seen = set()
        self._events = []
        self._seq = 0
        self._tickets = {}

    def set_reply(self, reply):
        self.reply = reply

    def start(self):
        if os.environ.get("MEDIX_WECHAT_DISABLE") == "1":
            return
        self._load()
        self._stop.set()
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._stop = threading.Event()
        self._poller = threading.Thread(target=self._loop_poll, args=(generation,), name="medix-wechat-poll", daemon=True)
        self._sender = threading.Thread(target=self._loop_send, args=(generation,), name="medix-wechat-send", daemon=True)
        self._poller.start()
        self._sender.start()
        if self._phase == "online":
            self._notify_start()

    def stop(self):
        with self._lock:
            self._generation += 1
        self._stop.set()
        sender = self._sender
        if sender and sender.is_alive() and threading.current_thread() is not sender:
            sender.join(timeout=2)
        self._notify_stop()

    def view(self, browser_id, after=0):
        with self._lock:
            return self._view_locked(browser_id, after)

    def begin_login(self, browser_id):
        with self._lock:
            if self._blocks(browser_id):
                return self._view_locked(browser_id, 0)
            self.owner = browser_id
            self._phase = "login"
            self._verify_code = ""
            self._refreshes = 0
            self._error = ""
        self._fetch_qr()
        return self.view(browser_id, 0)

    def submit_code(self, browser_id, code):
        digits = str(code or "").strip()
        if not digits.isdigit() or not 4 <= len(digits) <= 8:
            raise ValueError("配对码是 4 到 8 位数字。")
        with self._lock:
            if self.owner != browser_id:
                return self._view_locked(browser_id, 0)
            self._verify_code = digits
            self._status = "waiting"
        return self.view(browser_id, 0)

    def logout(self, browser_id):
        with self._lock:
            if self.owner and self.owner != browser_id:
                return self._view_locked(browser_id, 0)
            token = self._token
        if token:
            self.client.token = token
            self._notify_stop()
        with self._lock:
            self._wipe_locked()
        return self.view(browser_id, 0)

    def forward_local(self, user_id, question, answer):
        text = str(answer or "").strip()
        if not text:
            return False
        question = str(question or "（图片）").strip() or "（图片）"
        body = "你在电脑上问：" + question[:800] + "\n\n" + text
        with self._lock:
            if self._phase != "online" or not self.owner or user_id != self.owner:
                return False
            peer = self._peer_locked()
            if not peer:
                return False
            self._jobs.put({"account_owner":self.owner, "kind": "out", "user": peer[0], "token": peer[1], "text": body})
        return True

    def poll_login(self):
        with self._lock:
            if self._phase != "login" or not self._qrcode:
                return
            qrcode = self._qrcode
            verify = self._verify_code
            base = self._status_base
        try:
            code, body = self.client.qr_status(qrcode, verify, base)
        except Exception:
            logger.warning("WeChat login status failed")
            code, body = "network", None
        action = "hold"
        with self._lock:
            if self._phase != "login" or self._qrcode != qrcode:
                return
            action = self._apply_status_locked(code, body)
        if action == "fetch":
            self._fetch_qr()
        elif action == "online":
            self._notify_start()
            logger.info("WeChat MediX linked")
        elif self._poller and self._poller.is_alive():
            self._stop.wait(1)

    def poll_updates(self):
        with self._lock:
            if self._phase != "online" or not self._token:
                return
            buf = self._buf
        try:
            code, body = self.client.get_updates(buf)
        except Exception:
            logger.warning("WeChat updates failed")
            code, body = "network", None
        if code == "timeout":
            return
        if self._token_rejected(code, body):
            return
        if code != 200 or result_code(body) not in (0, None):
            self._stop.wait(2)
            return
        messages = body.get("msgs") if isinstance(body, dict) else []
        new_buf = body.get("get_updates_buf") if isinstance(body, dict) else ""
        now = time.monotonic()
        with self._lock:
            if self._phase != "online":
                return
            self._outgoing = [item for item in self._outgoing if item[0] > now]
            for msg in messages or []:
                parsed = accept_message(msg, self._bot_id, self._outgoing, now)
                if self.database_backed and parsed and (not self._login_user or parsed["user"] != self._login_user):
                    continue
                if not parsed or parsed["id"] in self._seen:
                    continue
                self._seen.add(parsed["id"])
                if len(self._seen) > 500:
                    self._seen = set(list(self._seen)[-300:])
                self._peers[parsed["user"]] = parsed["token"]
                self._peer_user = parsed["user"]
                self._jobs.put({**parsed, "account_owner":self.owner, "kind": "in"})
            if isinstance(new_buf, str) and new_buf:
                self._buf = new_buf
            self._save_locked()

    def run_pending(self):
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            self.run_job(job)

    def run_job(self, job):
        expected_owner=job.get("account_owner",self.owner)
        if self.database_backed:
            from messenger import load_channel_state
            state = load_channel_state("wechat")
            if not state or state.get("owner_browser") != expected_owner or self.owner != expected_owner or job.get("user") != self._login_user:
                return
        if job.get("kind") == "out":
            self._send_plain(job.get("user"), job.get("token"), job.get("text"))
            return
        user = job.get("user") or ""
        token = job.get("token") or ""
        if job.get("media"):
            self._publish("user", "（在微信发来了图片或文件）",expected_owner)
            self._send_plain(user, token, MEDIA_REPLY)
            self._publish("assistant", MEDIA_REPLY,expected_owner)
            return
        text = job.get("text") or ""
        self._publish("user", text,expected_owner)
        try:
            if self.reply is None:
                raise RuntimeError("MediX reply is not ready")
            answer = self.reply(expected_owner, "web-" + expected_owner + "-wechat", text)
        except ValueError as exc:
            answer = str(exc) or "这次没能完成分析，请稍后再问我。"
        except Exception:
            logger.warning("WeChat answer failed")
            answer = "这次没能完成分析，请稍后再问我。"
        if self.database_backed:
            state=load_channel_state('wechat')
            if self.owner != expected_owner or not state or state.get('owner_browser') != expected_owner:
                return
        answer = str(answer or "").strip() or "这次没能完成分析，请稍后再问我。"
        self._send_plain(user, token, answer)
        self._publish("assistant", answer,expected_owner)

    def flush_reminders(self):
        if self.database_backed:
            from messenger import load_channel_state
            state=load_channel_state('wechat')
            if not state or state.get('owner_browser') != self.owner:
                return
        from messenger import current_channel
        if current_channel(self.owner) != "wechat":
            return
        with self._lock:
            if self._phase != "online" or not self.owner:
                return
            user_id = self.owner
            peer = self._peer_locked()
        if not peer or self.store_getter is None:
            return
        try:
            rows = self.store_getter().pending_wechat(user_id, limit=3)
        except Exception:
            logger.warning("WeChat reminder lookup failed")
            return
        for row in rows:
            if not self._send_plain(peer[0], peer[1], row.get("canonical_text") or ""):
                return
            try:
                self.store_getter().mark_wechat_sent(user_id, row["id"])
            except Exception:
                logger.warning("WeChat reminder mark failed")
                return

    def _loop_poll(self, generation):
        while self._alive(generation):
            phase = self.phase
            try:
                if phase == "login":
                    self.poll_login()
                elif phase == "online":
                    self.poll_updates()
                else:
                    self._stop.wait(0.4)
            except Exception:
                logger.exception("WeChat poll failed")
                self._stop.wait(2)

    def _loop_send(self, generation):
        while self._alive(generation):
            try:
                job = self._jobs.get(timeout=1)
            except queue.Empty:
                try:
                    self.flush_reminders()
                except Exception:
                    logger.exception("WeChat reminder flush failed")
                continue
            try:
                self.run_job(job)
                self.flush_reminders()
            except Exception:
                logger.exception("WeChat send failed")

    def _alive(self, generation):
        return generation == self._generation and not self._stop.is_set()

    @property
    def phase(self):
        with self._lock:
            return self._phase

    def _blocks(self, browser_id):
        return bool(self.owner) and self.owner != browser_id and (self.database_backed or self._phase in {"login", "online"})

    def _peer_locked(self):
        user = self._peer_user
        token = self._peers.get(user) if user else ""
        if user and token:
            return user, token
        if len(self._peers) == 1:
            return next(iter(self._peers.items()))
        return None

    def _memory_user(self):
        with self._lock:
            return self.owner if self.owner else ""

    def _memory_session(self):
        user_id = self._memory_user()
        return "web-" + user_id + "-wechat" if user_id else ""

    def _view_locked(self, browser_id, after):
        taken = self._blocks(browser_id)
        mine = bool(self.owner) and browser_id == self.owner and not taken
        if taken:
            status = "taken"
        elif not mine and self._phase == "login":
            status = "idle"
        else:
            status = self._status
        can_push = status == "connected" and self._peer_locked() is not None
        if status == "connected" and can_push:
            hint = "已连接。手机消息会同步到这个页面，电脑上的回答和到点提醒会发到微信。"
        elif status == "connected":
            hint = "已添加。请先在微信里给 MediX 发一句话，之后电脑上的对话和提醒才能发过去。"
        elif status == "error":
            hint = self._error or "微信连接暂时不可用，请稍后重试。"
        else:
            hint = HINTS.get(status, HINTS["idle"])
        events = [dict(item) for item in self._events if item["id"] > after] if mine else []
        show_qr = mine and status in {"waiting", "scanned", "need_code"} and bool(self._qr_image)
        return {
            "name": "MediX",
            "status": status,
            "hint": hint,
            "linked": status == "connected",
            "can_push": can_push,
            "qr": self._qr_image if show_qr else "",
            "events": events,
            "cursor": self._events[-1]["id"] if mine and self._events else 0,
        }

    def _fetch_qr(self):
        with self._lock:
            tokens = [self._token] if self._token else []
        try:
            code, body = self.client.get_qrcode(tokens)
        except Exception:
            logger.warning("WeChat qr request failed")
            code, body = "network", None
        with self._lock:
            self._store_qr_locked(code, body)

    def _store_qr_locked(self, code, body):
        fields = login_fields(body)
        content = str(fields.get("qrcode_img_content") or fields.get("qrcode_url") or "")
        qrcode = str(fields.get("qrcode") or "")
        if code != 200 or not qrcode or not content:
            self._phase = "idle"
            self._status = "error"
            self._error = "暂时连不上微信，请检查网络后重试。"
            self._qr_image = ""
            self._qrcode = ""
            return
        self._qrcode = qrcode
        self._qr_image = self._make_qr(content)
        self._phase = "login"
        self._status = "waiting" if self._qr_image else "error"
        if not self._qr_image:
            self._error = "二维码没有生成，请稍后重试。"

    def _make_qr(self, content):
        try:
            return qr_data_url(content)
        except Exception:
            logger.warning("WeChat qr image failed")
            return ""

    def _apply_status_locked(self, code, body):
        if code == "timeout":
            return "hold"
        if code != 200 or not isinstance(body, dict):
            self._status = "error"
            self._error = "暂时连不上微信，请检查网络后重试。"
            self._phase = "idle"
            self._qr_image = ""
            return "stop"
        fields = login_fields(body)
        status = str(fields.get("status") or "")
        if status == "wait":
            self._status = "waiting"
            return "hold"
        if status == "scaned":
            self._status = "scanned"
            self._verify_code = ""
            return "hold"
        if status == "need_verifycode":
            self._status = "need_code"
            self._verify_code = ""
            return "stop"
        if status in {"expired", "verify_code_blocked"}:
            self._verify_code = ""
            self._refreshes += 1
            if self._refreshes <= 3:
                return "fetch"
            self._phase = "idle"
            self._status = "expired"
            self._qr_image = ""
            self._qrcode = ""
            return "stop"
        if status == "scaned_but_redirect":
            host = str(fields.get("redirect_host") or "")
            base = allowed_https_base("https://" + host) if host and "://" not in host else allowed_https_base(host)
            if base:
                self._status_base = base
            return "hold"
        if status == "binded_redirect" and self._token:
            self._enter_online_locked()
            return "online"
        if status == "confirmed":
            token = str(fields.get("bot_token") or "")
            bot_id = str(fields.get("ilink_bot_id") or "")
            base = allowed_https_base(fields.get("baseurl")) or self.client.baseurl
            if not token or not bot_id:
                self._status = "error"
                self._error = "微信没有返回可用的登录信息，请重新扫码。"
                self._phase = "idle"
                self._qr_image = ""
                return "stop"
            self._token = token
            self._bot_id = bot_id
            self._login_user = str(fields.get("ilink_user_id") or "")
            self.client.token = token
            self.client.baseurl = base
            self._enter_online_locked()
            self._save_locked()
            return "online"
        self._status = "error"
        self._error = "微信登录状态无法确认，请重新扫码。"
        self._phase = "idle"
        self._qr_image = ""
        return "stop"

    def _enter_online_locked(self):
        self._phase = "online"
        self._status = "connected"
        self._error = ""
        self._qr_image = ""
        self._qrcode = ""
        self._verify_code = ""

    def _token_rejected(self, code, body):
        if result_code(body) == -14 or code == 401:
            with self._lock:
                self._token = ""
                self.client.token = ""
                self._peers = {}
                self._peer_user = ""
                self._buf = ""
                self._phase = "idle"
                self._status = "error"
                self._error = "微信登录已失效，请重新扫码添加 MediX。"
                self._qr_image = ""
                self._save_locked()
            logger.warning("WeChat token rejected")
            return True
        return False

    def _typing(self, user, token, status):
        try:
            if status == 1:
                code, body = self.client.get_config(user, token)
                if code == 200 and isinstance(body, dict) and body.get("typing_ticket"):
                    self._tickets[user] = body["typing_ticket"]
            ticket = self._tickets.get(user) or ""
            if ticket:
                self.client.send_typing(user, ticket, status)
        except Exception:
            return

    def _send_plain(self, user, token, text):
        if not user or not token or not str(text or "").strip():
            return False
        self._typing(user, token, 1)
        try:
            for chunk in text_chunks(text):
                sent = False
                for _attempt in range(2):
                    try:
                        code, body = self.client.send_text(user, token, chunk)
                    except Exception:
                        code, body = "network", None
                    if self._token_rejected(code, body):
                        return False
                    if code == 200 and result_code(body) in (0, None):
                        with self._lock:
                            self._note_out_locked(user, chunk)
                        sent = True
                        break
                if not sent:
                    return False
            return True
        finally:
            self._typing(user, token, 2)

    def _note_out_locked(self, user, text):
        now = time.monotonic()
        self._outgoing = [item for item in self._outgoing if item[0] > now]
        self._outgoing.append((now + 60, user, fingerprint(user, text)))
        del self._outgoing[:-200]

    def _publish(self, role, text, expected_owner=None):
        with self._lock:
            if expected_owner is not None and self.owner != expected_owner:
                return
            self._seq += 1
            self._events.append({"id": self._seq, "role": role, "text": str(text)[:4000], "origin": "wechat"})
            del self._events[:-80]

    def _notify_start(self):
        if not self.client.token:
            return
        try:
            self.client.notify_start()
        except Exception:
            logger.warning("WeChat start notice failed")

    def _notify_stop(self):
        if not self.client.token:
            return
        try:
            self.client.notify_stop()
        except Exception:
            logger.warning("WeChat stop notice failed")

    def _wipe_locked(self):
        if self.database_backed:
            from messenger import clear_channel_state
            clear_channel_state("wechat", self.owner)
        self._token = ""
        self.client.token = ""
        self._bot_id = ""
        self._login_user = ""
        self._buf = ""
        self._peers = {}
        self._peer_user = ""
        self._qrcode = ""
        self._qr_image = ""
        self._verify_code = ""
        self._outgoing.clear()
        self._seen.clear()
        self._events.clear()
        self._tickets.clear()
        self.owner = ""
        self._phase = "idle"
        self._status = "idle"
        self._error = ""
        path = Path(self.path)
        if not self.database_backed and path.exists():
            path.unlink()
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break

    def _save_locked(self):
        path = Path(self.path)
        if not self.database_backed:
            path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "bot_token": self._token,
            "baseurl": self.client.baseurl,
            "ilink_bot_id": self._bot_id,
            "ilink_user_id": self._login_user,
            "owner_browser": self.owner,
            "get_updates_buf": self._buf,
            "peers": self._peers,
            "peer_user": self._peer_user,
        }
        if self.database_backed:
            from messenger import save_channel_state
            save_channel_state("wechat", self.owner, payload)
            return
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _load(self):
        if self.database_backed:
            from messenger import load_channel_state
            payload = load_channel_state("wechat")
        else:
            path = Path(self.path)
            if not path.exists():return
            try:payload=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,json.JSONDecodeError):return
        if not isinstance(payload, dict):
            return
        token = str(payload.get("bot_token") or "")
        base = allowed_https_base(payload.get("baseurl")) or self.client.baseurl
        peers = payload.get("peers") if isinstance(payload.get("peers"), dict) else {}
        clean_peers = {str(key): str(value) for key, value in peers.items() if key and value}
        with self._lock:
            self._token = token
            self.client.token = token
            self.client.baseurl = base
            self._bot_id = str(payload.get("ilink_bot_id") or "")
            self._login_user = str(payload.get("ilink_user_id") or "")
            self.owner = str(payload.get("owner_browser") or "")
            self._buf = str(payload.get("get_updates_buf") or "")
            self._peers = clean_peers
            self._peer_user = str(payload.get("peer_user") or "")
            if token and self.owner:
                self._phase = "online"
                self._status = "connected"
            else:
                self._phase = "idle"
                self._status = "idle"


_bridge = None
_bridge_lock = threading.Lock()


def get_bridge():
    global _bridge
    with _bridge_lock:
        from storage.business import database_url
        path = "database:" + database_url()
        if _bridge is None or _bridge.path != path:
            if _bridge is not None:
                _bridge.stop()
            _bridge = WeChatBridge(path)
            _bridge.database_backed = True
            _bridge._load()
        return _bridge


def reset_bridge():
    global _bridge
    with _bridge_lock:
        if _bridge is not None:
            _bridge.stop()
            _bridge = None
