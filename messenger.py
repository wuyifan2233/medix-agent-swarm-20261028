"""Which phone app currently receives MediX replies and reminders."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def channel_path():
    override = os.environ.get("MEDIX_CHANNEL_PATH")
    if override:
        return Path(override)
    return ROOT / "data" / "messenger.json"


def current_channel():
    forced = os.environ.get("MEDIX_CHANNEL")
    if forced in {"wechat", "qq"}:
        return forced
    path = channel_path()
    if not path.exists():
        return "wechat"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "wechat"
    name = payload.get("channel") if isinstance(payload, dict) else ""
    return name if name in {"wechat", "qq"} else "wechat"


def set_channel(name):
    if name not in {"wechat", "qq"}:
        raise ValueError("请选择微信或 QQ。")
    path = channel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"channel": name}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return name
