"""Deterministic TTS contract/failure tests. These never call the cloud."""
import asyncio
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from web.app import app, speech_tickets
from web import speech


class StubSpeaker:
    calls = []
    chunks = [{"type": "SentenceBoundary", "text": "ignored"},
              {"type": "audio", "data": b"mp3-a"}, {"type": "audio", "data": b"mp3-b"}]
    failure = None

    def __init__(self, text, **kwargs):
        self.calls.append((text, kwargs))

    async def stream(self):
        if self.failure:
            raise self.failure
        for chunk in self.chunks:
            yield chunk


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch("config.SPEECH_CONFIG", {
            "remote_enabled": False, "tts_provider": "edge", "tts_voice": "zh-CN-XiaoxiaoNeural",
            "tts_rate": "-5%", "tts_pitch": "+0Hz", "tts_volume": "+0%",
            "api_key": "text-key-must-never-be-sent", "base_url": "https://api.deepseek.com",
        })
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.speaker_patch = patch("edge_tts.Communicate", StubSpeaker)
        self.speaker_patch.start()
        self.addCleanup(self.speaker_patch.stop)
        StubSpeaker.calls = []
        StubSpeaker.failure = None
        self.client = TestClient(app)
        speech_tickets.clear()
        self.addCleanup(speech_tickets.clear)

    def test_cloud_is_independent_of_asr_and_llm_keys(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["tts_configured"])
        self.assertFalse(body["speech_api_configured"])
        self.assertEqual(body["tts_provider"], "edge")
        self.assertNotIn("api_key", body)
        response = self.client.post("/api/voice/speech", json={"text": "## 你好\n[今天](https://example.org)，**照顾自己**。```private-code```"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"mp3-amp3-b")
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        text, options = StubSpeaker.calls[0]
        self.assertEqual(text, "你好 今天，照顾自己。")
        self.assertEqual(options, {"voice": "zh-CN-XiaoxiaoNeural", "rate": "-5%",
                                  "pitch": "+0Hz", "volume": "+0%", "connect_timeout": 10,
                                  "receive_timeout": 30})

    def test_invalid_inputs_never_call_provider(self):
        for payload, status in [({"text": " "}, 400), ({"text": 123}, 400), ([], 400),
                                ({"text": "字" * 4001}, 413)]:
            with self.subTest(payload_type=type(payload).__name__, status=status):
                self.assertEqual(self.client.post("/api/voice/speech", json=payload).status_code, status)
        self.assertEqual(self.client.post("/api/voice/speech", content=b"{bad").status_code, 400)
        self.assertEqual(StubSpeaker.calls, [])

    def test_provider_error_is_controlled_without_upstream_details(self):
        StubSpeaker.failure = RuntimeError("secret-provider-detail")
        response = self.client.post("/api/voice/speech", json={"text": "你好"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-provider-detail", response.text)

    def test_empty_and_oversized_audio_are_rejected(self):
        for chunks, cap in [([], 16), ([{"type": "audio", "data": b"12345"}], 4)]:
            with self.subTest(cap=cap), patch.object(StubSpeaker, "chunks", chunks), patch.object(speech, "MAX_TTS_AUDIO_BYTES", cap):
                self.assertEqual(self.client.post("/api/voice/speech", json={"text": "你好"}).status_code, 502)

    def test_unknown_provider_is_disabled(self):
        with patch("config.SPEECH_CONFIG", {"remote_enabled": False, "tts_provider": "unknown"}):
            self.assertFalse(self.client.get("/api/health").json()["tts_configured"])
            self.assertEqual(self.client.post("/api/voice/speech", json={"text": "你好"}).status_code, 503)
        self.assertEqual(StubSpeaker.calls, [])

    def test_missing_dependency_has_actionable_error(self):
        with patch.object(speech.importlib.util, "find_spec", return_value=None):
            self.assertFalse(self.client.get("/api/health").json()["tts_configured"])
        with patch.object(speech.importlib, "import_module", side_effect=ImportError):
            response = self.client.post("/api/voice/speech", json={"text": "你好"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("requirements.web.txt", response.json()["detail"])

    def test_timeout_is_bounded(self):
        async def stalled(_self):
            await asyncio.Event().wait()
            yield {"type": "audio", "data": b"never"}
        with patch.object(StubSpeaker, "stream", stalled), patch.object(speech, "TTS_TIMEOUT_SECONDS", 0.02):
            response = self.client.post("/api/voice/speech", json={"text": "你好"})
        self.assertEqual(response.status_code, 504)

    def test_native_stream_ticket_is_browser_owned_and_single_use(self):
        prepared = self.client.post("/api/voice/speech/prepare", json={"text": "你好，固定样例"})
        self.assertEqual(prepared.status_code, 200)
        url = prepared.json()["url"]
        self.assertNotIn("固定样例", url)
        self.assertEqual(StubSpeaker.calls, [], "Preparing must not wait for synthesis")
        self.assertEqual(TestClient(app).get(url).status_code, 404)
        audio = self.client.get(url, headers={"Range": "bytes=0-"})
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.content, b"mp3-amp3-b")
        self.assertNotIn("content-length", audio.headers)
        self.assertEqual(audio.headers["x-accel-buffering"], "no")
        self.assertEqual(audio.headers["accept-ranges"], "none")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_ticket_expiration_and_capacity(self):
        with patch("web.app.MAX_SPEECH_TICKETS", 1):
            url = self.client.post("/api/voice/speech/prepare", json={"text": "你好"}).json()["url"]
            self.assertEqual(self.client.post("/api/voice/speech/prepare", json={"text": "你好"}).status_code, 429)
            speech_tickets[url.rsplit("/", 1)[1]]["created"] -= 121
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post("/api/voice/speech/prepare", json={"text": "你好"}).status_code, 200)
        self.assertEqual(StubSpeaker.calls, [])

    def test_default_voice_needs_no_llm_or_audio_credentials(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict(os.environ, {"MEDIX_CONFIG_PATH": str(root / "missing-test-config.py")}, clear=True):
            config = runpy.run_path(str(root / "config.py"))["SPEECH_CONFIG"]
        self.assertEqual(config["tts_provider"], "edge")
        self.assertEqual(config["tts_voice"], "zh-CN-XiaoxiaoNeural")
        self.assertFalse(config["remote_enabled"])


class StreamTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_chunk_arrives_before_generation_finishes_and_close_releases_upstream(self):
        finished, closed = asyncio.Event(), asyncio.Event()
        class DelayedSpeaker:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                try:
                    yield {"type": "audio", "data": b"first"}
                    await asyncio.Event().wait()
                    finished.set()
                finally:
                    closed.set()
        with patch("edge_tts.Communicate", DelayedSpeaker):
            stream = speech.stream_audio({}, "test")
            try:
                first = await asyncio.wait_for(anext(stream), 0.5)
                self.assertEqual(first, b"first")
                self.assertFalse(finished.is_set())
            finally:
                await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_disconnect_cancels_synthesis_before_first_chunk(self):
        from fastapi import HTTPException
        started, closed = asyncio.Event(), asyncio.Event()
        class WaitingSpeaker:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                try:
                    started.set()
                    await asyncio.Event().wait()
                    yield {"type": "audio", "data": b"never"}
                finally:
                    closed.set()
        class DisconnectedRequest:
            async def receive(self):
                await started.wait()
                return {"type": "http.disconnect"}
        with patch("edge_tts.Communicate", WaitingSpeaker):
            with self.assertRaises(HTTPException) as caught:
                await asyncio.wait_for(speech.speech_response(DisconnectedRequest(), {}, "test"), 1)
        self.assertEqual(caught.exception.status_code, 499)
        self.assertTrue(closed.is_set())

    async def test_late_failure_aborts_mp3_instead_of_appending_json(self):
        closed = asyncio.Event()
        class FailingSpeaker:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                try:
                    yield {"type": "audio", "data": b"first"}
                    raise RuntimeError("private-upstream-error")
                finally:
                    closed.set()
        class ConnectedRequest:
            async def receive(self): await asyncio.Event().wait()
        with patch("edge_tts.Communicate", FailingSpeaker):
            response = await speech.speech_response(ConnectedRequest(), {}, "test")
            self.assertEqual(await anext(response.body_iterator), b"first")
            with self.assertRaisesRegex(RuntimeError, "^Cloud speech stream interrupted$"):
                await anext(response.body_iterator)
        self.assertTrue(closed.is_set())

    async def test_header_disconnect_closes_provider_before_body_starts(self):
        closed = asyncio.Event()
        class Speaker:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                try:
                    yield {"type": "audio", "data": b"first"}
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        class ConnectedRequest:
            async def receive(self): await asyncio.Event().wait()
        async def send(message): raise OSError("disconnected")
        async def receive(): await asyncio.Event().wait()
        from starlette.requests import ClientDisconnect
        with patch("edge_tts.Communicate", Speaker):
            response = await speech.speech_response(ConnectedRequest(), {}, "test")
            with self.assertRaises(ClientDisconnect):
                await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        self.assertTrue(closed.is_set())

    async def test_transport_disconnect_releases_open_provider(self):
        closed, sent = asyncio.Event(), asyncio.Event()
        class WaitingSpeaker:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                try:
                    yield {"type": "audio", "data": b"first"}
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        class ConnectedRequest:
            async def receive(self): await asyncio.Event().wait()
        async def receive():
            await sent.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body": sent.set()
        with patch("edge_tts.Communicate", WaitingSpeaker):
            response = await speech.speech_response(ConnectedRequest(), {}, "test")
            await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send), 1)
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
