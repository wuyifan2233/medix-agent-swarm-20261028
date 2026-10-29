"""Load the supplied config without saving credentials in the project."""
import ast
import os
from pathlib import Path

source = Path(os.environ.get("MEDIX_CONFIG_PATH", "D:/AI training/config.py"))
settings = {}
if source.is_file():
    for node in ast.parse(source.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"LLM_CONFIG", "MEM0_CONFIG"}:
                    settings[target.id] = ast.literal_eval(node.value)

LLM_CONFIG = dict(settings.get("LLM_CONFIG", {}))
if os.environ.get("OPENAI_API_KEY"):
    LLM_CONFIG.update(api_key=os.environ["OPENAI_API_KEY"],
                      model_name=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                      base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
else:
    LLM_CONFIG["api_key"] = os.environ.get("ARK_API_KEY") or LLM_CONFIG.get("api_key") or "not-configured"
LLM_CONFIG.setdefault("model_name", "gpt-4.1-mini")
LLM_CONFIG.setdefault("base_url", "https://api.openai.com/v1")
LLM_CONFIG.setdefault("temperature", 0.7)
LLM_CONFIG.setdefault("max_tokens", 2048)
MEM0_CONFIG = dict(settings.get("MEM0_CONFIG", {}))
MEM0_CONFIG["api_key"] = os.environ.get("MEM0_API_KEY") or MEM0_CONFIG.get("api_key", "")
