import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from memory.case_memory import CaseMemory, patient_for, memory_context, referenced


class CaseMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CaseMemory(Path(self.temp.name) / 'cases.db')
        self.ident = self.store.save('alice', 'previous', '我最近晚上头晕，持续三天。')

    def test_only_same_patient_and_owner_including_current_session(self):
        self.assertEqual(len(self.store.related('alice', 'new', '我今天头晕', 'self')), 1)
        self.assertEqual(len(self.store.related('alice', 'previous', '我头晕', 'self')), 1)
        for owner, session, question, patient in [
            ('bob', 'new', '我头晕', 'self'),
            ('alice', 'new', '我爸爸头晕', 'father'), ('alice', 'new', '我咳嗽', 'self'),
            ('alice', 'new', '他头晕', 'other')]:
            self.assertEqual(self.store.related(owner, session, question, patient), [])

    def test_edited_temperature_is_recalled_in_same_chat(self):
        ident=self.store.save('alice','fever-chat','我昨晚发烧到39度。')
        self.store.update('alice',ident,'我昨晚发烧到38度。','',0)
        rows=self.store.related('alice','fever-chat','我昨晚体温是多少？','self')
        self.assertEqual(rows[0]['id'],ident)
        self.assertIn('38',rows[0]['content'])
        self.assertNotIn('39',rows[0]['content'])

    def test_demo_retirement_does_not_reseed_and_can_delete_retired(self):
        self.store.seed_demo('demo', '2026-10-23T00:00:00+00:00')
        ident = self.store.list('demo')[0]['id']
        self.store.change('demo', ident, 'retire')
        self.store.seed_demo('demo', '2026-10-24T00:00:00+00:00')
        self.assertFalse(self.store.list('demo'))
        self.assertEqual(len(self.store.list('demo', include_inactive=True)), 1)
        self.assertTrue(self.store.change('demo', ident, 'delete'))
        self.assertFalse(self.store.list('demo', include_inactive=True))

    def test_subject_detection(self):
        self.assertEqual(patient_for('我爸爸头晕'), 'father')
        self.assertEqual(patient_for('我妈妈头晕'), 'mother')
        self.assertEqual(patient_for('父亲和母亲头晕'), 'other')
        self.assertEqual(patient_for('我爸头晕，我也头晕'), 'other')
        self.assertEqual(patient_for('我朋友头晕'), 'other')

    def test_exclusion_is_session_scoped_and_owner_checked(self):
        self.assertFalse(self.store.change('bob', self.ident, 'delete'))
        self.store.save('alice', 'previous', '我今天还头晕')
        self.assertTrue(self.store.change('alice', self.ident, 'exclude', 'new'))
        self.assertFalse(self.store.related('alice', 'new', '我头晕', 'self'))
        self.assertTrue(self.store.related('alice', 'another', '我头晕', 'self'))

    def test_retire_and_delete(self):
        self.assertTrue(self.store.change('alice', self.ident, 'retire'))
        self.assertFalse(self.store.related('alice', 'new', '我头晕', 'self'))
        ident = self.store.save('alice', 'next', '我头晕')
        self.assertTrue(self.store.change('alice', ident, 'delete'))
        self.assertFalse(self.store.list('alice'))

    def test_no_general_advice_or_unknown_patient_saved(self):
        self.assertIsNone(self.store.save('alice', 'new', '高血压是什么？'))
        self.assertIsNone(self.store.save('alice', 'new', '患者头晕', 'other'))

    def test_only_existing_cited_ids_are_displayed(self):
        refs = memory_context(self.store.related('alice', 'new', '我头晕', 'self'))
        clean, used = referenced('参考 [M1]，未知 [M99]', refs)
        self.assertEqual(len(used), 1)
        self.assertNotIn('[M', clean)
        self.assertEqual(referenced('未引用', refs)[1], [])

    def test_real_endpoints_demo_isolation_and_correction(self):
        from storage.test_support import account_clients
        import uuid
        with account_clients() as accounts:
            client, other = accounts.clients
            chat_id = str(uuid.uuid4())
            data = client.post('/api/memory/demo', json={'chat_id':chat_id}).json()
            self.assertTrue(data['demo'])
            self.assertEqual(len(data['memory_references']), 1)
            record = data['memory_references'][0]
            response = other.post('/api/memories/'+record['id'],json={'action':'delete','chat_id':chat_id,'demo':True})
            self.assertEqual(response.status_code,404)
            response = client.post('/api/memories/'+record['id'],json={'action':'exclude','chat_id':chat_id,'demo':True})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.post('/api/memory/demo',json={'chat_id':chat_id}).json()['memory_references'],[])
            from storage.business import connect
            with connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM memory_cases').fetchone()[0],0)
                self.assertGreater(db.execute('SELECT count(*) FROM demo_memory_cases').fetchone()[0],0)


class ContextTests(unittest.TestCase):
    def test_all_agents_receive_memory_context(self):
        from core.agent_loop import AgentLoop
        from types import SimpleNamespace
        loop = AgentLoop()
        agent = SimpleNamespace(get_system_prompt=lambda:'system', format_user_input=lambda data:data['question'])
        messages = loop._initialize_messages(agent, {'question':'我头晕', 'context':{'memory_references':[{'reference':'M1','content':'我以前头晕'}]}})
        self.assertTrue(any('M1' in m['content'] for m in messages))
        self.assertEqual(messages[-1]['content'], '我头晕')


if __name__ == '__main__': unittest.main()

class AnalyzeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_analyze_passes_sources_and_saves_only_raw_input(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        import config
        from web.app import analyze, contexts
        with tempfile.TemporaryDirectory() as directory:
            store = CaseMemory(Path(directory) / 'cases.db')
            store.save('isolated-owner', 'old-session', '我最近晚上头晕')
            process = AsyncMock(return_value={'answer':'参考之前的记录 [M1]。请确认是否同一次不适。'})
            client = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
            coordinator = SimpleNamespace(short_term_memory=SimpleNamespace(clear_session=lambda _:None),worker_pool=[], llm_client=client, process=process)
            payload = {'message':'我今天白天也头晕', 'images':[], 'remember':True, 'patient':'self'}
            import time
            job = {'steps':[], 'started':time.monotonic()}
            with patch('web.app.resolve_patient',new=AsyncMock(return_value=__import__('memory.patient_resolver',fromlist=['resolution']).resolution('self',.99,'我',should_store=True))), patch('web.app.memory_journal', store), patch('web.app.WebMem0Memory', return_value=store), patch.dict(config.LLM_CONFIG, api_key='test'), patch('knowledge.milvus_kb.MedicalKnowledgeBase', return_value=SimpleNamespace(search=lambda *args, **kw:[])), patch('swarm.SwarmCoordinator', return_value=coordinator) as factory:
                await analyze(job, payload, 'new-isolated-session', 'isolated-owner')
                factory.assert_called_once_with(enable_long_term_memory=False, memory_user_id='isolated-owner', persist_session_summaries=False)
                self.assertEqual(process.call_args.kwargs['context']['memory_references'][0]['content'], '我最近晚上头晕')
                self.assertEqual(job['result']['memory_status'], 'saved')
                self.assertEqual(len(job['result']['memory_references']), 1)
                self.assertNotIn('[M1]', job['result']['answer'])
                saved = store.list('isolated-owner')[0]
                self.assertEqual(saved['content'], payload['message'])
                self.assertNotIn('请优先', saved['content'])
                before = len(store.list('isolated-owner'))
                payload['remember'] = False
                await analyze(job, payload, 'off-isolated-session', 'isolated-owner')
                self.assertEqual(process.call_args.kwargs['context']['memory_references'], [])
                self.assertEqual(job['result']['memory_status'], 'off')
                self.assertEqual(len(store.list('isolated-owner')), before)
            contexts.pop('new-isolated-session', None)
            contexts.pop('off-isolated-session', None)
