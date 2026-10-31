"""Machine-local NapCat bootstrap. No QQ accounts or credentials belong in Git."""
import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.18.41"
URL = f"https://github.com/NapNeko/NapCatQQ/releases/download/v{VERSION}/NapCat.Shell.Windows.Node.zip"
SHA256 = "51fbb10e7bcd56b0c2a6de86c37811e7518330e48a137ac689ab1e4d8627d3f0"
DATA_PATH_LINE = b"let e = t.NodeQQNTWrapperUtil.getNTUserDataInfoConfig();"
ISOLATED_DATA_LINE = b"let e = process.env.MEDIX_NAPCAT_QQ_DATA || t.NodeQQNTWrapperUtil.getNTUserDataInfoConfig();"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def prepare(home, archive=None, proxy=None):
    """Download a pinned official package, verify it, then isolate its QQ data path."""
    receipt = home / "medix-package.json"
    if not (receipt.is_file() and read_json(receipt).get("sha256") == SHA256):
        if home.exists() and any(home.iterdir()):
            raise RuntimeError("目标安装目录不是已校验的 MediX NapCat 目录，请选择空目录。")
        cache = ROOT / "data" / "downloads" / f"NapCat-{VERSION}-Windows.Node.zip"
        package = Path(archive) if archive else cache
        if not package.is_file():
            package.parent.mkdir(parents=True, exist_ok=True)
            download = package.with_suffix(".download")
            # requests uses a verified CA bundle and supports HTTPS_PROXY / HTTP_PROXY.
            import requests
            options = {"https": proxy, "http": proxy} if proxy else None
            print(f"首次下载官方 NapCat {VERSION}（约118 MB）…", flush=True)
            try:
                with requests.get(URL, stream=True, timeout=(30, 90), proxies=options) as response:
                    response.raise_for_status()
                    with download.open("wb") as output:
                        for chunk in response.iter_content(1024 * 1024):
                            output.write(chunk)
                download.replace(package)
            finally:
                download.unlink(missing_ok=True)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        if digest != SHA256:
            raise RuntimeError("NapCat 安装包 SHA256 校验失败，未解压或运行。请重新下载官方包。")
        home.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="napcat-install-", dir=home.parent) as temporary:
            staging = Path(temporary) / "package"
            staging.mkdir()
            with zipfile.ZipFile(package) as bundle:
                if sum(item.file_size for item in bundle.infolist()) > 1024 ** 3:
                    raise RuntimeError("安装包解压大小异常。")
                for item in bundle.infolist():
                    target = (staging / item.filename).resolve()
                    if not target.is_relative_to(staging.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError("安装包包含不安全路径或符号链接。")
                bundle.extractall(staging)
            # The official standalone package otherwise reuses Documents/Tencent Files.
            script = staging / "napcat" / "napcat.mjs"
            original = script.read_bytes()
            if original.count(DATA_PATH_LINE) != 1:
                raise RuntimeError("官方包的数据目录接口与已验证版本不一致，未启动。")
            script.with_suffix(".mjs.official").write_bytes(original)
            script.write_bytes(original.replace(DATA_PATH_LINE, ISOLATED_DATA_LINE))
            write_json(staging / receipt.name, {"version": VERSION, "sha256": SHA256, "source": URL})
            if home.exists():
                home.rmdir()  # Only the verified-empty target, never a recursive removal.
            staging.replace(home)
    for name in ("node.exe", "index.js", "wrapper.node", "napcat/napcat.mjs"):
        if not (home / name).is_file():
            raise RuntimeError(f"NapCat 安装不完整，缺少 {name}。")
    return home


def local_settings(runtime, web_port=6099, http_port=3000, ws_port=3001):
    if len({web_port, http_port, ws_port}) != 3 or any(not 1 <= p <= 65535 for p in (web_port, http_port, ws_port)):
        raise ValueError("WebUI、HTTP、WebSocket 端口必须不同且在1–65535之间。")
    path = runtime / "connection.json"
    config = read_json(path)
    for key in ("web_token", "http_token", "ws_token"):
        config.setdefault(key, secrets.token_urlsafe(32))
    config.update(web_port=web_port, http_port=http_port, ws_port=ws_port)
    write_json(path, config)
    webui = runtime / "config" / "webui.json"
    ui = read_json(webui)
    ui.update(host="127.0.0.1", port=web_port, token=config["web_token"])
    write_json(webui, ui)
    (runtime / "qq-data").mkdir(exist_ok=True)
    return config


class LocalAPI:
    def __init__(self, settings):
        self.settings = settings
        self.credential = ""
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path, data, authenticated=True):
        if authenticated and not self.credential:
            hashed = hashlib.sha256((self.settings["web_token"] + ".napcat").encode()).hexdigest()
            result = self.post("/auth/login", {"hash": hashed}, authenticated=False)
            self.credential = result["Credential"]
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.credential
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.settings['web_port']}/api{path}",
            data=json.dumps(data).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=12) as response:
                result = json.load(response)
        except urllib.error.HTTPError:
            self.credential = ""
            raise RuntimeError("本机 NapCat 管理接口认证失败，请检查是否有其他实例占用端口。") from None
        if result.get("code") != 0:
            self.credential = ""
            # Do not surface response bodies: they may contain credentials or accounts.
            raise RuntimeError("本机 NapCat 操作未成功，请查看本机日志。")
        return result.get("data")


def onebot_config(existing, settings):
    network = existing.setdefault("network", {})
    network["httpServers"] = [{"name": "medix-http", "enable": True, "host": "127.0.0.1",
        "port": settings["http_port"], "enableCors": False, "enableWebsocket": False,
        "messagePostFormat": "array", "token": settings["http_token"], "debug": False}]
    network["websocketServers"] = [{"name": "medix-ws", "enable": True, "host": "127.0.0.1",
        "port": settings["ws_port"], "messagePostFormat": "array", "reportSelfMessage": False,
        "token": settings["ws_token"], "enableForcePushEvent": True, "heartInterval": 5000, "debug": False}]
    return existing


def publish_env(runtime, settings):
    values = {"MEDIX_QQ_BACKEND": "onebot", "MEDIX_QQ_HTTP": f"http://127.0.0.1:{settings['http_port']}",
              "MEDIX_QQ_WS": f"ws://127.0.0.1:{settings['ws_port']}",
              "MEDIX_QQ_TOKEN": settings["http_token"], "MEDIX_QQ_WS_TOKEN": settings["ws_token"]}
    path = runtime / "medix.env"
    temporary = path.with_suffix(".env.tmp")
    temporary.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    temporary.replace(path)


def login_page(runtime, status, ready=False):
    qr = runtime / "cache" / "qrcode.png"
    image = ""
    if not ready and qr.is_file():
        image = '<img alt="QQ登录二维码" src="data:image/png;base64,' + base64.b64encode(qr.read_bytes()).decode() + '">'
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    page += '<meta http-equiv="refresh" content="5"><title>MediX QQ 连接</title><style>body{font:16px system-ui;background:#f5f6fb;color:#283349;display:grid;place-items:center;min-height:95vh;margin:0}main{background:white;padding:32px;border-radius:20px;text-align:center;width:min(380px,80vw)}img{display:block;width:240px;max-width:100%;margin:24px auto}p{line-height:1.7}small{color:#64748b}</style>'
    page += '<main><h2>MediX QQ 连接</h2><p>' + html.escape(status) + '</p>' + image
    page += '<small>使用机器人 QQ 扫码并在手机确认。<br>同账号的电脑版 QQ 请先退出。<br>本页每5秒刷新，无需填写令牌。</small></main></html>'
    (runtime / "login.html").write_text(page, encoding="utf-8")


def listening(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def supervise(home, runtime, settings):
    # Windows releases this lock even if the supervisor is interrupted.
    import msvcrt
    with (runtime / "supervisor.lock").open("a+b") as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        try:
            _run_supervisor(home, runtime, settings)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _run_supervisor(home, runtime, settings):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = os.environ.copy()
    environment.update(NAPCAT_WORKDIR=str(runtime), MEDIX_NAPCAT_QQ_DATA=str(runtime / "qq-data"), NAPCAT_DISABLE_TIME_SYNC="1")
    command = [str(home / "node.exe"), str(home / "index.js")]
    account = read_json(runtime / "account.json").get("uin", "")
    if str(account).isdigit():
        command += ["-q", str(account)]
    with (runtime / "runtime.log").open("ab") as log:
        child = subprocess.Popen(command, cwd=home, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        write_json(runtime / "processes.json", {"supervisor_pid": os.getpid(), "node_pid": child.pid})
        api = LocalAPI(settings)
        configured_account = ""
        last_qr_refresh = time.monotonic()
        while child.poll() is None:
            try:
                state = api.post("/QQLogin/CheckLoginStatus", {})
                if state.get("isLogin") and state.get("coreReady"):
                    info = api.post("/QQLogin/GetQQLoginInfo", {})
                    account = str(info.get("uin") or info.get("user_id") or "")
                    if not account.isdigit():
                        raise RuntimeError("QQ 未返回可用的账号信息。")
                    if configured_account != account:
                        current = api.post("/OB11Config/GetConfig", {})
                        if isinstance(current, str):
                            current = json.loads(current)
                        if not isinstance(current, dict):
                            raise RuntimeError("OneBot 配置格式不可用。")
                        api.post("/OB11Config/SetConfig", {"config": json.dumps(onebot_config(current, settings))})
                        write_json(runtime / "account.json", {"uin": account})
                        publish_env(runtime, settings)
                        configured_account = account
                    login_page(runtime, "QQ 已在线。请启动或重启 MediX，在聊天渠道中连接 QQ 并绑定好友。", ready=True)
                else:
                    configured_account = ""
                    if state.get("loginPhase") == "waiting_qrcode" and time.monotonic() - last_qr_refresh > 90:
                        api.post("/QQLogin/RefreshQRcode", {})
                        last_qr_refresh = time.monotonic()
                    message = "请用机器人 QQ 扫码，在手机确认登录。"
                    if state.get("loginError"):
                        message = "QQ 登录未完成；若提示重复登录，请退出同账号电脑版 QQ，再重新扫码。"
                    login_page(runtime, message)
            except Exception:
                login_page(runtime, "正在连接 QQ 服务；若长时间未就绪，请检查 data/napcat/runtime.log。")
            time.sleep(3)
    login_page(runtime, "QQ 服务已退出，请重新运行 start_qq.ps1，并检查本机 runtime.log。")


def main():
    parser = argparse.ArgumentParser(description="MediX QQ 自动准备和启动（Windows）")
    parser.add_argument("--home", type=Path, default=ROOT / "data" / "tools" / f"NapCat-{VERSION}-win-node")
    parser.add_argument("--runtime", type=Path, default=ROOT / "data" / "napcat")
    parser.add_argument("--archive", type=Path, help="可选：已下载的官方 Windows.Node ZIP，仍强制校验")
    parser.add_argument("--proxy", help="仅用于官方包下载，例如 http://127.0.0.1:7890")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--web-port", type=int, default=6099)
    parser.add_argument("--http-port", type=int, default=3000)
    parser.add_argument("--ws-port", type=int, default=3001)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("此自动启动包仅支持 Windows x64。其他平台可连接自己的 OneBot 服务。")
    home, runtime = args.home.resolve(), args.runtime.resolve()
    if args.supervise:
        supervise(home, runtime, read_json(runtime / "connection.json"))
        return
    prepare(home, args.archive, args.proxy)
    settings = local_settings(runtime, args.web_port, args.http_port, args.ws_port)
    publish_env(runtime, settings)
    login_page(runtime, "正在启动 QQ 服务，请稍候。")
    if args.prepare_only:
        print("官方包校验、独立账号目录和本机配置已准备好。")
        return
    if listening(args.web_port):
        state = LocalAPI(settings).post("/QQLogin/CheckLoginStatus", {})
        login_page(runtime, "QQ 已在线，可以在 MediX 中连接并绑定好友。" if state.get("isLogin") else "请用机器人 QQ 扫码并确认登录。", ready=bool(state.get("isLogin")))
        print("本机 NapCat 已运行。")
        return
    for port in (args.http_port, args.ws_port):
        if listening(port):
            raise RuntimeError(f"本机端口 {port} 已被占用，未启动第二个 QQ 服务。")
    with (runtime / "bootstrap.log").open("ab") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--supervise", "--home", str(home), "--runtime", str(runtime)],
                         cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    print(f"QQ 服务已在后台启动。打开扫码页面：{runtime / 'login.html'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never include requests/urllib URLs or response bodies containing secrets.
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc), file=sys.stderr)
        else:
            print(f"QQ 启动失败（{type(exc).__name__}）。下载需联网，可使用 --proxy 或 --archive。", file=sys.stderr)
        sys.exit(1)
