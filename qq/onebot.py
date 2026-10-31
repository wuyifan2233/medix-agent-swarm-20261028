"""OneBot v11 client for a local QQ bridge such as SnowLuma.

MediX only logs in, receives private text, and sends private text.
The QQ app itself is scanned and logged in by that local bridge.
"""
import base64
import hashlib
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

def loopback_url(url, schemes):
    parsed = urllib.parse.urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in schemes or host not in {"127.0.0.1", "localhost", "::1"}:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    port = parsed.port
    if port is None or not 1 <= port <= 65535:
        return ""
    path = parsed.path or ""
    if schemes == {"ws"} and path not in {"", "/"}:
        return ""
    if host == "::1":
        netloc = f"[{host}]:{port}"
    else:
        netloc = f"{host}:{port}"
    return f"{parsed.scheme}://{netloc}"


def default_http():
    return loopback_url(os.environ.get("MEDIX_QQ_HTTP") or "http://127.0.0.1:3000", {"http"}) or ""


def default_ws():
    return loopback_url(os.environ.get("MEDIX_QQ_WS") or "ws://127.0.0.1:3001", {"ws"}) or ""


def fingerprint(user, text):
    return hashlib.sha256((str(user) + "\n" + str(text).strip()).encode("utf-8")).hexdigest()


def accept_event(event, self_id, outgoing, now):
    """Keep a new private user text. Drop groups, self sends, and recent echoes."""
    if not isinstance(event, dict) or event.get("post_type") != "message":
        return None
    if event.get("message_type") != "private":
        return None
    user = str(event.get("user_id") or "")
    if not user.isdigit() or (self_id and user == str(self_id)):
        return None
    text, had_item = _event_text(event)
    if text:
        digest = fingerprint(user, text)
        if any(expiry > now and owner == user and previous == digest for expiry, owner, previous in outgoing):
            return None
    elif not had_item:
        return None
    message_id = str(event.get("message_id") or "")
    if not message_id:
        message_id = fingerprint(user, text or user)
    return {"id": message_id, "user": user, "text": text[:8000], "media": not bool(text)}


def _event_text(event):
    message = event.get("message")
    if isinstance(message, str):
        text = message.strip()
        return text, bool(text)
    if isinstance(message, list):
        parts = []
        had_item = False
        for item in message:
            if not isinstance(item, dict):
                continue
            had_item = True
            if item.get("type") == "text":
                data = item.get("data") if isinstance(item.get("data"), dict) else {}
                piece = str(data.get("text") or "").strip()
                if piece:
                    parts.append(piece)
        return "\n".join(parts).strip(), had_item
    raw = str(event.get("raw_message") or "").strip()
    return raw, bool(raw)


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


def action_ok(status, body):
    return status == 200 and isinstance(body, dict) and body.get("status") == "ok" and body.get("retcode") in (0, None)


class OneBotClient:
    def __init__(self, transport=None, http_url=None, token=""):
        self.transport = transport or UrllibTransport()
        self.http_url = loopback_url(http_url or default_http(), {"http"})
        self.token = token if token is not None else os.environ.get("MEDIX_QQ_TOKEN") or ""

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _post(self, action, payload, timeout=15):
        if not self.http_url:
            return "network", None
        return self.transport("POST", self.http_url + "/" + action, payload, self._headers(), timeout)

    def get_login_info(self):
        return self._post("get_login_info", {}, 8)

    def send_private_text(self, user_id, text):
        return self._post("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "text", "data": {"text": text}}],
        })

    def get_friend_list(self):
        return self._post("get_friend_list", {})

    def get_stranger_info(self, user_id):
        return self._post("get_stranger_info", {"user_id": int(user_id)})

def run_ws(url, token, stop, on_event):
    """Read OneBot events until stop is set. Reconnects after the socket drops."""
    target = loopback_url(url, {"ws"})
    if not target:
        return
    while not stop.is_set():
        try:
            _one_socket(target, token, stop, on_event)
        except Exception:
            pass
        stop.wait(2)


def _one_socket(url, token, stop, on_event):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port
    sock = socket.create_connection((host, port), timeout=8)
    try:
        sock.settimeout(1)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        header = (
            f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n"
        )
        if token:
            header += "Authorization: Bearer " + token + "\r\n"
        header += "\r\n"
        sock.sendall(header.encode("ascii"))
        opening = b""
        while b"\r\n\r\n" not in opening:
            if stop.is_set():
                return
            chunk = _recv_some(sock)
            if not chunk:
                return
            opening += chunk
            if len(opening) > 8192:
                return
        if b" 101 " not in opening.split(b"\r\n", 1)[0]:
            return
        buffer = opening.split(b"\r\n\r\n", 1)[1]
        while not stop.is_set():
            frame, buffer = _read_frame(sock, buffer)
            if frame is None:
                continue
            opcode, payload = frame
            if opcode == 8:
                return
            if opcode == 9:
                _send_frame(sock, 10, payload)
                continue
            if opcode == 1:
                try:
                    event = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(event, dict):
                    on_event(event)
    finally:
        try:
            sock.close()
        except OSError:
            pass


class _NeedMore(Exception):
    def __init__(self, buffer):
        self.buffer = buffer


def _recv_some(sock):
    try:
        return sock.recv(65536)
    except TimeoutError:
        return None


def _read_exact(sock, buffer, size):
    while len(buffer) < size:
        chunk = _recv_some(sock)
        if chunk is None:
            raise _NeedMore(buffer)
        if chunk == b"":
            raise ConnectionError("closed")
        buffer += chunk
    return buffer[:size], buffer[size:]


def _read_frame(sock, buffer):
    try:
        header, buffer = _read_exact(sock, buffer, 2)
    except _NeedMore as paused:
        return None, paused.buffer
    opcode = header[0] & 15
    masked = bool(header[1] & 0x80)
    length = header[1] & 127
    if length == 126:
        extra, buffer = _read_exact(sock, buffer, 2)
        length = int.from_bytes(extra, "big")
    elif length == 127:
        extra, buffer = _read_exact(sock, buffer, 8)
        length = int.from_bytes(extra, "big")
    if length > 1024 * 1024:
        raise ConnectionError("frame too large")
    mask = b""
    if masked:
        mask, buffer = _read_exact(sock, buffer, 4)
    payload, buffer = _read_exact(sock, buffer, length)
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return (opcode, payload), buffer


def _send_frame(sock, opcode, payload):
    body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(body))
    header = bytes([0x80 | opcode, 0x80 | len(body)])
    if len(body) >= 126:
        header = bytes([0x80 | opcode, 0x80 | 126]) + len(body).to_bytes(2, "big")
    sock.sendall(header + mask + masked)
