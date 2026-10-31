"""Start the local SnowLuma install and surface QQ's login QR in MediX.

SnowLuma stays where the user downloaded it. MediX only launches that copy,
hooks the desktop QQ process, and reads the OneBot ports SnowLuma opens
(HTTP 3000 and WebSocket 3001).
"""
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

from .onebot import loopback_url

ROOT = Path(__file__).resolve().parents[1]
WEBUI = "http://127.0.0.1:5099"


def install_dir():
    override = os.environ.get("MEDIX_SNOWLUMA_HOME")
    if override:
        return Path(override)
    pointer = ROOT / "data" / "snowluma_home.txt"
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text)
    return None


def runtime_dir():
    override = os.environ.get("MEDIX_SNOWLUMA_RUNTIME")
    return Path(override) if override else ROOT / "data" / "snowluma"


def read_endpoints(payload):
    """Return loopback OneBot URLs and tokens from a SnowLuma onebot config."""
    networks = payload.get("networks") if isinstance(payload, dict) else None
    if not isinstance(networks, dict):
        return None
    http = _enabled(networks.get("httpServers"))
    ws = _enabled(networks.get("wsServers"))
    if not http or not ws:
        return None
    http_url = loopback_url(f"http://{http.get('host') or '127.0.0.1'}:{http.get('port')}", {"http"})
    ws_url = loopback_url(f"ws://{ws.get('host') or '127.0.0.1'}:{ws.get('port')}", {"ws"})
    if not http_url or not ws_url:
        return None
    return {
        "http": http_url,
        "ws": ws_url,
        "http_token": str(http.get("accessToken") or ""),
        "ws_token": str(ws.get("accessToken") or ""),
    }


def _enabled(items):
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("enabled") is not False and item.get("port"):
            return item
    return None


class SnowLumaHost:
    def __init__(self, install=None, runtime=None, capture=None, opener=None):
        chosen = install or install_dir()
        self.install = Path(chosen) if chosen else None
        self.runtime = Path(runtime or runtime_dir())
        self.capture = capture or capture_qq_png
        self.opener = opener or launch_qq
        self._process = None
        self._token = ""

    def prepare(self, cancelled, on_qr):
        if self.install is None or not (self.install / "index.mjs").is_file():
            raise RuntimeError("没有找到本机 SnowLuma。请设置 MEDIX_SNOWLUMA_HOME。")
        self._ensure_running()
        if cancelled():
            raise RuntimeError("已取消")
        self._api("POST", "/api/login", {"password": self._password()})
        self._wait_until_online(cancelled, on_qr)
        uin = self._online_uin()
        endpoints = self._wait_endpoints(uin, cancelled)
        if not endpoints:
            raise RuntimeError("QQ 已登录，但 OneBot 端口还没有打开。")
        endpoints["uin"] = uin
        return endpoints

    def resume(self):
        """Reconnect OneBot when this QQ is already logged in. Does not wait for a new scan."""
        if self.install is None or not (self.install / "index.mjs").is_file():
            return None
        self._ensure_running()
        self._api("POST", "/api/login", {"password": self._password()})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            processes = self._processes()
            online = next((item for item in processes if item.get("loggedIn") or item.get("status") == "online"), None)
            if online:
                uin = str(online.get("uin") or "")
                if not uin.isdigit() or uin == "0":
                    uin = self._online_uin()
                return self._wait_endpoints(uin, lambda: False)
            target = self._pick_process(processes)
            if target and not target.get("injected"):
                self._api("POST", f"/api/processes/{int(target['pid'])}/load", {})
            elif not processes:
                return None
            time.sleep(1)
        return None

    def _ensure_running(self):
        if self._healthy():
            return
        self.runtime.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "SNOWLUMA_WEBUI_HOST": "127.0.0.1",
            "SNOWLUMA_WEBUI_PORT": "5099",
            "SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD": self._password(),
            "SNOWLUMA_ACCEPT_EULA": "1",
            "SNOWLUMA_ACCEPT_PRIVACY": "1",
        })
        log_path = self.runtime / "snowluma.log"
        log_file = open(log_path, "ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                [os.environ.get("MEDIX_SNOWLUMA_NODE") or "node", str(self.install / "index.mjs")],
                cwd=str(self.runtime),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("没有找到 Node.js，无法启动 SnowLuma。") from exc
        finally:
            log_file.close()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError("SnowLuma 启动后退出了，请查看 data/snowluma/snowluma.log。")
            if self._healthy():
                return
            time.sleep(0.4)
        raise RuntimeError("SnowLuma 没有在本机 5099 端口就绪。")

    def _healthy(self):
        status, _body = self._request("GET", "/api/ui/public", None, timeout=2)
        return status == 200

    def _password(self):
        path = self.runtime / "webui_password"
        if path.is_file():
            current = path.read_text(encoding="utf-8").strip()
            if current:
                return current
        self.runtime.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(24)
        path.write_text(generated, encoding="utf-8")
        return generated

    def _api(self, method, path, body=None):
        status, payload = self._request(method, path, body, token=self._token)
        if path == "/api/login" and isinstance(payload, dict) and payload.get("token"):
            self._token = str(payload["token"])
        if status == 401 and path != "/api/login":
            self._token = ""
            self._api("POST", "/api/login", {"password": self._password()})
            status, payload = self._request(method, path, body, token=self._token)
        if status != 200:
            message = payload.get("message") if isinstance(payload, dict) else ""
            raise RuntimeError(message or "SnowLuma 接口没有成功。")
        return payload

    def _request(self, method, path, body, token="", timeout=15):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-SnowLuma-Token"] = token
        request = urllib.request.Request(WEBUI + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except (TimeoutError, urllib.error.URLError):
            return "network", None
        if not raw:
            return status, {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {}
        return status, parsed if isinstance(parsed, dict) else {}

    def _wait_until_online(self, cancelled, on_qr):
        self._ensure_qq_process(cancelled)
        deadline = time.monotonic() + 150
        last_capture = 0
        while time.monotonic() < deadline:
            if cancelled():
                raise RuntimeError("已取消")
            processes = self._processes()
            online = next((item for item in processes if item.get("loggedIn") or item.get("status") == "online"), None)
            if online:
                return
            target = self._pick_process(processes)
            if target and not target.get("injected") and target.get("status") in {None, "available", "disconnected", "error"}:
                self._api("POST", f"/api/processes/{int(target['pid'])}/load", {})
            now = time.monotonic()
            if now - last_capture > 2:
                image = self.capture()
                if image:
                    on_qr(image)
                last_capture = now
            time.sleep(1)
        raise RuntimeError("还没有完成 QQ 扫码。请重新打开登录后再试。")

    def _ensure_qq_process(self, cancelled):
        launched = False
        for _attempt in range(10):
            if cancelled():
                raise RuntimeError("已取消")
            if self._processes():
                return
            if not launched:
                launched = bool(self.opener())
            time.sleep(1)
        if not self._processes():
            raise RuntimeError("没有找到电脑版 QQ。请先安装 QQ，或设置 MEDIX_QQ_EXE 指向 QQ.exe。")

    def _processes(self):
        payload = self._api("GET", "/api/processes", None)
        items = payload.get("list") if isinstance(payload, dict) else None
        return [item for item in items or [] if isinstance(item, dict) and item.get("pid")]

    def _pick_process(self, processes):
        for item in processes:
            if item.get("status") in {"loaded", "connecting", "online"} or item.get("injected"):
                return item
        return processes[0] if processes else None

    def _online_uin(self):
        for item in self._processes():
            if item.get("loggedIn") or item.get("status") == "online":
                uin = str(item.get("uin") or "")
                if uin.isdigit() and uin != "0":
                    return uin
        payload = self._api("GET", "/api/qq-list", None)
        for item in payload.get("list") or []:
            uin = str(item.get("uin") or "")
            if uin.isdigit():
                return uin
        raise RuntimeError("QQ 已登录，但没有读到账号。")

    def _wait_endpoints(self, uin, cancelled):
        path = self.runtime / "config" / f"onebot_{uin}.json"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cancelled():
                raise RuntimeError("已取消")
            if path.is_file():
                try:
                    found = read_endpoints(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    found = None
                if found:
                    return found
            time.sleep(0.5)
        return None


def launch_qq():
    exe = find_qq_exe()
    if not exe:
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([exe], close_fds=True, creationflags=flags)
    return True


def find_qq_exe():
    override = os.environ.get("MEDIX_QQ_EXE")
    if override and Path(override).is_file():
        return override
    roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LOCALAPPDATA", "")]
    relatives = [Path("Tencent") / "QQNT" / "QQ.exe", Path("Tencent") / "QQ" / "QQ.exe"]
    for root in roots:
        if not root:
            continue
        for relative in relatives:
            candidate = Path(root) / relative
            if candidate.is_file():
                return str(candidate)
    return ""


def capture_qq_png():
    if os.name != "nt":
        return None
    try:
        return _capture_qq_png()
    except Exception:
        logger.warning("QQ window capture failed")
        return None


def _is_qq_window(hwnd):
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    if not process:
        return False
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            return False
        expected = find_qq_exe()
        return os.path.normcase(path.value) == os.path.normcase(expected) if expected else Path(path.value).name.lower() == 'qq.exe'
    finally:
        kernel32.CloseHandle(process)


def _capture_qq_png():
    import ctypes
    from ctypes import wintypes
    from io import BytesIO
    from PIL import ImageGrab
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return 1
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return 1
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if "QQ" not in title or "MediX" in title or not _is_qq_window(hwnd):
            return 1
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return 1
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        # The QQ main chat window is not a QR login window. Do not expose
        # its private conversations as a supposed login image.
        if width < 180 or height < 180 or width > 650:
            return 1
        score = width * height + (500000 if "登录" in title else 0)
        found.append((score, hwnd, width, height))
        return 1

    user32.EnumWindows(visit, 0)
    if not found:
        return None
    _score, hwnd, width, height = max(found)
    try:
        # Capture the QQ window itself, even when another app covers its screen area.
        # Never fall back to a desktop rectangle, which could expose other apps.
        image = ImageGrab.grab(window=hwnd)
        width, height = image.size
    except Exception:
        logger.warning("QQ window capture failed")
        return None
    if width > 560:
        side = int(min(width, height) * 0.62)
        crop_left = max(0, (width - side) // 2)
        crop_top = max(0, int(height * 0.12))
        image = image.crop((crop_left, crop_top, min(width, crop_left + side), min(height, crop_top + side)))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
