"""Offline DeepSeek configuration and OpenAI-compatible request contracts."""
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI


class ConfigTests(unittest.TestCase):
    def config(self, values, environment=None):
        with patch.dict(os.environ, {'MEDIX_CONFIG_PATH': 'missing-test-config.py',
                                    **(environment or {})}, clear=True), \
             patch('dotenv.dotenv_values', return_value=values):
            return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'config.py'))['LLM_CONFIG']

    def test_local_placeholder_is_not_configured(self):
        config = self.config({'MEDIX_LLM_PROVIDER': 'deepseek', 'DEEPSEEK_API_KEY': 'xxx'})
        self.assertEqual(config['api_key'], 'not-configured')
        self.assertEqual(config['model_name'], 'deepseek-flash')

    def test_local_key_and_environment_override(self):
        config = self.config({'MEDIX_LLM_PROVIDER': 'deepseek', 'DEEPSEEK_API_KEY': 'file-test'},
                             {'DEEPSEEK_API_KEY': 'env-test'})
        self.assertEqual(config['api_key'], 'env-test')
        self.assertEqual(config['base_url'], 'https://api.deepseek.com')
        self.assertEqual(config['request_defaults']['extra_body'], {'thinking': {'type': 'enabled'}})

    def test_auto_preserves_existing_provider(self):
        config = self.config({'DEEPSEEK_API_KEY': 'file-test'}, {'OPENAI_API_KEY': 'old-test'})
        self.assertEqual(config['api_key'], 'old-test')
        self.assertNotIn('request_defaults', config)


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_and_tool_continuation_preserve_contract(self):
        from core.llm_client import LLMClient
        from core.agent_loop import AgentLoop
        requests = []

        def handler(request):
            self.assertEqual(str(request.url), 'https://api.deepseek.com/chat/completions')
            body = json.loads(request.content); requests.append(body)
            message = {'role': 'assistant', 'content': 'mock answer', 'reasoning_content': 'mock reasoning'}
            if len(requests) == 2:
                message.update(content=None, tool_calls=[{'id': 'call_test', 'type': 'function',
                    'function': {'name': 'lookup', 'arguments': '{}'}}])
            return httpx.Response(200, json={'id': 'mock', 'object': 'chat.completion', 'created': 0,
                'model': 'deepseek-flash', 'choices': [{'index': 0, 'message': message,
                    'finish_reason': 'tool_calls' if len(requests) == 2 else 'stop'}]})

        config = {'api_key': 'mock-key', 'base_url': 'https://api.deepseek.com',
                  'model_name': 'deepseek-flash', 'max_tokens': 8192,
                  'request_defaults': {'stream': False, 'reasoning_effort': 'high',
                                       'extra_body': {'thinking': {'type': 'enabled'}}}}
        sdk = AsyncOpenAI(api_key='mock-key', base_url=config['base_url'],
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with patch('core.llm_client.LLM_CONFIG', config), patch('core.llm_client.AsyncOpenAI', return_value=sdk):
            client = LLMClient()
        try:
            messages = [{'role': 'user', 'content': 'synthetic question'}]
            self.assertEqual(await client.chat(messages), 'mock answer')
            tools = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}]
            result = await client.chat_with_tools(messages, tools)
            assistant = AgentLoop._create_assistant_message_with_tools(None, result)
            self.assertEqual(assistant['reasoning_content'], 'mock reasoning')
            messages += [assistant, {'role': 'tool', 'tool_call_id': 'call_test', 'content': 'synthetic evidence'}]
            await client.chat_with_tools(messages, tools)
            for request in requests:
                self.assertEqual(request['model'], 'deepseek-flash')
                self.assertFalse(request['stream'])
                self.assertEqual(request['thinking'], {'type': 'enabled'})
                self.assertEqual(request['reasoning_effort'], 'high')
            self.assertEqual(requests[-1]['messages'][1]['reasoning_content'], 'mock reasoning')
        finally:
            await sdk.close()


if __name__ == '__main__':
    unittest.main()
