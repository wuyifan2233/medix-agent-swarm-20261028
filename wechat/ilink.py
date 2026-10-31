"""Minimal client for the WeChat iLink bot API.

The phone scans a QR code and adds the bot. This module only logs in, receives
private text, and sends text back. It does not read the desktop WeChat database.
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.6"
CLIENT_VERSION = "132102"
BOT_AGENT = "MediX/1.0.0 (python)"


def wechat_uin():
    number = int.from_bytes(os.urandom(4), "big")
    return base64.b64encode(str(number).encode("ascii")).decode("ascii")


def result_code(body):
    if not isinstance(body, dict):
        return None
    for key in ("ret", "errcode"):
        value = body.get(key)
        if value in (None, 0, "0"):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1
    return 0


def login_fields(body):
    if not isinstance(body, dict):
        return {}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    credentials = data.get("credentials") if isinstance(data.get("credentials"), dict) else {}
    merged = dict(data)
    for key, value in credentials.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def allowed_https_base(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        return ""
    if host != "weixin.qq.com" and not host.endswith(".weixin.qq.com"):
        return ""
    return "https://" + host


def text_chunks(text, limit=1400, parts=3):
    rest = str(text or "").strip()
    if not rest:
        return []
    if len(rest) <= limit or parts <= 1:
        if len(rest) > limit:
            return [rest[: limit - 1].rstrip() + "…"]
        return [rest]
    chunks = []
    while rest and len(chunks) < parts - 1:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        piece = rest[:cut].strip()
        rest = rest[cut:].strip()
        if piece:
            chunks.append(piece)
    if rest:
        if len(rest) > limit:
            rest = rest[: limit - 1].rstrip() + "…"
        chunks.append(rest)
    return chunks


class UrllibTransport:
    def __call__(self, method, url, body, headers, timeout):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except TimeoutError:
            return "timeout", None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return "timeout", None
            return "network", None
        if not raw:
            return status, {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {}
        return status, parsed if isinstance(parsed, dict) else {}


class ILinkClient:
    def __init__(self, transport=None):
        self.transport = transport or UrllibTransport()
        self.baseurl = DEFAULT_BASE
        self.token = ""
        self.poll_seconds = 35

    def _headers(self, authorized):
        headers = {
            "Content-Type": "application/json",
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": CLIENT_VERSION,
            "X-WECHAT-UIN": wechat_uin(),
        }
        if authorized and self.token:
            headers["AuthorizationType"] = "ilink_bot_token"
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _post(self, path, payload, timeout):
        body = dict(payload)
        body["base_info"] = {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}
        return self.transport("POST", self.baseurl.rstrip("/") + path, body, self._headers(True), timeout)

    def get_qrcode(self, local_tokens):
        tokens = [item for item in local_tokens if item][:10]
        return self.transport(
            "POST",
            DEFAULT_BASE + "/ilink/bot/get_bot_qrcode?bot_type=3",
            {"local_token_list": tokens},
            self._headers(False),
            20)

    def qr_status(self, qrcode, verify_code, base):
        root = allowed_https_base(base) or DEFAULT_BASE
        query = urllib.parse.urlencode({"qrcode": qrcode, **({"verify_code": verify_code} if verify_code else {})})
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": CLIENT_VERSION}
        return self.transport("GET", root + "/ilink/bot/get_qrcode_status?" + query, None, headers, self.poll_seconds + 5)

    def get_updates(self, buf):
        status, body = self._post("/ilink/bot/getupdates", {"get_updates_buf": buf or ""}, self.poll_seconds + 5)
        if isinstance(body, dict):
            try:
                suggested = int(body.get("longpolling_timeout_ms") or 0)
            except (TypeError, ValueError):
                suggested = 0
            if suggested > 0:
                self.poll_seconds = min(max(suggested / 1000, 5), 60)
        return status, body

    def get_config(self, user_id, context_token):
        return self._post("/ilink/bot/getconfig", {
            "ilink_user_id": user_id, "context_token": context_token}, 10)

    def send_typing(self, user_id, ticket, status):
        return self._post("/ilink/bot/sendtyping", {
            "ilink_user_id": user_id, "typing_ticket": ticket, "status": status}, 10)

    def send_text(self, user_id, context_token, text):
        return self._post("/ilink/bot/sendmessage", {"msg": {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": "medix-" + os.urandom(8).hex(),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }}, 15)

    def notify_start(self):
        return self._post("/ilink/bot/msg/notifystart", {}, 10)

    def notify_stop(self):
        return self._post("/ilink/bot/msg/notifystop", {}, 5)
