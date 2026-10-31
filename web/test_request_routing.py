"""Top-level routing, independently of medical corpus coverage."""
import asyncio
import json
import os
import time
import unittest
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from storage.test_support import account_clients
from web.request_routing import classify_request

class SemanticRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_and_private_stream_stage(self):
        client=NS(chat=AsyncMock(return_value=json.dumps({'kind':'personal','subject':'self'})))
        prior={'history':[{'role':'user','content':'我是小林'}]}
        result=await classify_request('还记得我的名字吗',prior,client=client)
        self.assertEqual(result['kind'],'personal')
        args=client.chat.call_args
        self.assertEqual(args.kwargs['_agent'],'stage:request_router')
        self.assertIn('我是小林',args.args[0][1]['content'])

    async def test_invalid_route_is_not_a_knowledge_gap(self):
        for response in ('bad json','{"kind":"ignore_auth","subject":"self"}'):
            with self.assertRaisesRegex(ValueError,'没有理解本次请求'):
                await classify_request('随便聊聊',{},client=NS(chat=AsyncMock(return_value=response)))

    async def test_nonpersonal_routes_do_not_require_person_identity(self):
        for kind in ('conversation','action','medical','report'):
            for subject in (None,'unknown','none',{'unexpected':'object'}):
                client=NS(chat=AsyncMock(return_value=json.dumps({'kind':kind,'subject':subject})))
                result=await classify_request('一个普通请求',{},client=client)
                self.assertEqual(result,{'kind':kind,'subject':'general'})
                client.chat.assert_awaited_once()

    async def test_personal_missing_subject_does_not_guess_self(self):
        client=NS(chat=AsyncMock(return_value='{"kind":"personal"}'))
        result=await classify_request('记得那个人吗',{},client=client)
        self.assertEqual(result['subject'],'unknown')

    async def test_format_retry_and_fenced_json(self):
        client=NS(chat=AsyncMock(side_effect=['invalid','```json\n{"kind":"conversation","subject":null}\n```']))
        self.assertEqual((await classify_request('聊聊吧',{},client=client))['kind'],'conversation')
        self.assertEqual(client.chat.await_count,2)

    async def test_provider_failures_are_not_mislabeled_as_bad_intent(self):
        client=NS(chat=AsyncMock(side_effect=RuntimeError('provider unavailable')))
        with self.assertRaisesRegex(RuntimeError,'provider unavailable'):
            await classify_request('聊聊吧',{},client=client)
        client.chat.assert_awaited_once()

    async def test_deepseek_router_disables_reasoning_without_changing_text_config(self):
        client=NS(model_name='deepseek-flash',chat=AsyncMock(return_value='{"kind":"medical","subject":"general"}'))
        await classify_request('健康问题',{},client=client)
        self.assertEqual(client.chat.call_args.kwargs['extra_body'],{'thinking':{'type':'disabled'}})

    async def test_images_route_to_report_without_classifier(self):
        client=NS(chat=AsyncMock())
        self.assertEqual((await classify_request('看看这张',{},images=True,client=client))['kind'],'report')
        client.chat.assert_not_called()

class RoutingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.scope=account_clients();self.fixture=self.scope.__enter__()
    def tearDown(self): self.scope.__exit__(None,None,None)

    def analyze(self,question,kind,subject='self',index=0,remember=False):
        import web.app as web
        from config import LLM_CONFIG
        owner=self.fixture.users[index].id
        job={'started':time.monotonic(),'steps':[],'owner_user_id':owner}
        payload={'message':question,'images':[],'remember':remember,'owner':owner,
                 'chat_id':str(uuid.uuid4()),'request_id':str(uuid.uuid4())}
        coordinator=Mock(worker_pool=[])
        coordinator.llm_client=NS(client=NS(close=AsyncMock()))
        coordinator.process=AsyncMock(return_value={'answer':'当前请求已处理','agent_id':'consultation_agent'})
        memory=Mock();memory.related.return_value=[]
        kb=Mock();kb.retrieve.return_value={'status':'needs_information','hits':[],'trace':{},'message':'医学资料不足'}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence'}),patch.dict(LLM_CONFIG,{'api_key':'mock'}), \
             patch('web.request_routing.classify_request',AsyncMock(return_value={'kind':kind,'subject':subject})), \
             patch('knowledge.get_knowledge_base',return_value=kb) as getkb, \
             patch('web.app.prepare_context',AsyncMock(return_value={'case_id':'','facts':[],'context':'','sources':[],'index_ready':True,'outcome':{'changes':[],'questions':[],'switched':False},'warnings':[]})) as cases, \
             patch('swarm.SwarmCoordinator',return_value=coordinator), \
             patch('web.app.get_web_memory',return_value=memory):
            asyncio.run(web.analyze(job,payload,'web-'+owner+'-'+payload['chat_id'],owner))
        return job,coordinator,memory,kb,getkb,cases

    def test_identity_memory_and_actions_do_not_require_medical_coverage(self):
        for question,kind in [('我是谁','personal'),('还记得我之前说过什么吗','personal'),
                              ('帮我设置明天八点的提醒','action'),('我们聊聊今天的计划','conversation')]:
            job,coordinator,memory,kb,getkb,cases=self.analyze(question,kind)
            self.assertEqual(job['result']['answer'],'当前请求已处理')
            getkb.assert_not_called();cases.assert_not_called()
            coordinator.process.assert_awaited_once()
            self.assertEqual(job['request_kind'],kind)
            memory.save.assert_not_called()

    def test_personal_memory_always_uses_authenticated_owner(self):
        for index in (0,1):
            job,coordinator,memory,*_=self.analyze('记得我的事吗','personal',index=index,remember=True)
            self.assertEqual(memory.related.call_args.args[0],self.fixture.users[index].id)
            self.assertEqual(memory.related.call_args.args[-1],'self')
            self.assertIn('服务端当前账号展示名称',coordinator.process.call_args.args[0])
            memory.save.assert_not_called()

    def test_medical_evidence_gap_still_blocks_unsupported_answer(self):
        from memory.patient_resolver import resolution
        with patch('web.app.resolve_patient',AsyncMock(return_value=resolution('self',1))):
            job,coordinator,_,kb,*_=self.analyze('你好，我头痛要吃什么药','medical')
        kb.retrieve.assert_called_once();coordinator.process.assert_not_awaited()
        self.assertEqual(job['result']['answer'],'医学资料不足')

    def test_report_transcription_is_not_blocked_by_public_corpus_gap(self):
        from memory.patient_resolver import resolution
        with patch('web.app.resolve_patient',AsyncMock(return_value=resolution('self',1))):
            job,coordinator,_,kb,*_=self.analyze('核对刚才报告上的数值','report')
        kb.retrieve.assert_called_once();coordinator.process.assert_awaited_once()
        self.assertEqual(job['result']['answer'],'当前请求已处理')
