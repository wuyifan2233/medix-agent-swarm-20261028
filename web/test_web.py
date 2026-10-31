import os
os.environ.setdefault("MEDIX_WECHAT_DISABLE", "1")
os.environ.setdefault("MEDIX_QQ_DISABLE", "1")
import base64
import io
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch
import tempfile
from fastapi.testclient import TestClient
from PIL import Image
from web.app import app, jobs, normalize_image
from auth.schemas import Registration
from auth.service import AuthService
from auth.settings import AuthSettings
from storage.database import make_database
from storage.migrate import upgrade_database


class StubAudioClient:
    calls = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return type("AudioResponse", (), {
            "status_code": 200,
            "content": b"fake-audio",
            "json": lambda self: {"text": "已识别的语音"},
        })()

class WebBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth = app.state.auth_service
        self.temp = tempfile.TemporaryDirectory()
        url = "sqlite:///" + (Path(self.temp.name) / "web.db").as_posix()
        upgrade_database(url)
        self.engine, sessions = make_database(url)
        settings = AuthSettings(url, False, frozenset({"http://testserver"}), True, password_registration_enabled=True)
        app.state.auth_service = AuthService(sessions, settings)
        user = app.state.auth_service.register(Registration(username="alice", display_name="Alice", password="Test-Password2026!"))
        self.user_id = user.id
        self.client = TestClient(app, headers={"Origin":"http://testserver", "X-Medix-Request":"1"})
        response = self.client.post("/api/auth/login", json={"username":"alice", "password":"Test-Password2026!"})
        self.client.headers["X-CSRF-Token"] = response.json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        app.state.auth_service = self.previous_auth
        self.engine.dispose()
        self.temp.cleanup()

    def test_image_pixels_are_reencoded(self):
        stream = io.BytesIO()
        Image.new("RGB", (32, 20), "white").save(stream, "PNG")
        result = normalize_image({"data": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()})
        self.assertTrue(result.startswith("data:image/jpeg;base64,"))
        image = Image.open(io.BytesIO(base64.b64decode(result.split(",", 1)[1])))
        self.assertEqual(image.size, (32, 20))

    def test_disguised_non_image_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_image({"data": "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()})

    def test_svg_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_image({"data": "data:image/svg+xml;base64,PHN2Zz4="})

    def test_empty_message_is_rejected(self):
        client = self.client
        self.assertEqual(client.post("/api/chat", json={"message": "", "images": []}).status_code, 400)

    def test_foreign_origin_is_rejected(self):
        client = self.client
        self.assertEqual(client.post("/api/chat", json={}, headers={"Origin":"https://elsewhere.example"}).status_code, 403)

    def test_other_user_cannot_read_job(self):
        jobs["boundary-test"] = {"owner_user_id": "another-user", "status": "completed"}
        try:
            client = self.client
            self.assertEqual(client.get("/api/jobs/boundary-test").status_code, 404)
            jobs["boundary-test"]["owner_user_id"] = self.user_id
            self.assertEqual(client.get("/api/jobs/boundary-test").status_code, 200)
        finally:
            jobs.pop("boundary-test", None)

    def test_health_exposes_speech_capability(self):
        body = TestClient(app).get("/api/health").json()
        self.assertIn("speech_api_configured", body)
        self.assertIn("tts_configured", body)
        self.assertIn("tts_voice", body)

    def test_voice_upload_rejects_unknown_format(self):
        response = self.client.post(
            "/api/voice/transcribe", json={"audio":"bm90LWF1ZGlv", "content_type":"text/plain"}
        )
        self.assertEqual(response.status_code, 415)

    def test_voice_upload_requires_audio_configuration(self):
        with patch("config.SPEECH_CONFIG", {"remote_enabled": False}):
            response = self.client.post("/api/voice/transcribe", json={"audio":"YXVkaW8=", "content_type":"audio/webm"})
        self.assertEqual(response.status_code, 503)

    def test_empty_speech_text_is_rejected_before_provider_call(self):
        response = self.client.post("/api/voice/speech", json={"text": "   "})
        self.assertEqual(response.status_code, 400)

    def test_transcription_uses_configured_model_and_returns_text(self):
        config = {
            "remote_enabled": True, "api_key": "test-key", "base_url": "https://audio.example/v1",
            "transcription_model": "test-asr", "transcription_language": "zh", "max_audio_bytes": 1024,
        }
        StubAudioClient.calls = []
        with patch("config.SPEECH_CONFIG", config), patch("httpx.AsyncClient", StubAudioClient):
            response = self.client.post(
                "/api/voice/transcribe", json={"audio":base64.b64encode(b"test-recording").decode(), "content_type":"audio/webm"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "已识别的语音"})
        url, request = StubAudioClient.calls[0]
        self.assertEqual(url, "https://audio.example/v1/audio/transcriptions")
        self.assertEqual(request["data"], {"model": "test-asr", "language": "zh"})

    def test_transcription_rejects_invalid_and_oversized_recordings(self):
        config = {"remote_enabled":True, "max_audio_bytes":4}
        cases = [({}, 400), ({"audio":"?", "content_type":"audio/webm"}, 400),
                 ({"audio":"", "content_type":"audio/webm"}, 400),
                 ({"audio":base64.b64encode(b"12345").decode(), "content_type":"audio/webm"}, 413)]
        with patch("config.SPEECH_CONFIG", config), patch("httpx.AsyncClient", StubAudioClient):
            StubAudioClient.calls = []
            for payload, status in cases:
                with self.subTest(payload=payload):
                    self.assertEqual(self.client.post("/api/voice/transcribe", json=payload).status_code, status)
            self.assertEqual(StubAudioClient.calls, [])

    def test_gpt_transcribe_uses_supported_language_hints(self):
        config = {
            "remote_enabled": True, "api_key": "test-key", "base_url": "https://audio.example/v1",
            "transcription_model": "gpt-transcribe", "transcription_language": "zh", "max_audio_bytes": 1024,
        }
        StubAudioClient.calls = []
        with patch("config.SPEECH_CONFIG", config), patch("httpx.AsyncClient", StubAudioClient):
            response = self.client.post(
                "/api/voice/transcribe", json={"audio":base64.b64encode(b"test-recording").decode(), "content_type":"audio/webm"}
            )
        self.assertEqual(response.status_code, 200)
        _, request = StubAudioClient.calls[0]
        self.assertEqual(request["data"], {"model": "gpt-transcribe", "languages": ["zh"]})

    def test_audio_key_reuse_is_limited_to_same_openai_endpoint(self):
        root = Path(__file__).resolve().parents[1]
        config_path = str(root / "missing-audio-test-config.py")
        text_config = {
            "MEDIX_CONFIG_PATH": config_path,
            "OPENAI_API_KEY": "text-key",
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "MEDIX_AUDIO_BASE_URL": "https://audio.example/v1",
        }
        with patch.dict(os.environ, text_config, clear=True):
            speech = runpy.run_path(str(root / "config.py"))["SPEECH_CONFIG"]
        self.assertFalse(speech["remote_enabled"])
        self.assertEqual(speech["api_key"], "")

        with patch.dict(os.environ, {**text_config, "MEDIX_AUDIO_API_KEY": "audio-key"}, clear=True):
            speech = runpy.run_path(str(root / "config.py"))["SPEECH_CONFIG"]
        self.assertTrue(speech["remote_enabled"])
        self.assertEqual(speech["api_key"], "audio-key")

        with patch.dict(os.environ, {
            "MEDIX_CONFIG_PATH": config_path,
            "MEDIX_LLM_PROVIDER": "auto",
            "DEEPSEEK_API_KEY": "xxx",
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        }, clear=True):
            speech = runpy.run_path(str(root / "config.py"))["SPEECH_CONFIG"]
        self.assertTrue(speech["remote_enabled"])
        self.assertEqual(speech["api_key"], "openai-key")


class SwarmContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_subtask_keeps_image_facts_and_session(self):
        from types import SimpleNamespace
        from agents.base_agent import BaseAgent
        class CaptureAgent(BaseAgent):
            def get_system_prompt(self): return "test"
            def register_tools(self): pass
            async def run_loop(self, input_data): return input_data
        agent = CaptureAgent("context-test", {}, llm_client=object())
        agent.shared_context = SimpleNamespace(session_id="image-session", data={
            "original_question":"第二次记录为 136/88 mmHg", "request_context":{"image":True}})
        data = await agent.process_subtask(SimpleNamespace(id="one", type="read", description="读取第二次记录"))
        self.assertIn("136/88", data["question"])
        self.assertEqual(data["session_id"], "image-session")
        self.assertTrue(data["context"]["image"])


class RuntimeSkillTests(unittest.TestCase):
    def test_voice_ui_skills_are_discovered_but_not_agent_tools(self):
        import importlib.util
        import sys
        import types

        root = Path(__file__).resolve().parents[1]
        loader_spec = importlib.util.spec_from_file_location("voice_test_skill_loader", root / "core" / "skill_loader.py")
        loader = importlib.util.module_from_spec(loader_spec)
        loader_spec.loader.exec_module(loader)
        registry_spec = importlib.util.spec_from_file_location("voice_test_skill_registry", root / "core" / "skill_registry.py")
        registry = importlib.util.module_from_spec(registry_spec)
        registry_spec.loader.exec_module(registry)
        core_package = types.ModuleType("core")
        core_package.__path__ = []
        mixin_spec = importlib.util.spec_from_file_location("voice_test_skill_mixin", root / "agents" / "skill_registry_mixin.py")
        mixin = importlib.util.module_from_spec(mixin_spec)
        with patch.dict(sys.modules, {
            "core": core_package, "core.skill_loader": loader, "core.skill_registry": registry,
        }):
            mixin_spec.loader.exec_module(mixin)
        discovered = []
        for name, script, function_name in (
            ("voice-input", "voice_input", "voice_input"),
            ("tts-voice", "tts_voice", "tts_voice"),
        ):
            skill_dir = root / ".claude" / "skills" / name
            metadata = loader.parse_skill_md(skill_dir / "SKILL.md")
            self.assertIsNotNone(metadata)
            self.assertFalse(metadata.get("expose_to_agent", True))
            function = loader.load_skill_function(name, script, function_name, root)
            discovered.append({"name": name, "function_name": function_name, "metadata": metadata, "function": function})

        class RegistryHarness(mixin.SkillRegistryMixin):
            def __init__(self):
                self.skill_registry = registry.SkillRegistry()

        harness = RegistryHarness()
        with patch.object(mixin, "discover_skills", return_value=discovered):
            harness.register_all_skills()
        self.assertNotIn("voice_input", harness.skill_registry.get_all())
        self.assertNotIn("tts_voice", harness.skill_registry.get_all())

if __name__ == "__main__":
    unittest.main()
