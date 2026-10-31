"""Load external configuration and ignored local defaults without exposing keys."""
import ast
import os
from pathlib import Path
from urllib.parse import urlsplit
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
# ASR uses its own audio endpoint; Edge cloud TTS never uses text-model credentials.
_audio_key_override = os.environ.get("MEDIX_AUDIO_API_KEY")
_audio_base_override = os.environ.get("MEDIX_AUDIO_BASE_URL")
_audio_base = _audio_base_override or (
    "https://api.openai.com/v1" if _audio_key_override else LLM_CONFIG.get("base_url", "")
)
_text_base = str(LLM_CONFIG.get("base_url", "")).rstrip("/")
_audio_same_text_endpoint = _audio_base.rstrip("/") == _text_base
_audio_key = _audio_key_override or (LLM_CONFIG.get("api_key", "") if _audio_same_text_endpoint else "")
_uses_openai_audio = urlsplit(_audio_base).hostname == "api.openai.com"
_audio_configured = bool(_audio_key not in {None, "", "not-configured"}
                         and (_audio_key_override or _uses_openai_audio))
SPEECH_CONFIG = {
    "api_key": _audio_key,
    "base_url": _audio_base,
    "remote_enabled": _audio_configured,
    "transcription_model": os.environ.get("MEDIX_TRANSCRIBE_MODEL", "gpt-transcribe"),
    "transcription_language": os.environ.get("MEDIX_TRANSCRIBE_LANGUAGE", "zh"),
    "tts_provider": os.environ.get("MEDIX_TTS_PROVIDER", "edge").strip().lower(),
    "tts_voice": os.environ.get("MEDIX_TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
    "tts_rate": os.environ.get("MEDIX_TTS_RATE", "-5%"),
    "tts_pitch": os.environ.get("MEDIX_TTS_PITCH", "+0Hz"),
    "tts_volume": os.environ.get("MEDIX_TTS_VOLUME", "+0%"),
    "max_audio_bytes": max(1, min(int(os.environ.get("MEDIX_MAX_AUDIO_BYTES", str(16 * 1024 * 1024))), 16 * 1024 * 1024)),
}
MEM0_CONFIG = dict(settings.get("MEM0_CONFIG", {}))
MEM0_CONFIG["api_key"] = os.environ.get("MEM0_API_KEY") or MEM0_CONFIG.get("api_key", "")
