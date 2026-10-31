import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from .case_memory import CaseMemory, MemoryConflict
from .web_mem0 import WebMem0Memory, Mem0Error


class FakePlatform:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.fail = False
        self.pending = False
        self.foreign = None
        self.search_override = None

    def handle(self, request):
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        if self.fail: return httpx.Response(503, json={'secret':'provider-body-must-not-leak'})
        path = request.url.path
        if path == '/v3/memories/add/':
            if self.pending: return httpx.Response(200, json={'event_id':'pending-test'})
            ident = str(uuid.uuid4())
            self.records[ident] = dict(id=ident, user_id=body['user_id'], memory=body['messages'][0]['content'], metadata=copy.deepcopy(body['metadata']))
            return httpx.Response(200, json={'results':[{'id':ident}], 'message':'added'})
        if path.startswith('/v1/event/'):
            return httpx.Response(200,json={'status':'FAILED'})
        if path in ['/v3/memories/','/v3/memories/search/']:
            rows = [copy.deepcopy(row) for row in self.records.values() if row['user_id']==body['filters']['user_id']]
            if path == '/v3/memories/search/' and self.search_override is not None:
                rows = copy.deepcopy(self.search_override)
            for row in rows: row['score']=.9
            if self.foreign: rows.append(copy.deepcopy(self.foreign))
            return httpx.Response(200,json={'results':rows,'next':None,'count':len(rows)})
        ident = path.strip('/').split('/')[-1]
        if ident not in self.records: return httpx.Response(404,json={})
        if request.method == 'GET': return httpx.Response(200,json=copy.deepcopy(self.records[ident]))
        if request.method == 'PUT':
            self.records[ident]['memory'] = body.get('text', self.records[ident]['memory'])
            self.records[ident]['metadata'] = copy.deepcopy(body['metadata'])
            return httpx.Response(200,json=self.records[ident])
        if request.method == 'DELETE':
            del self.records[ident]
            return httpx.Response(200,json={'message':'deleted'})
        raise AssertionError((request.method,path))


class WebMem0Tests(unittest.TestCase):
    def route_client(self):
        from fastapi import Request
        from fastapi.testclient import TestClient
        from auth.dependencies import require_user
        from web.app import app
        previous = dict(app.dependency_overrides)
        def principal(request: Request):
            return SimpleNamespace(id=request.headers.get('X-Test-User','a'*32))
        app.dependency_overrides[require_user] = principal
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        client = TestClient(app,headers={'Origin':'http://127.0.0.1:8765','X-Medix-Request':'1'})
        self.addCleanup(client.close)
        return client

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.local = CaseMemory(Path(self.directory.name)/'memory.db')
        self.platform = FakePlatform()
        self.store = WebMem0Memory(self.local, api_key='synthetic-key', transport=httpx.MockTransport(self.platform.handle))

    def test_edit_overwrites_same_cloud_id_and_preserves_provenance(self):
        ident = self.store.save('owner','mother-session','我母亲今天感冒','mother')
        self.store.change('owner',ident,'retire')
        before = copy.deepcopy(self.platform.records[ident]['metadata'])
        self.assertIsNone(self.store.update('stranger',ident,'内容','',0))
        updated = self.store.update('owner',ident,'我母亲最近睡眠不好','虚构图片：血压记录',0)
        self.assertEqual(set(self.platform.records),{ident})
        self.assertEqual(updated['id'],ident)
        self.assertEqual(updated['patient'],'mother')
        self.assertEqual(updated['active'],0)
        self.assertEqual(updated['revision'],1)
        self.assertTrue(updated['edited_at'])
        self.assertEqual(set(updated['topics']),{'睡眠','血压'})
        self.assertNotIn('感冒',updated['topics'])
        row = self.platform.records[ident]
        self.assertIn('虚构图片：血压记录',row['memory'])
        for key in ('owner_id','patient','session_id','recorded_at','active'):
            self.assertEqual(row['metadata'][key],before[key])
        count = sum(call[0]=='PUT' for call in self.platform.calls)
        with self.assertRaises(MemoryConflict): self.store.update('owner',ident,'过期覆盖','',0)
        self.assertEqual(sum(call[0]=='PUT' for call in self.platform.calls),count)
        self.assertEqual(self.store.list('owner',True,scope='family')[0]['content'],updated['content'])

    def test_local_edit_stays_local_and_checks_revision(self):
        ident = self.local.save('owner','old','我父亲血压偏高','father')
        self.assertIsNone(self.store.update('stranger','local:'+ident,'内容','',0))
        row = self.store.update('owner','local:'+ident,'我父亲最近睡眠不好','',0)
        self.assertEqual(row['backend'],'local_legacy')
        self.assertEqual(row['id'],'local:'+ident)
        self.assertEqual(row['topics'],['睡眠'])
        self.assertEqual(self.local.list('owner')[0]['revision'],1)
        with self.assertRaises(MemoryConflict): self.store.update('owner','local:'+ident,'过期覆盖','',0)
        self.assertFalse(self.platform.calls)

    def test_edit_outage_never_reports_success(self):
        ident = self.store.save('owner','first','我头晕')
        self.platform.fail = True
        with self.assertRaises(Mem0Error): self.store.update('owner',ident,'我睡眠不好','',0)

    def test_edit_acknowledgement_without_persistence_is_not_success(self):
        ident = self.store.save('owner','first','我头晕')
        original = self.platform.handle
        def acknowledge_only(request):
            if request.method == 'PUT': return httpx.Response(200,json={'message':'accepted'})
            return original(request)
        store = WebMem0Memory(self.local,api_key='synthetic-key',transport=httpx.MockTransport(acknowledge_only))
        with self.assertRaisesRegex(Mem0Error,'回读核验'):
            store.update('owner',ident,'我睡眠不好','',0)

    def test_current_chat_recall_reads_edited_value_instead_of_stale_search(self):
        ident = self.store.save('owner','fever-chat','我昨晚发烧到39度。','self')
        stale = copy.deepcopy(self.platform.records[ident])
        self.store.update('owner',ident,'我昨晚发烧到38度。','',0)
        self.platform.search_override = [stale]
        row = self.store.related('owner','fever-chat','我昨晚发烧到多少度？','self')[0]
        self.assertEqual(row['id'],ident)
        self.assertEqual(row['content'],'我昨晚发烧到38度。')
        self.assertEqual(row['revision'],1)
        self.assertIn('修改后的记忆',row['reason'])
        self.assertIn('发烧',row['highlight_terms'])
        self.assertEqual(self.store.related('owner','fever-chat','我昨晚发烧到多少度？','mother'),[])
        self.assertEqual(self.store.related('stranger','fever-chat','我昨晚发烧到多少度？','self'),[])
        self.store.change('owner',ident,'retire')
        self.assertEqual(self.store.related('owner','fever-chat','我昨晚发烧到多少度？','self'),[])
        self.store.change('owner',ident,'delete')
        self.assertEqual(self.store.related('owner','fever-chat','我昨晚发烧到多少度？','self'),[])

    def test_search_index_miss_falls_back_to_current_person_latest_record(self):
        ident = self.store.save('owner','fever-chat','我昨晚发烧到39度。','self')
        self.store.update('owner',ident,'我昨晚发烧到38度。','',0)
        self.platform.search_override = []
        for session in ('fever-chat','new-chat'):
            rows=self.store.related('owner',session,'我昨晚体温是多少？','self')
            self.assertEqual([row['id'] for row in rows],[ident])
            self.assertIn('38',rows[0]['content'])
        self.store.change('owner',ident,'exclude','fever-chat')
        self.assertEqual(self.store.related('owner','fever-chat','我昨晚体温是多少？','self'),[])
        self.assertTrue(self.store.related('owner','new-chat','我昨晚体温是多少？','self'))

    def test_edit_route_validates_ownership_revision_and_clears_contexts(self):
        from fastapi.testclient import TestClient
        from web.app import app, contexts
        client = self.route_client()
        owner = 'a'*32
        ident = self.store.save(owner,'old','我母亲今天感冒','mother')
        chat_id = str(uuid.uuid4())
        session = 'web-'+owner+'-'+chat_id
        body = dict(content='我母亲最近睡眠不好',observations='',expected_revision=0,chat_id=chat_id)
        try:
            contexts[session] = {'old':'旧症状'}
            with patch('web.app.get_web_memory',return_value=self.store):
                for invalid in ({'content':'  '},{'expected_revision':True},{'observations':[]},{'chat_id':None}):
                    self.assertEqual(client.post(f'/api/memories/{ident}/edit',json=body|invalid).status_code,400)
                response = client.post(f'/api/memories/{ident}/edit',json=body)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['record']['id'],ident)
                self.assertEqual(response.json()['backend'],'mem0')
                self.assertNotIn(session,contexts)
                self.assertEqual(client.post(f'/api/memories/{ident}/edit',json=body).status_code,409)
                client.headers['X-Test-User'] = 'b'*32
                self.assertEqual(client.post(f'/api/memories/{ident}/edit',json=body).status_code,404)
        finally: contexts.pop(session,None)

    def test_raw_cloud_save_roundtrip_and_no_legacy_upload(self):
        self.local.save('owner','old','我最近头晕')
        ident = self.store.save('owner','first','我最近头晕','self','图片读取：血压记录')
        row = self.platform.records[ident]
        add = next(call[2] for call in self.platform.calls if call[1]=='/v3/memories/add/')
        self.assertFalse(add['infer'])
        self.assertEqual(row['metadata']['original_content'],'我最近头晕')
        self.assertEqual(row['metadata']['observations'],'图片读取：血压记录')
        self.assertEqual(len(self.platform.records),1)
        listed = self.store.list('owner',include_inactive=True)
        self.assertEqual({row['backend'] for row in listed},{'mem0','local_legacy'})

    def test_mother_cold_is_saved_in_mother_cloud_group(self):
        question='虚构功能测试：我母亲今天有点感冒，想咨询日常照护。'
        ident=self.store.save('owner','mother-cold',question,'mother')
        row=self.store.list('owner',include_inactive=True,scope='family')[0]
        self.assertEqual(row['id'],ident)
        self.assertEqual(row['patient'],'mother')
        self.assertIn('感冒',row['topics'])
        self.assertEqual(row['content'],question)

    def test_confirmed_personal_health_is_not_limited_to_topic_dictionary(self):
        ident=self.store.save('owner','unlisted','膝关节肿胀伴晨僵，持续两天。','mother')
        self.assertIsNotNone(ident)
        self.assertEqual(self.platform.records[ident]['metadata']['patient'],'mother')
        self.assertEqual(self.platform.records[ident]['metadata']['topics'],[])
        self.assertIsNone(self.store.save('owner','empty','   ','mother'))
        self.assertIsNone(self.store.save('owner','unknown','膝关节肿胀','other'))

    def test_patient_scope_search_highlight_and_reject_foreign_results(self):
        ident = self.store.save('owner','first','我晚上头晕')
        self.store.save('owner','father','我爸爸血压偏高','father')
        result = self.store.related('owner','new','我白天也头晕','self')
        self.assertEqual([row['id'] for row in result],[ident])
        self.assertIn('头晕',result[0]['highlight_terms'])
        self.assertEqual(self.store.related('owner','first','我头晕','self')[0]['id'],ident)
        self.assertEqual(self.store.related('owner','new','我头晕','father'),[])
        self.assertEqual(self.store.related('stranger','new','我头晕','self'),[])
        self.platform.foreign = dict(self.platform.records[ident], user_id='another-user')
        self.assertEqual(self.store.related('stranger','new','我头晕','self'),[])

    def test_exclude_retire_delete_and_cross_owner_mutation(self):
        ident = self.store.save('owner','first','我头晕')
        self.assertFalse(self.store.change('stranger',ident,'delete'))
        self.assertTrue(self.store.change('owner',ident,'exclude','new'))
        self.assertEqual(self.store.related('owner','new','我头晕','self'),[])
        self.assertTrue(self.store.related('owner','another','我头晕','self'))
        self.assertTrue(self.store.change('owner',ident,'retire'))
        self.assertEqual(self.store.related('owner','another','我头晕','self'),[])
        self.assertEqual(self.store.list('owner',include_inactive=True)[0]['active'],0)
        self.assertTrue(self.store.change('owner',ident,'delete'))
        self.assertEqual(self.platform.records,{})

    def test_list_metadata_string_topics_are_normalized_for_source_highlighting(self):
        ident = self.store.save('owner','first','我最近睡眠不好')
        self.platform.records[ident]['metadata']['topics'] = '["睡眠"]'
        row = self.store.list('owner', scope='self')[0]
        self.assertEqual(row['topics'], ['睡眠'])
        self.assertTrue(self.store.related('owner','new','我又失眠','self'))
        self.platform.records[ident]['metadata']['topics'] = "['睡眠']"
        self.assertEqual(self.store.list('owner',scope='self')[0]['topics'],['睡眠'])

    def test_cloud_outage_is_not_silent_local_success(self):
        self.local.save('owner','old','我头晕')
        self.platform.fail = True
        for call in [lambda:self.store.save('owner','new','我头晕'), lambda:self.store.related('owner','new','我头晕','self'), lambda:self.store.list('owner')]:
            with self.assertRaises(Mem0Error) as error: call()
            self.assertNotIn('provider-body',str(error.exception))
            self.assertNotIn('synthetic-key',str(error.exception))

    def test_pending_failure_is_not_saved(self):
        self.platform.pending = True
        with self.assertRaises(Mem0Error): self.store.save('owner','first','我头晕')

    def test_archive_change_is_owner_scoped_and_stays_local(self):
        ident = self.local.save('owner','old','我头晕')
        self.assertFalse(self.store.change('stranger','local:'+ident,'delete'))
        self.assertTrue(self.store.change('owner','local:'+ident,'retire'))
        self.assertFalse(self.platform.calls)

    def test_real_web_routes_use_cloud_and_surface_failure(self):
        from fastapi.testclient import TestClient
        from web.app import app
        client=self.route_client()
        owner='a'*32
        ident = self.store.save(owner,'first','我头晕')
        self.store.save(owner,'father','我爸爸血压偏高','father')
        with patch('web.app.get_web_memory',return_value=self.store):
            self.assertEqual(client.get('/api/memories?scope=family').json()['memories'][0]['patient'],'father')
            response=client.post('/api/memories/'+ident,json={'action':'retire','chat_id':str(uuid.uuid4())})
            self.assertEqual(response.json()['backend'],'mem0')
            self.platform.fail=True
            self.assertEqual(client.get('/api/memories').status_code,503)


class ScopedToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mem0_tool_uses_only_authorized_request_references(self):
        from core.agent_loop import AgentLoop
        from core.llm_client import LLMResponse, ToolCall
        loop=AgentLoop(); loop.validator=None
        llm=SimpleNamespace(chat_with_tools=AsyncMock(side_effect=[
            LLMResponse('',[ToolCall('1','search_similar_cases',{'query':'history'})],'tool_calls'),
            LLMResponse('参考 [M1]',[],'stop')]), create_tool_message=lambda **kw:{'role':'tool','content':str(kw['result']),'tool_call_id':kw['tool_call_id']})
        agent=SimpleNamespace(agent_id='scoped-test', config={}, get_system_prompt=lambda:'system',
            format_user_input=lambda data:data['question'], get_tools_for_llm=lambda:[], llm_client=llm,
            execute_tool=AsyncMock(side_effect=AssertionError('unscoped tool must not run')))
        result=await loop.run(agent,{'question':'我头晕','context':{'memory_policy':'mem0','memory_references':[{'reference':'M1','content':'授权原文'}]}})
        self.assertIn('[M1]',result['answer'])
        agent.execute_tool.assert_not_awaited()
        self.assertTrue(any('授权原文' in str(item) for item in llm.chat_with_tools.call_args.kwargs['messages'] if item['role']=='tool'))

class CloudAnalyzeTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_uses_cloud_provenance_and_off_makes_no_cloud_calls(self):
        import config
        import time
        from web.app import analyze, contexts
        with tempfile.TemporaryDirectory() as directory:
            platform = FakePlatform()
            cloud = WebMem0Memory(CaseMemory(Path(directory)/'source.db'), api_key='synthetic', transport=httpx.MockTransport(platform.handle))
            ident = cloud.save('owner','old','我晚上头晕')
            process = AsyncMock(return_value={'answer':'参考之前的记录 [M1]。请确认是否同一次不适。'})
            client = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
            coordinator = SimpleNamespace(short_term_memory=SimpleNamespace(clear_session=lambda _:None),worker_pool=[],llm_client=client,process=process)
            payload={'message':'我今天也头晕','images':[],'remember':True,'patient':'self'}
            job={'steps':[],'started':time.monotonic()}
            chunk='-8小时，最大2.4g/日\n- 补充水分：发热时水分蒸发增加，需要多饮水。'
            hits=[{'score':.9,'content':chunk,'metadata':{'filename':'05_symptoms_emergency.txt'}}]
            with patch('web.app.resolve_patient',new=AsyncMock(return_value=__import__('memory.patient_resolver',fromlist=['resolution']).resolution('self',.99,'我',should_store=True))), patch('web.app.get_web_memory',return_value=cloud), patch.dict(config.LLM_CONFIG,api_key='synthetic'), patch('knowledge.milvus_kb.MedicalKnowledgeBase',return_value=SimpleNamespace(search=lambda *args,**kw:hits)), patch('swarm.SwarmCoordinator',return_value=coordinator):
                await analyze(job,payload,'cloud-web-new','owner')
                self.assertEqual(job['result']['sources'][0]['title'],'急症症状识别与处理')
                self.assertEqual(job['result']['sources'][0]['content'],chunk)
                self.assertEqual(job['result']['memory_backend'],'mem0')
                self.assertEqual(job['result']['memory_status'],'saved')
                self.assertEqual(job['result']['memory_references'][0]['id'],ident)
                self.assertEqual(job['result']['memory_references'][0]['backend'],'mem0')
                self.assertEqual(process.call_args.kwargs['context']['memory_policy'],'mem0')
                self.assertEqual(len(platform.records),2)
                calls=len(platform.calls)
                payload['remember']=False
                await analyze(job,payload,'cloud-web-off','owner')
                self.assertEqual(len(platform.calls),calls)
                self.assertEqual(job['result']['memory_status'],'off')
                platform.fail=True; payload['remember']=True
                await analyze(job,payload,'cloud-web-failure','owner')
                self.assertEqual(job['result']['memory_status'],'error')
                self.assertIsNone(job['result']['memory_saved'])
                self.assertNotIn('provider-body',job['result']['memory_error'])
            for key in ['cloud-web-new','cloud-web-off','cloud-web-failure']: contexts.pop(key,None)


class AutoPatientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_subject_skips_cloud_and_confirmation_keeps_symptoms(self):
        import time
        import config
        from web.app import analyze, contexts
        from memory.patient_resolver import resolution
        with tempfile.TemporaryDirectory() as directory:
            platform=FakePlatform()
            cloud=WebMem0Memory(CaseMemory(Path(directory)/'source.db'),api_key='synthetic',transport=httpx.MockTransport(platform.handle))
            process=AsyncMock(return_value={'answer':'请补充情况。'})
            coordinator=SimpleNamespace(short_term_memory=SimpleNamespace(clear_session=lambda _:None),worker_pool=[],llm_client=SimpleNamespace(client=SimpleNamespace(close=AsyncMock())),process=process)
            payload={'message':'最近头晕三天了','images':[],'remember':True}
            job={'steps':[],'started':time.monotonic()}
            session='auto-patient-test'
            try:
                with patch('web.app.get_web_memory',return_value=cloud),patch.dict(config.LLM_CONFIG,api_key='synthetic'),patch('knowledge.milvus_kb.MedicalKnowledgeBase',return_value=SimpleNamespace(search=lambda *a,**kw:[])),patch('swarm.SwarmCoordinator',return_value=coordinator),patch('web.app.resolve_patient',new=AsyncMock(side_effect=[resolution(),resolution('father',.99,'我爸爸',confirms_previous=True,should_store=True),resolution('self',.99,'我自己',should_store=True),resolution('self',.99,'我自己',should_store=False,memory_reason='追问未增加健康事实')])):
                    await analyze(job,payload,session,'owner')
                    self.assertEqual(platform.calls,[])
                    self.assertTrue(job['result']['patient_resolution']['needs_confirmation'])
                    self.assertIn('这次是在问你本人',job['result']['answer'])
                    payload['message']='是我爸爸的情况'
                    await analyze(job,payload,session,'owner')
                    saved=list(platform.records.values())[0]
                    self.assertEqual(saved['metadata']['patient'],'father')
                    self.assertIn('最近头晕三天了',saved['metadata']['original_content'])
                    self.assertTrue(any('最近头晕三天了' in row['content'] for row in contexts[session]['history'] if row.get('patient')=='father'))
                    contexts[session]['image_observations']='父亲报告原文'
                    payload['message']='我自己最近咳嗽'
                    await analyze(job,payload,session,'owner')
                    current=process.call_args.kwargs['context']
                    self.assertEqual(current['patient'],'本人')
                    self.assertEqual(current['recent_history'],[])
                    self.assertNotIn('父亲报告原文',process.call_args.args[0])
                    self.assertEqual(contexts[session]['image_observations'],'')
                    count=len(platform.records)
                    payload['message']='那我自己应该注意什么？'
                    await analyze(job,payload,session,'owner')
                    self.assertEqual(len(platform.records),count)
                    self.assertEqual(job['result']['memory_status'],'skipped')
                    self.assertFalse(job['result']['memory_decision']['should_store'])
                    self.assertEqual(job['result']['memory_decision']['reason'],'追问未增加健康事实')
            finally:
                contexts.pop(session,None)


    async def test_explicit_person_correction_retires_wrong_group_and_preserves_quotes(self):
        import time
        import config
        from web.app import analyze, contexts
        from memory.patient_resolver import resolution
        with tempfile.TemporaryDirectory() as directory:
            platform=FakePlatform(); cloud=WebMem0Memory(CaseMemory(Path(directory)/'source.db'),api_key='synthetic',transport=httpx.MockTransport(platform.handle))
            coordinator=SimpleNamespace(short_term_memory=SimpleNamespace(clear_session=lambda _:None),worker_pool=[],llm_client=SimpleNamespace(client=SimpleNamespace(close=AsyncMock())),process=AsyncMock(return_value={'answer':'请补充情况。'}))
            payload={'message':'我爸最近睡眠不好','images':[],'remember':True}; job={'steps':[],'started':time.monotonic()}; session='auto-correction-test'
            try:
                with patch('web.app.get_web_memory',return_value=cloud),patch.dict(config.LLM_CONFIG,api_key='synthetic'),patch('knowledge.milvus_kb.MedicalKnowledgeBase',return_value=SimpleNamespace(search=lambda *a,**kw:[])),patch('swarm.SwarmCoordinator',return_value=coordinator),patch('web.app.resolve_patient',new=AsyncMock(side_effect=[resolution('father',.99,'我爸',should_store=True),resolution('mother',.99,'我妈',corrects_previous=True,should_store=True)])):
                    await analyze(job,payload,session,'owner')
                    payload['message']='刚才其实是我妈的情况'
                    await analyze(job,payload,session,'owner')
                    rows=list(platform.records.values())
                    self.assertFalse(next(row for row in rows if row['metadata']['patient']=='father')['metadata']['active'])
                    mother=next(row for row in rows if row['metadata']['patient']=='mother')
                    self.assertIn('我爸最近睡眠不好',mother['metadata']['original_content'])
                    self.assertIn('刚才其实是我妈',mother['metadata']['original_content'])
                    self.assertEqual(job['result']['patient_resolution']['patient'],'mother')
            finally: contexts.pop(session,None)
