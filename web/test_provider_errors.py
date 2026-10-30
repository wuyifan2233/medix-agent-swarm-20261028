import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from openai import AuthenticationError


def auth_error():
    return AuthenticationError('private-provider-response', response=httpx.Response(401, request=httpx.Request('POST','https://example.invalid/v1')), body=None)


class ProviderPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lead_does_not_swallow_auth_error(self):
        from swarm.lead_agent import LeadAgent
        client = SimpleNamespace(chat=AsyncMock(side_effect=auth_error()))
        with self.assertRaises(AuthenticationError):
            await LeadAgent(client).assess_and_decompose('synthetic')
        self.assertEqual(client.chat.await_count, 1)

    async def test_worker_does_not_retry_auth_error(self):
        from core.agent_loop import AgentLoop
        client = SimpleNamespace(chat_with_tools=AsyncMock(side_effect=auth_error()))
        agent = SimpleNamespace(agent_id='synthetic', config={}, llm_client=client,
            get_system_prompt=lambda:'test', get_tools_for_llm=lambda:[], format_user_input=lambda data:data['question'])
        with self.assertRaises(AuthenticationError):
            await AgentLoop().run(agent, {'question':'synthetic'})
        self.assertEqual(client.chat_with_tools.await_count, 1)


class ProviderJobTests(unittest.TestCase):
    def test_failed_auth_job_is_nonretryable_and_redacted(self):
        from web.app import run_job, health
        job = {}
        with patch.dict(health, knowledge='ready'), patch('web.app.analyze', new=AsyncMock(side_effect=auth_error())):
            run_job(job, {}, 'synthetic', 'synthetic')
        self.assertEqual(job['status'],'failed')
        self.assertFalse(job['retryable'])
        self.assertEqual(job['error_code'],'provider_configuration')
        self.assertIn('LOCAL_BASE_URL',job['error'])
        self.assertNotIn('private-provider-response',job['error'])

    def test_missing_key_has_nonretryable_submission_detail(self):
        import uuid, config
        from fastapi.testclient import TestClient
        from web.app import app
        with patch.dict(config.LLM_CONFIG,api_key=''):
            r=TestClient(app).post('/api/chat',json={'message':'synthetic','chat_id':str(uuid.uuid4())})
        self.assertEqual(r.status_code,503)
        self.assertFalse(r.json()['detail']['retryable'])
