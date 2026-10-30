"""Cross-platform, loopback-only browser entry point."""
import argparse
import errno
import importlib.util
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def configure_database(port, explicit_path=None):
    """Web instances on different ports must not share a Milvus Lite lock."""
    import runtime_paths
    selected = explicit_path or os.environ.get('MEDIX_DB_PATH')
    if not selected:
        selected = Path(runtime_paths.DEFAULT_DB_PATH).with_name(f'web-{port}-milvus.db')
    path = str(Path(selected).expanduser().resolve())
    os.environ['MEDIX_DB_PATH'] = path
    # runtime_paths was imported to obtain the default, so keep its exported
    # value consistent before the knowledge modules import DB_PATH from it.
    runtime_paths.DB_PATH = path
    return path


def main():
    parser = argparse.ArgumentParser(description="启动 MediX 本机网页聊天")
    parser.add_argument("--port", type=int, default=8744, help="本地端口（默认 %(default)s）")
    parser.add_argument("--db-path", help="独立的 Milvus 数据目录，避免与其他实例争用数据库")
    parser.add_argument("--open", action="store_true", help="启动后打开默认浏览器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 到 65535 之间")
    required = {"fastapi": "fastapi", "uvicorn": "uvicorn", "PIL": "pillow",
                "loguru": "loguru", "pymilvus": "pymilvus", "sentence_transformers": "sentence-transformers"}
    missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
    if missing:
        parser.exit(1, "缺少依赖：" + ", ".join(missing) + '\n请在项目目录运行：python -m pip install -r requirements.web.txt\n')
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", args.port))
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EPERM}:
            parser.exit(1, "当前执行环境不允许监听本机端口，请在本机终端启动或申请执行权限。\n")
        parser.exit(1, f"无法监听端口 {args.port}；请关闭旧实例或使用 --port 指定其他端口。\n")
    os.chdir(ROOT)
    database_path = configure_database(args.port,args.db_path)
    os.environ.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    from loguru import logger
    import uvicorn
    logger.remove()
    logger.add(sys.stderr, level="WARNING", filter=lambda record: record["name"].startswith("web."),
               format="{time:HH:mm:ss} | {level} | {message}")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"MediX 网页聊天：{url}\n知识库目录：{database_path}\n保持此终端运行，按 Ctrl+C 停止。", flush=True)
    if args.open:
        timer = threading.Timer(1.5, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run("web.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
