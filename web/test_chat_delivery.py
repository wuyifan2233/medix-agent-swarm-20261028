"""Conversation durability, SSE transport, cancellation and usage contracts."""
import asyncio
import base64
import io
import json
import threading
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
from openai import AsyncOpenAI
from PIL import Image

from storage.test_support import account_clients
from storage.chat import ChatStore, PersistentContexts, store
from storage.business import connect
from core.chat_runtime import ChatRuntime, completion, runtime, usage_summary, usage_values


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.scope=account_clients(); self.fixture=self.scope.__enter__()
        self.a,self.b=self.fixture.clients
        self.owner=self.fixture.users[0].id
        self.chat=str(uuid.uuid4());self.request=str(uuid.uuid4());self.turn=uuid.uuid4().hex

    def tearDown(self): self.scope.__exit__(None,None,None)

    def seed(self, images=None):
        return store.create_turn(self.owner,self.chat,self.request,self.turn,{'message':'虚构演示','images':images or [],'case_id':''})

    def test_restart_restores_transcript_image_context_and_draft(self):
        self.seed(['data:image/jpeg;base64,test-fixture'])
        key=f'web-{self.owner}-{self.chat}'
        context=PersistentContexts()
        context[key]={'image_observations':'虚构报告：120/80 mmHg','history':[{'role':'user','content':'核对图片'}],'patient':'father','profile_scope':None}
        store.event(self.turn,{'type':'draft_start','call_id':'test','agent':'test'})
        store.event(self.turn,{'type':'delta','call_id':'test','text':'已有草稿'})
        ChatStore().recover()
        self.assertEqual(PersistentContexts()[key]['patient'],'father')
        response=self.a.get('/api/conversations/'+self.chat).json()
        self.assertEqual(response['turns'][0]['payload']['images'],['data:image/jpeg;base64,test-fixture'])
        self.assertEqual(response['turns'][0]['draft'],'已有草稿')
        self.assertEqual(response['turns'][0]['status'],'interrupted')

    def test_owner_and_csrf_checks_cover_all_routes(self):
        self.seed();store.update(self.turn,'completed',{'answer':'私有回答'})
        for suffix in ('','/usage'):
            self.assertEqual(self.b.get('/api/conversations/'+self.chat+suffix).status_code,404)
        self.assertEqual(self.b.patch('/api/conversations/'+self.chat,json={'title':'bad'}).status_code,404)
        self.assertEqual(self.b.delete('/api/conversations/'+self.chat,headers={'Content-Type':'application/json'}).status_code,404)
        self.assertEqual(self.b.get('/api/jobs/'+self.turn+'/events').status_code,404)
        self.assertEqual(self.b.post('/api/jobs/'+self.turn+'/cancel',json={}).status_code,404)
        self.assertEqual(self.b.get('/api/jobs/'+self.turn).status_code,404)
        self.assertEqual(self.a.patch('/api/conversations/'+self.chat,json={'title':'test'},headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(self.a.patch('/api/conversations/'+self.chat,json={'title':'演示会话'}).status_code,200)
        self.assertEqual(self.a.get('/api/conversations').json()['conversations'][0]['title'],'演示会话')

    def test_api_deduplicates_and_normalizes_images_and_serializes_turns(self):
        out=io.BytesIO();Image.new('RGB',(16,16),'white').save(out,format='PNG')
        payload={'chat_id':self.chat,'request_id':self.request,'message':'虚构报告','images':[{'data':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}]}
        with patch('web.app.executor.submit') as submit:
            first=self.a.post('/api/chat',json=payload);self.assertEqual(first.status_code,202)
            second=self.a.post('/api/chat',json=payload)
            self.assertEqual(first.json(),second.json());self.assertEqual(submit.call_count,1)
            saved=store.turn(self.owner,first.json()['job_id'])
            self.assertTrue(saved['payload']['images'][0].startswith('data:image/jpeg;base64,'))
            changed=self.a.post('/api/chat',json={**payload,'message':'不同内容'})
            self.assertEqual(changed.status_code,409)
            parallel=self.a.post('/api/chat',json={**payload,'request_id':str(uuid.uuid4())})
            self.assertEqual(parallel.status_code,409)

    def test_sse_replay_and_deleted_conversation_cascades(self):
        self.seed();store.update(self.turn,'cancelled',error='已停止')
        store.event(self.turn,{'type':'stage','label':'检索'})
        seq=store.event(self.turn,{'type':'delta','text':'草稿','call_id':'x'})
        response=self.a.get('/api/jobs/'+self.turn+'/events',headers={'Last-Event-ID':str(seq-1)})
        self.assertEqual(response.status_code,200)
        self.assertIn('text/event-stream',response.headers['content-type'])
        self.assertNotIn('检索',response.text);self.assertIn('草稿',response.text)
        self.assertIn('"type": "done"',response.text)
        key=f'web-{self.owner}-{self.chat}';PersistentContexts()[key]={'history':[]}
        self.assertEqual(self.a.delete('/api/conversations/'+self.chat,headers={'Content-Type':'application/json'}).status_code,200)
        for table in ('chat_events','chat_contexts','chat_turns'):
            with connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_restored_answer_supports_profile_action_and_delete_hides_cached_job(self):
        from web.app import jobs
        self.seed();store.update(self.turn,'completed',{'answer':'历史回答'})
        payload={'text':'虚构演示','job_id':self.turn,'subject':'self','consent_to_model':True,'expected_revision':0}
        with patch('personalization.conversation_updates.assess',AsyncMock(return_value=[])) as assess:
            response=self.a.post('/api/profile/conversation-candidates',json=payload)
            self.assertEqual(response.status_code,201,response.text)
            assess.assert_awaited_once_with('虚构演示','历史回答')
        jobs[self.turn]={'owner_user_id':self.owner,'status':'completed','_persistent':True,'result':{'answer':'历史回答'}}
        self.assertEqual(self.a.delete('/api/conversations/'+self.chat,headers={'Content-Type':'application/json'}).status_code,200)
        self.assertEqual(self.a.get('/api/jobs/'+self.turn).status_code,404)
        self.assertEqual(self.a.post('/api/profile/conversation-candidates',json=payload).status_code,404)

    def test_greeting_skips_retrieval_model_and_memory_but_persists(self):
        import time
        from web.app import analyze
        self.seed()
        job={'id': self.turn, 'started': time.monotonic(), 'owner_user_id': self.owner}
        with patch('knowledge.get_knowledge_base', side_effect=AssertionError('No KB for greetings')), patch('web.app.resolve_patient', side_effect=AssertionError('No model for greetings')):
            asyncio.run(analyze(job, {'message':'你好！','images':[]}, 'social-test', self.owner))
        self.assertIn('你好', job['result']['answer'])
        self.assertEqual(job['result']['generation'], 'local_social')
        self.assertFalse(job['result']['memory_enabled'])
        store.finish(self.turn, 'completed', job['result'], None, {})
        restored=ChatStore().detail(self.owner,self.chat)
        self.assertEqual(restored['turns'][0]['result']['answer'], job['result']['answer'])
        self.assertEqual(usage_summary(self.turn)['requests'],0)

    def test_active_delete_is_rejected(self):
        self.seed()
        self.assertEqual(self.a.delete('/api/conversations/'+self.chat,headers={'Content-Type':'application/json'}).status_code,409)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scope=account_clients();self.fixture=self.scope.__enter__()
        self.owner=self.fixture.users[0].id;self.chat=str(uuid.uuid4());self.turn=uuid.uuid4().hex
        store.create_turn(self.owner,self.chat,str(uuid.uuid4()),self.turn,{'message':'虚构问题','images':[],'case_id':''})
        self.token=runtime.set(ChatRuntime(self.turn))

    async def asyncTearDown(self):
        runtime.reset(self.token);self.scope.__exit__(None,None,None)

    async def test_sdk_stream_assembles_tools_reasoning_and_terminal_usage(self):
        requests=[]
        def handler(request):
            requests.append(json.loads(request.content))
            deltas=[{'reasoning_content':'PRIVATE_REASONING'}, {'content':'你好'},
                    {'tool_calls':[{'index':0,'id':'call_1','type':'function','function':{'name':'lookup','arguments':'{"q":'}}]},
                    {'tool_calls':[{'index':0,'function':{'arguments':'"test"}'}}]}]
            frames=[{'id':'id','object':'chat.completion.chunk','created':0,'model':'deepseek-flash',
                     'choices':[{'index':0,'delta':delta,'finish_reason':None}]} for delta in deltas]
            frames.append({'id':'id','object':'chat.completion.chunk','created':0,'model':'deepseek-flash',
                           'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]})
            frames.append({'id':'id','object':'chat.completion.chunk','created':0,'model':'deepseek-flash','choices':[],
                           'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':40}})
            data=''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=data.encode())
        sdk=AsyncOpenAI(api_key='mock',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            response=await completion(sdk,{'model':'deepseek-flash','messages':[{'role':'user','content':'fixture'}]},visible=True,agent='worker')
        finally: await sdk.close()
        self.assertTrue(requests[0]['stream']);self.assertTrue(requests[0]['stream_options']['include_usage'])
        message=response.choices[0].message
        self.assertEqual(message.reasoning_content,'PRIVATE_REASONING')
        self.assertEqual(json.loads(message.tool_calls[0].function.arguments),{'q':'test'})
        summary=usage_summary(self.turn)
        self.assertEqual(summary['requests'],1);self.assertEqual(summary['cache_hit_tokens'],40)
        self.assertEqual(summary['output_tokens'],20)
        self.assertEqual(Decimal(summary['estimated_cost']),Decimal('0.0001408'))
        self.assertNotIn('PRIVATE_REASONING',str(store.events(self.turn)))
        self.assertEqual(store.events(self.turn)[-2][1]['type'],'draft_clear')

    async def test_cancel_route_closes_upstream_and_preserves_unknown_usage(self):
        from web.app import run_job, controls, health
        from threading import Event
        emitted=threading.Event();closed=threading.Event()
        class Stream:
            def __aiter__(self): return self
            async def __anext__(self):
                if not emitted.is_set():
                    emitted.set()
                    return NS(usage=None,choices=[NS(index=0,delta=NS(content='部分回答',tool_calls=[],reasoning_content=None),finish_reason=None)])
                await asyncio.sleep(60)
            async def close(self):closed.set()
        create=AsyncMock(return_value=Stream())
        client=NS(chat=NS(completions=NS(create=create)));client.with_options=lambda **kw:client
        async def analyze(*args):
            await completion(client,{'model':'deepseek-flash'},visible=True,agent='worker')
        controls[self.turn]={'cancel':Event()}
        job={'id':self.turn,'owner_user_id':self.owner,'steps':[],'_persistent':True}
        with patch('web.app.analyze',analyze),patch.dict(health,{'knowledge':'ready'}):
            task=asyncio.create_task(asyncio.to_thread(run_job,job,{},f'web-{self.owner}-{self.chat}',self.owner))
            self.assertTrue(await asyncio.to_thread(emitted.wait,5))
            response=self.fixture.clients[0].post('/api/jobs/'+self.turn+'/cancel',json={})
            self.assertTrue(response.json()['cancel_requested'])
            await asyncio.wait_for(task,5)
        self.assertTrue(closed.is_set())
        self.assertEqual(store.turn(self.owner,self.turn)['status'],'cancelled')
        summary=usage_summary(self.turn)
        self.assertEqual(summary['requests'],1);self.assertEqual(summary['unknown_requests'],1)
        self.assertIsNone(summary['estimated_cost'])
        self.assertTrue(any(event['type']=='delta' and event['text']=='部分回答' for _,event in store.events(self.turn)))

    async def test_failed_attempts_and_retries_are_separate_unknown_records(self):
        create=AsyncMock(side_effect=RuntimeError('network failure'))
        client=NS(chat=NS(completions=NS(create=create)));client.with_options=lambda **kw:client
        for _ in range(2):
            with self.assertRaises(RuntimeError):await completion(client,{'model':'deepseek-flash'})
        summary=usage_summary(self.turn)
        self.assertEqual(summary['requests'],2);self.assertEqual(summary['unknown_requests'],2)


class PriceTests(unittest.TestCase):
    def test_cached_tokens_are_not_charged_twice(self):
        values=usage_values({'prompt_tokens':100,'completion_tokens':10,'prompt_cache_hit_tokens':60},
                            {'input':'2','cached_input':'0.5','output':'3'})
        self.assertEqual(Decimal(values[3]),Decimal('0.00014'))
        self.assertIsNone(usage_values(None,None))
        self.assertIsNone(usage_values({'prompt_tokens':1,'completion_tokens':0,'prompt_cache_hit_tokens':2},None))

    def test_explicit_document_reference_preserves_fictional_image_without_cross_person_history(self):
        from web.app import document_followup_text
        previous={'document_context':{'text':'第二次 136/88 脉搏76','subject':'general'}}
        self.assertEqual(document_followup_text(previous,'刚才那张图片第二次是什么',{'subject':'general'},False),previous['document_context']['text'])
        self.assertEqual(document_followup_text(previous,'父亲上一张图片第二次是什么',{'subject':'father'},False),'')
        self.assertEqual(document_followup_text(previous,'另一个人的图片',{'subject':'unknown'},False),'')
        self.assertEqual(document_followup_text(previous,'我最近头痛',{'subject':'self'},False),'')
        self.assertEqual(document_followup_text(previous,'刚才那张图片',{'subject':'general'},True),'')

    def test_partial_evidence_hides_json_and_checks_quotes(self):
        from knowledge.answering import partial_answer
        sources=[{'citation':1,'content':'这是至少八个字的完整原文。'}]
        raw='{"sentences":[{"text":"一句回答","citations":[1],"quotes":[]}, {"text":"未完成'
        self.assertEqual(partial_answer(raw,sources),'一句回答[1]')
        self.assertEqual(partial_answer('{"sentences":[{"text":',sources),'')


if __name__=='__main__': unittest.main()


class SocialIntentTests(unittest.TestCase):
    def test_pure_social_intents(self):
        from web.social import social_reply
        for text in ('你好', '您好！', 'hello', '谢谢你', '你能做什么？'):
            self.assertIsNotNone(social_reply(text),text)

    def test_mixed_medical_questions_are_not_swallowed(self):
        from web.social import social_reply
        for text in ('你好，我头痛怎么办', '谢谢，阿司匹林怎么吃', '高血压怎么管理', '你好，请解读报告'):
            self.assertIsNone(social_reply(text),text)
