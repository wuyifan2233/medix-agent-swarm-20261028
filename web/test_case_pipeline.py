"""Regression cases for long histories, result-column checks and partial reports."""
import asyncio
import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from PIL import Image
from web import case_memory as store
from web.case_context import prepare_context, propose_changes, extraction_proposal
from web.report_reader import read_reports


def operation(name, value, source='user', quote=None):
    return {'action': 'add', 'source': source, 'quote': quote or f'{name} {value}',
            'fact': {'name': name, 'value': value}}


class PipelineTests(unittest.TestCase):
    def test_case_title_uses_topics_without_inventing_diagnoses(self):
        title = store.case_title([{'name':'尿酸','value':'480','date':'2018-05-22'},
                                  {'name':'总胆红素','value':'26.3','date':'2026-10-30'}])
        self.assertIn('肝胆功能', title)
        self.assertIn('2026-10-30', title)
        self.assertNotIn('肝炎', title)

    def test_case_title_accepts_explicit_recorded_diagnosis(self):
        title = store.case_title([{'name':'医生诊断','value':'高血压','certainty':'clear','date':''}])
        self.assertIn('高血压', title)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, 'DB_PATH', Path(self.temp.name) / 'cases.sqlite3')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def seed(self, count=250):
        ops = [operation(f'项目{i}', str(1000+i)) for i in range(count)]
        result = store.apply_changes('owner', 'chat', '', 'seed', {'operations': ops},
                                     '\n'.join(op['quote'] for op in ops), '')
        return result['case_id']

    def test_reference_bound_cannot_be_saved_as_result(self):
        line = 'GLU 5.00 mmol/L (3.89-6.11)'
        wrong = operation('GLU', '6.11', 'image', line)
        outcome = store.apply_changes('owner', 'chat', '', 'image', {'operations': [wrong]}, '', line)
        self.assertFalse(outcome['changes'])
        self.assertTrue(outcome['questions'])
        self.assertTrue(store.result_cell_matches({'name': 'GLU', 'value': '5.00'}, line))

    def test_large_history_is_paged_and_old_named_record_is_retrievable(self):
        case = self.seed()
        self.assertEqual([len(page) for page in store.fact_pages('owner', case)], [200, 50])
        facts = store.current_facts('owner', case)
        self.assertEqual(len(facts), 250)
        self.assertEqual(store.related_facts(facts, '项目0是多少')[0]['data']['name'], '项目0')

    def test_old_record_reaches_extractor_and_can_be_corrected(self):
        case = self.seed()
        facts = store.current_facts('owner', case)
        old = next(f for f in facts if f['data']['name'] == '项目0')
        captured = []
        async def close(): pass
        class Client:
            client = SimpleNamespace(close=close)
            async def chat(self, messages, **kwargs):
                captured.extend(json.loads(messages[1]['content'])['existing_current_records'])
                return json.dumps({'operations': [{'action': 'correct', 'source': 'user', 'quote': '更正项目0为900',
                    'target_id': old['id'], 'expected_revision': 1, 'fact': {'value': '900'}}]})
        with patch('core.LLMClient', Client):
            proposal = asyncio.run(propose_changes('更正项目0为900', '', facts))
        self.assertIn(old['id'], [f['id'] for f in captured])
        store.apply_changes('owner', 'chat', case, 'correction', proposal, '更正项目0为900', '')
        self.assertEqual(next(f for f in store.current_facts('owner', case) if f['id'] == old['id'])['data']['value'], '900')

    def test_failed_index_still_selects_old_requested_record_and_warns(self):
        case = self.seed()
        with patch('web.case_context.propose_changes', AsyncMock(return_value={'operations': []})), \
             patch('web.case_context.retrieve', side_effect=RuntimeError('synthetic failure')):
            result = asyncio.run(prepare_context('owner', 'chat', case, 'lookup', '项目0是多少', '', object()))
        self.assertFalse(result['index_ready'])
        self.assertIn('项目0', [f['data']['name'] for f in result['facts']])
        self.assertTrue(any('语义检索暂不可用' in warning for warning in result['warnings']))

    def test_more_than_40_image_fields_are_extracted_in_batches(self):
        rows = [f'项目{i}【结果】{1000+i}【单位】mmol/L【参考】0-10' for i in range(55)]
        calls = []
        async def extract(question, observed, facts):
            lines = [line for line in observed.splitlines() if '【结果】' in line]
            calls.append(len(lines))
            return {'operations': [operation(line.split('【结果】')[0], line.split('【结果】')[1].split('【单位】')[0], 'image', line) for line in lines]}
        with patch('web.case_context.propose_changes', side_effect=extract):
            result = asyncio.run(prepare_context('owner', 'chat', '', 'many-rows', '看看报告', '\n'.join(rows), object()))
        self.assertEqual(calls, [24, 24, 7])
        self.assertEqual(len(store.current_facts('owner', result['case_id'])), 55)
        self.assertEqual(result['extraction_check']['unmatched_rows'], 0)

    def test_omitted_field_is_retried_and_failed_storage_is_disclosed(self):
        row = 'GLU【结果】5.00【单位】mmol/L【参考】3.89-6.11'
        extractor = AsyncMock(return_value={'operations': []})
        with patch('web.case_context.propose_changes', extractor):
            result = asyncio.run(prepare_context('owner', 'chat', '', 'missing', '看看', row, object()))
        self.assertEqual(extractor.await_count, 2)
        self.assertEqual(result['extraction_check']['unmatched_rows'], 1)
        self.assertTrue(result['warnings'])

    def test_each_image_batch_keeps_its_own_date_metadata(self):
        observed = '【图片 1】\n2026-01-01\nGLU【结果】5【单位】mmol/L【参考】0-10\n【图片 2】\n2026-10-01\nGLU【结果】6【单位】mmol/L【参考】0-10'
        calls = []
        async def extract(question, observed, facts):
            calls.append(observed)
            line = next(line for line in observed.splitlines() if '【结果】' in line)
            return {'operations': [operation('GLU', line.split('【结果】')[1].split('【单位】')[0], 'image', line)]}
        with patch('web.case_context.propose_changes', side_effect=extract):
            asyncio.run(extraction_proposal('看看', observed, []))
        self.assertEqual(len(calls), 2)
        self.assertNotIn('2026-10-01', calls[0])
        self.assertNotIn('2026-01-01', calls[1])

    def test_analyze_exposes_degradation_and_extraction_status(self):
        import time
        import config
        import knowledge.milvus_kb as kb_module
        import swarm
        from web.app import analyze, contexts
        async def close(): pass
        captured = []
        reading = {'complete': True, 'visible_rows': 1, 'text': '', 'rows': [
            {'name': 'GLU', 'result': '5.00', 'unit': 'mmol/L', 'reference': '3.89-6.11',
             'quote': 'GLU 5.00 mmol/L (3.89-6.11)'}]}
        class Client:
            client = SimpleNamespace(close=close)
            async def chat(self, *args, **kwargs): return json.dumps(reading)
        class Coordinator:
            worker_pool = []
            llm_client = SimpleNamespace(client=SimpleNamespace(close=close))
            long_term_memory = SimpleNamespace(enabled=False)
            def __init__(self, **kwargs): pass
            async def process(self, question, **kwargs):
                captured.append(question)
                return {'answer': 'synthetic answer'}
        row = 'GLU【结果】5.00【单位】mmol/L【参考】3.89-6.11'
        proposal = {'operations': [operation('GLU', '5.00', 'image', row)]}
        job = {'steps': [], 'started': time.monotonic()}
        payload = {'message': '看看', 'images': ['synthetic'], 'owner': 'owner', 'chat_id': 'chat',
                   'request_id': 'api-test', 'remember': False}
        try:
            with patch.dict(config.LLM_CONFIG, {'api_key': 'synthetic-not-used'}), \
                 patch('core.LLMClient', Client), patch.object(swarm, 'SwarmCoordinator', Coordinator), \
                 patch.object(kb_module, 'MedicalKnowledgeBase', lambda: SimpleNamespace(search=lambda *a, **k: [])), \
                 patch('web.case_context.propose_changes', AsyncMock(return_value=proposal)):
                asyncio.run(analyze(job, payload, 'synthetic-session', 'owner'))
            self.assertFalse(job['result']['case_index_ready'])
            self.assertTrue(job['result']['data_warnings'])
            self.assertEqual(job['result']['extraction_check']['unmatched_rows'], 0)
            self.assertIn('语义检索暂不可用', captured[0])
        finally:
            contexts.pop('synthetic-session', None)


class ReportReaderTests(unittest.IsolatedAsyncioTestCase):
    def image(self):
        stream = io.BytesIO()
        Image.new('RGB', (100, 100), 'white').save(stream, 'JPEG')
        return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode()

    def response(self, complete=True):
        return {'complete': complete, 'visible_rows': 1, 'text': '2026-10-01', 'rows': [
            {'name': 'GLU', 'result': '5.00', 'unit': 'mmol/L', 'reference': '3.89-6.11',
             'quote': 'GLU 5.00 mmol/L (3.89-6.11)'}]}

    async def test_images_are_read_independently(self):
        client = SimpleNamespace(chat=AsyncMock(return_value=json.dumps(self.response())))
        result = await read_reports(client, [self.image(), self.image()])
        self.assertEqual(client.chat.await_count, 2)
        self.assertEqual(len(result['images']), 2)
        self.assertFalse(result['warnings'])

    async def test_truncated_response_retries_crops_and_deduplicates(self):
        responses = [{'content': json.dumps(self.response()), 'finish_reason': 'length'}]
        responses += [json.dumps(self.response())] * 4
        client = SimpleNamespace(chat=AsyncMock(side_effect=responses))
        result = await read_reports(client, [self.image()])
        self.assertEqual(client.chat.await_count, 5)
        self.assertEqual(result['images'][0]['readable_rows'], 1)
        self.assertFalse(result['warnings'])

    async def test_wrong_result_is_not_silently_used(self):
        response = self.response()
        response['rows'][0]['result'] = '6.11'
        client = SimpleNamespace(chat=AsyncMock(return_value=json.dumps(response)))
        result = await read_reports(client, [self.image()])
        self.assertEqual(result['images'][0]['readable_rows'], 0)
        self.assertTrue(result['warnings'])

    async def test_llm_metadata_is_opt_in_and_not_forwarded_to_provider(self):
        from core.llm_client import LLMClient
        client = object.__new__(LLMClient)
        client.temperature, client.max_tokens, client.model_name = 0.7, 200, 'synthetic'
        client.model_type, client.config = 'openai_compatible', {}
        create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='synthetic'), finish_reason='length')]))
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.assertEqual(await client.chat([]), 'synthetic')
        response = await client.chat([], _return_metadata=True)
        self.assertEqual(response, {'content': 'synthetic', 'finish_reason': 'length'})
        self.assertNotIn('_return_metadata', create.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
