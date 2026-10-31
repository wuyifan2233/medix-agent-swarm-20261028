"""Official Search HTTP contract and account-owned per-request settlement."""
import asyncio
from contextlib import contextmanager
import json
import unittest
import uuid
from unittest.mock import patch

import httpx

from core.chat_runtime import ChatRuntime, runtime, usage_summary
from research.web_search import SearchError, WebSearchTool
from storage import care_wallet
from storage.chat import store
from storage.test_support import account_clients


def item(url='https://www.who.int/fixture'):
    return {'title': 'WHO fixture', 'url': url, 'snippet': 'short fixture', 'summary': 'long fixture',
            'content': 'page fixture', 'site_name': 'WHO', 'date': '2026-10-01T00:00:00Z', 'authority': 3, 'rerank_score': 2.1}


class OfficialSearchTests(unittest.IsolatedAsyncioTestCase):
    def tool(self, handler):
        return WebSearchTool(provider='deepseek', api_key='fixture-secret', transport=httpx.MockTransport(handler))

    async def test_exact_request_and_structured_source_fields(self):
        def handler(req):
            self.assertEqual(str(req.url), 'https://api.deepseek.com/v1/tools/search')
            self.assertEqual(req.headers['Authorization'], 'Bearer fixture-secret')
            self.assertEqual(json.loads(req.content), {'query': 'WHO fixture', 'count': 2, 'need_content': False})
            return httpx.Response(200, json={'results': [item()]})
        row = (await self.tool(handler).search('WHO fixture', max_results=2))[0]
        self.assertEqual((row.summary, row.snippet, row.date, row.authority), ('long fixture', 'short fixture', '2026-10-01T00:00:00Z', 3))
        self.assertEqual(row.content, '')

    async def test_explicit_content_and_original_question(self):
        def handler(req):
            data = json.loads(req.content)
            self.assertTrue(data['need_content'])
            self.assertEqual(data['ori_question'], 'original fixture')
            self.assertNotIn('model', data)
            return httpx.Response(200, json={'results': [item()]})
        rows = await self.tool(handler).search('fixture', need_content=True, ori_question='original fixture')
        self.assertEqual(rows[0].content, 'page fixture')

    async def test_time_window_uses_official_query_syntax(self):
        def handler(req):
            data = json.loads(req.content)
            self.assertRegex(data['query'], r'^fixture after:\d{4}-\d{2}-\d{2}$')
            self.assertNotIn('timelimit', data)
            return httpx.Response(200, json={'results': []})
        self.assertEqual(await self.tool(handler).search('fixture', timelimit='y'), [])

    async def test_official_search_is_default_and_has_no_implicit_ddgs_fallback(self):
        requests = []
        def handler(req):
            requests.append(req)
            return httpx.Response(401, json={'error': {'message': 'fixture-secret upstream detail'}})
        with patch('research.web_search.DDGS') as ddgs:
            with self.assertRaises(SearchError) as raised:
                await self.tool(handler).search('fixture')
        self.assertNotIn('fixture-secret', str(raised.exception))
        self.assertEqual(len(requests), 1)
        ddgs.assert_not_called()

    async def test_status_errors_do_not_leak_upstream_bodies(self):
        for status in (400, 401, 402, 403, 429, 500, 504):
            with self.subTest(status=status), self.assertRaises(SearchError) as raised:
                await self.tool(lambda req: httpx.Response(status, text='fixture-secret')).search('fixture')
            self.assertNotIn('fixture-secret', str(raised.exception))

    async def test_validation_never_sends_invalid_requests(self):
        requests = []
        tool = self.tool(lambda req: requests.append(req))
        for kwargs in ({'query': ''}, {'query': 'a' * 129}, {'query': 'fixture', 'max_results': 0},
                       {'query': 'fixture', 'max_results': 51}, {'query': 'fixture', 'need_content': 1},
                       {'query': 'fixture', 'ori_question': 'a' * 129}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await tool.search(**kwargs)
        self.assertEqual(requests, [])

    async def test_duplicate_urls_and_unsafe_urls_are_not_returned(self):
        tool = self.tool(lambda req: httpx.Response(200, json={'results': [item(), item('https://www.who.int/fixture/#section'), item('javascript:fixture')]}))
        self.assertEqual(len(await tool.search('fixture')), 1)

    async def test_malformed_response_is_not_an_empty_success(self):
        for body in ({'results': {}}, {}, []):
            with self.subTest(body=body), self.assertRaises(SearchError):
                await self.tool(lambda req: httpx.Response(200, json=body)).search('fixture')

    async def test_transport_errors_are_safe(self):
        def handler(req):
            raise httpx.ReadTimeout('fixture-secret', request=req)
        with self.assertRaises(SearchError) as raised:
            await self.tool(handler).search('fixture')
        self.assertNotIn('fixture-secret', str(raised.exception))


class SearchWalletTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope = account_clients()
        self.accounts = self.scope.__enter__()
        self.owner = self.accounts.users[0].id
        self.turn = uuid.uuid4().hex
        store.create_turn(self.owner, str(uuid.uuid4()), str(uuid.uuid4()), self.turn,
                          {'message': 'public search fixture', 'images': [], 'case_id': ''})

    def tearDown(self):
        self.scope.__exit__(None, None, None)

    @contextmanager
    def active(self):
        token = runtime.set(ChatRuntime(self.turn))
        try:
            with patch.dict('os.environ', {'MEDIX_SEARCH_PRICE_CNY': '0.005'}):
                yield
        finally:
            runtime.reset(token)

    def tool(self, handler):
        return WebSearchTool(provider='deepseek', api_key='fixture-secret', transport=httpx.MockTransport(handler))

    async def test_paid_empty_and_rejected_calls_settle_separately_from_tokens(self):
        with self.active():
            await self.tool(lambda req: httpx.Response(200, json={'results': [item()]})).search('fixture')
            await self.tool(lambda req: httpx.Response(200, json={'results': []})).search('fixture')
            with self.assertRaises(SearchError):
                await self.tool(lambda req: httpx.Response(402)).search('fixture')
        self.assertEqual(care_wallet.view(self.owner)['balance'], 9995)
        self.assertEqual(care_wallet.view(self.owner)['held'], 0)
        self.assertEqual(care_wallet.view(self.accounts.users[1].id)['balance'], 10000)
        summary = usage_summary(self.turn)
        self.assertEqual((summary['requests'], summary['search_requests'], summary['agent_count']), (0, 3, 0))
        self.assertEqual((summary['input_tokens'], summary['output_tokens'], summary['unknown_requests']), (0, 0, 0))
        entry = care_wallet.history(self.owner)['entries'][0]
        self.assertEqual((entry['requests'], entry['search_requests'], entry['points']), (0, 3, 5))
        self.assertTrue(all(call['usage_kind'] == 'search' for call in entry['calls']))
        self.assertEqual(care_wallet.history(self.accounts.users[1].id)['entries'], [])

    async def test_insufficient_points_prevents_upstream_request(self):
        requests = []
        with self.active(), patch.dict('os.environ', {'MEDIX_INITIAL_CARE_POINTS': '0'}):
            with self.assertRaises(care_wallet.CarePointsError):
                await self.tool(lambda req: requests.append(req)).search('fixture')
        self.assertEqual(requests, [])

    async def test_client_timeout_keeps_only_the_fixed_price_pending(self):
        def handler(req):
            raise httpx.ReadTimeout('fixture timeout', request=req)
        with self.active(), self.assertRaises(SearchError):
            await self.tool(handler).search('fixture')
        balance = care_wallet.view(self.owner)
        self.assertEqual((balance['balance'], balance['available'], balance['held']), (10000, 9995, 5))
        self.assertEqual(usage_summary(self.turn)['unknown_requests'], 1)

    async def test_cancel_closes_upstream_and_records_pending_attempt(self):
        started, closed = asyncio.Event(), asyncio.Event()
        async def handler(req):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        with self.active():
            task = asyncio.create_task(self.tool(handler).search('fixture'))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(closed.is_set())
        self.assertEqual(care_wallet.view(self.owner)['held'], 5)
        self.assertEqual(usage_summary(self.turn)['calls'][0]['status'], 'cancelled')

    async def test_nonempty_provider_response_still_charges_after_filtering(self):
        with self.active():
            rows = await self.tool(lambda req: httpx.Response(200, json={'results': [item('javascript:fixture')]})).search('fixture')
        self.assertEqual(rows, [])
        self.assertEqual(care_wallet.turn_charge(self.turn)['points'], 5)

    async def test_price_snapshot_is_immutable_after_configuration_changes(self):
        with self.active():
            await self.tool(lambda req: httpx.Response(200, json={'results': [item()]})).search('fixture')
        with patch.dict('os.environ', {'MEDIX_SEARCH_PRICE_CNY': '1'}):
            self.assertEqual(usage_summary(self.turn)['calls'][0]['price']['request'], '0.005')
            self.assertEqual(care_wallet.turn_charge(self.turn)['points'], 5)
