"""Run the local web chat. Credentials are read from the existing config/env."""
import os
import sys
from pathlib import Path
import uvicorn
from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HOME", str(ROOT.parent / ".medix-model-cache"))
os.chdir(ROOT)

if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="WARNING", filter=lambda record: record["name"].startswith(("web.", "wechat.", "qq.")),
               format="{time:HH:mm:ss} | {level} | {message}")
    print("MediX 网页聊天：http://127.0.0.1:8765", flush=True)
    uvicorn.run("web.app:app", host="127.0.0.1", port=8765, log_level="warning")
