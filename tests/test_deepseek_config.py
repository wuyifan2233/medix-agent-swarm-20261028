"""Provider precedence and DeepSeek tool-history compatibility, without API calls."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class DeepSeekConfigTests(unittest.TestCase):
    def setUp(self):
        # Provider-default assertions must not consume a developer's private files.
        for target,value in [('dotenv.dotenv_values',{}),('dotenv.load_dotenv',False)]:
            guard=patch(target,return_value=value);guard.start();self.addCleanup(guard.stop)

    def test_placeholder_mem0_key_is_not_configured(self):
        with patch.dict(os.environ,{'MEDIX_CONFIG_PATH':str(ROOT/'absent-config.py'),'MEM0_API_KEY':'xxx'},clear=True):
            config=runpy.run_path(str(ROOT/'config.py'))
        self.assertEqual(config['MEM0_CONFIG']['api_key'],'')

    def test_deepseek_overrides_openai_without_changing_memory_key(self):
        with patch.dict(os.environ, {"MEDIX_CONFIG_PATH": str(ROOT / "absent-config.py"),
                                     "MEDIX_LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "dummy-deepseek", "OPENAI_API_KEY": "dummy-openai",
                                     "MEM0_API_KEY": "dummy-memory"}, clear=True):
            config = runpy.run_path(str(ROOT / "config.py"))
        llm = config["LLM_CONFIG"]
        self.assertEqual(llm["api_key"], "dummy-deepseek")
        self.assertEqual(llm["model_name"], "deepseek-flash")
        self.assertEqual(llm["base_url"], "https://api.deepseek.com")
        self.assertEqual(llm["request_defaults"]["extra_body"]["thinking"]["type"], "enabled")
        self.assertEqual(config["MEM0_CONFIG"]["api_key"], "dummy-memory")

    def test_openai_fallback_remains_available(self):
        with patch.dict(os.environ, {"MEDIX_CONFIG_PATH": str(ROOT / "absent-config.py"),
                                     "OPENAI_API_KEY": "dummy-openai"}, clear=True):
            config = runpy.run_path(str(ROOT / "config.py"))
        self.assertEqual(config["LLM_CONFIG"]["model_name"], "gpt-4.1-mini")
        self.assertNotIn("extra_body", config["LLM_CONFIG"])


class DeepSeekRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_and_tool_requests_disable_thinking(self):
        from core.llm_client import LLMClient
        client = object.__new__(LLMClient)
        client.model_type = "openai_compatible"
        client.model_name = "deepseek-flash"
        client.temperature = 0.7
        client.max_tokens = 2048
        client.config = {"extra_body": {"thinking": {"type": "disabled"}}}
        create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok", tool_calls=[]), finish_reason="stop")]))
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        await client.chat([{"role": "user", "content": "hello"}])
        await client.chat_with_tools([{"role": "user", "content": "hello"}])
        for call in create.call_args_list:
            self.assertEqual(call.kwargs["extra_body"], {"thinking": {"type": "disabled"}})


if __name__ == "__main__":
    unittest.main()
