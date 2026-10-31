"""Independent Edge cloud audio stream. No LLM keys or audio files are used."""
import asyncio
from contextlib import aclosing, suppress
import importlib
import importlib.util
from typing import Literal

from pydantic import BaseModel, ConfigDict

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

TTS_TIMEOUT_SECONDS = 60
MAX_TTS_AUDIO_BYTES = 16 * 1024 * 1024


# Only these server-owned profiles can reach the provider. No health data is used.
VOICE_PROFILES = {
    "child": {"id": "child", "label": "元气童声", "description": "清亮男童声，亲切自然",
              "voice": "zh-CN-YunxiaNeural", "rate": "-5%"},
    "gentle": {"id": "gentle", "label": "温柔陪伴", "description": "柔和女声，节奏稍慢",
               "voice": "zh-CN-XiaoxiaoNeural", "rate": "-8%"},
    "clear": {"id": "clear", "label": "清晰利落", "description": "明亮男声，节奏自然",
              "voice": "zh-CN-YunxiNeural", "rate": "+0%"},
    "steady": {"id": "steady", "label": "平和舒缓", "description": "平和女声，清晰舒缓",
               "voice": "zh-CN-XiaoyiNeural", "rate": "-3%"},
}
TONE_VOICES = {"supportive": "gentle", "direct": "clear", "neutral": "steady"}
PREVIEW_TEXT = "你好，我是 MediX。我们慢慢说，一起把最重要的事情理清楚。"


class VoicePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Literal["child", "auto", "gentle", "clear", "steady"] = "child"
    tone: Literal["supportive", "direct", "neutral"] = "neutral"


def public_voice(profile):
    return {key: profile[key] for key in ("id", "label", "description")}


def resolve_voice(config, preferences):
    """Return a request-local configuration; never modify global SPEECH_CONFIG."""
    data = preferences["data"]
    selected = {key: value for key, value in config.items() if key.startswith("tts_")}
    if not data.get("enabled"):
        return selected, {"id": "default", "label": "默认声音", "description": "未启用回答偏好，使用服务默认声音", "follows_tone": False}
    profile_id = data.get("voice_profile", "child")
    automatic = profile_id == "auto"
    if automatic:
        profile_id = TONE_VOICES[data.get("tone", "neutral")]
    profile = VOICE_PROFILES[profile_id]
    selected.update(tts_voice=profile["voice"], tts_rate=profile["rate"], tts_pitch="+0Hz")
    return selected, {**public_voice(profile), "follows_tone": automatic}


def voice_catalog(config, preferences):
    _, effective = resolve_voice(config, preferences)
    return {"profiles": [public_voice(profile) for profile in VOICE_PROFILES.values()],
            "auto_for_tone": dict(TONE_VOICES), "effective": effective,
            "enabled": preferences["data"]["enabled"], "revision": preferences["revision"]}


def tts_status(config):
    provider = config.get("tts_provider", "edge")
    return {
        "tts_configured": provider == "edge" and importlib.util.find_spec("edge_tts") is not None,
        "tts_provider": provider,
        "tts_voice": config.get("tts_voice", "zh-CN-YunxiaNeural"),
        "tts_streaming": True,
    }


def load_provider(config):
    if config.get("tts_provider", "edge") != "edge":
        raise HTTPException(503, "不支持的 TTS 服务，请配置 MEDIX_TTS_PROVIDER=edge。")
    try:
        return importlib.import_module("edge_tts")
    except ImportError as exc:
        raise HTTPException(503, "请在服务环境安装 requirements.web.txt 中的 edge-tts 依赖。") from exc


async def stream_audio(config, text):
    edge_tts = load_provider(config)
    try:
        speaker = edge_tts.Communicate(
            text, voice=config.get("tts_voice", "zh-CN-YunxiaNeural"),
            rate=config.get("tts_rate", "-5%"), pitch=config.get("tts_pitch", "+0Hz"),
            volume=config.get("tts_volume", "+0%"), connect_timeout=10, receive_timeout=30,
        )
        size = 0
        deadline = asyncio.get_running_loop().time() + TTS_TIMEOUT_SECONDS
        async with aclosing(speaker.stream()) as upstream:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    chunk = await asyncio.wait_for(anext(upstream), timeout=remaining)
                except StopAsyncIteration:
                    break
                if chunk["type"] != "audio" or not chunk["data"]:
                    continue
                size += len(chunk["data"])
                if size > MAX_TTS_AUDIO_BYTES:
                    raise HTTPException(502, "生成音频过大，请分段朗读。")
                yield chunk["data"]
        if not size:
            raise HTTPException(502, "云端未返回音频，请重新朗读。")
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(504, "云端语音生成超时，请稍后重新朗读。") from exc
    except Exception as exc:
        logger.warning("Edge speech synthesis failed ({})", type(exc).__name__)
        raise HTTPException(502, "云端语音暂时不可用，请检查网络后重新朗读。") from exc


class AudioStreamResponse(StreamingResponse):
    def __init__(self, content, *, upstream, **kwargs):
        super().__init__(content, **kwargs)
        self.upstream = upstream

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also close an iterator paused at yield when the listener disconnects.
            with anyio.CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    # Headers can fail before the body iterator ever starts.
                    await self.upstream.aclose()


async def speech_response(request, config, text):
    stream = stream_audio(config, text)
    first_task = asyncio.create_task(anext(stream))

    async def wait_for_disconnect():
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    disconnect_task = asyncio.create_task(wait_for_disconnect())
    try:
        done, _ = await asyncio.wait({first_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED)
        if disconnect_task in done:
            raise HTTPException(499, "播放已取消。")
        # Obtain only the FIRST chunk, so startup errors still have an HTTP status.
        first = await first_task
    except BaseException:
        first_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await first_task
        await stream.aclose()
        raise
    finally:
        disconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_task

    async def body():
        try:
            yield first
            async for chunk in stream:
                yield chunk
        except HTTPException:
            # Headers are already sent. Abort the transport instead of adding JSON to MP3.
            raise RuntimeError("Cloud speech stream interrupted") from None
        finally:
            await stream.aclose()

    return AudioStreamResponse(body(), upstream=stream, media_type="audio/mpeg", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no", "Accept-Ranges": "none",
    })
