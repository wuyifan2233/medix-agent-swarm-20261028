"""Load external configuration and ignored local defaults without exposing keys."""
import ast
import os
from pathlib import Path
from runtime_settings import load_setting

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

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

# Explicit selection allows local DeepSeek defaults alongside existing providers.
provider = load_setting('MEDIX_LLM_PROVIDER', 'auto').lower()
if provider not in {'auto', 'deepseek'}:
    raise ValueError('MEDIX_LLM_PROVIDER must be auto or deepseek')
deepseek_key = load_setting('DEEPSEEK_API_KEY')
if provider == 'deepseek' or (provider == 'auto' and deepseek_key and deepseek_key.lower() != 'xxx'
                             and LLM_CONFIG['api_key'] == 'not-configured'):
    LLM_CONFIG.update(
        api_key=deepseek_key if deepseek_key and deepseek_key.lower() != 'xxx' else 'not-configured',
        base_url='https://api.deepseek.com',
        model_name=load_setting('DEEPSEEK_MODEL', 'deepseek-flash'),
        max_tokens=int(load_setting('DEEPSEEK_MAX_TOKENS', '8192')),
        request_defaults={'stream': False,
                          'reasoning_effort': load_setting('DEEPSEEK_REASONING_EFFORT', 'high'),
                          'extra_body': {'thinking': {'type': load_setting('DEEPSEEK_THINKING', 'enabled')}}})
MEM0_CONFIG = dict(settings.get("MEM0_CONFIG", {}))
MEM0_CONFIG["api_key"] = load_setting("MEM0_API_KEY") or MEM0_CONFIG.get("api_key", "")

# Optional placeholder credentials must not enable cloud memory.
if str(MEM0_CONFIG.get('api_key', '')).strip().lower() == 'xxx':
    MEM0_CONFIG['api_key'] = ''
