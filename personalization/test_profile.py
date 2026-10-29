import asyncio
import copy
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import inspect, update
from auth.schemas import Registration
from auth.service import AuthService
from auth.settings import AuthSettings
from personalization.models import HealthProfile
from personalization.schemas import ProfileData
from personalization.store import ProfileStore, REVIEW_SECONDS
from storage.database import make_database
from storage.migrate import upgrade_database
from web.app import app, analyze, contexts, jobs


def sample(name="A专属病史"):
    data = ProfileData(age=35, sex="female").model_dump()
    data["conditions"] = {"status":"reported", "items":[{"name":name,"note":"虚构测试资料", "status":"historical"}]}
    return data


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.temp.name) / "test.db").as_posix()
        upgrade_database(self.url)
        self.engine, self.sessions = make_database(self.url)
        self.old = app.state.auth_service
        settings = AuthSettings(self.url,False,frozenset({"http://testserver"}),True,namespace="profile-test")
        app.state.auth_service = AuthService(self.sessions,settings)
        self.auth = app.state.auth_service
        self.a = self.auth.register(Registration(username="alice",password="Test-Password2026!"))
        self.b = self.auth.register(Registration(username="bobby",password="Test-Password2026!"))
        self.client = self.client_for("alice")
        self.other = self.client_for("bobby")
        self.store = ProfileStore(self.sessions)
        contexts.clear(); jobs.clear()

    def tearDown(self):
        self.client.close(); self.other.close()
        contexts.clear(); jobs.clear()
        app.state.auth_service = self.old
        self.engine.dispose(); self.temp.cleanup()

    def client_for(self, name):
        client = TestClient(app,headers={"Origin":"http://testserver","X-Medix-Request":"1"})
        response = client.post("/api/auth/login",json={"username":name,"password":"Test-Password2026!"})
        self.assertEqual(response.status_code,200,response.text)
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    def saved(self,client=None,name="A专属病史",confirm=True):
        client = client or self.client
        revision = client.get('/api/profile').json()['revision']
        response = client.put('/api/profile',json={"expected_revision":revision,"data":sample(name)})
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()
        if confirm:
            response = client.post('/api/profile/confirm',json={"expected_revision":result['revision'],"acknowledged":True})
            self.assertEqual(response.status_code,200,response.text)
            result = response.json()
        return result

    def test_migration_and_new_user_empty(self):
        upgrade_database(self.url)
        self.assertIn('health_profiles',inspect(self.engine).get_table_names())
        self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
        self.assertEqual(self.other.get('/api/profile').json()['data']['conditions']['status'],'unknown')

    def test_a_b_persist_and_relogin(self):
        self.saved(name="仅A拥有")
        self.assertNotIn('仅A拥有',self.other.get('/api/profile').text)
        self.saved(self.other,"仅B拥有")
        self.client.close(); self.client = self.client_for('alice')
        self.assertIn('仅A拥有',self.client.get('/api/profile').text)
        self.assertNotIn('仅B拥有',self.client.get('/api/profile').text)

    def test_cannot_supply_owner_or_confirmation_fields(self):
        self.saved()
        for extra in ({'user_id':self.a.id},{'confirmed_at':time.time()}):
            response = self.other.put('/api/profile',json={'expected_revision':0,'data':sample('攻击内容'),**extra})
            self.assertEqual(response.status_code,422)
        self.assertNotIn('攻击内容',self.client.get('/api/profile').text)
        self.assertEqual(self.other.post('/api/profile/confirm',json={'expected_revision':1,'acknowledged':True}).status_code,409)

    def test_login_and_csrf_required(self):
        anonymous = TestClient(app,headers={'Origin':'http://testserver','X-Medix-Request':'1'})
        self.assertEqual(anonymous.get('/api/profile').status_code,401)
        self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.client.put('/api/profile',json={'expected_revision':0,'data':sample()}).status_code,403)
        anonymous.close()

    def test_large_profile_body_is_rejected(self):
        response = self.client.put('/api/profile', content='{"data":"' + 'x'*65536 + '"}', headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)

    def test_draft_edit_and_stale_revision_require_confirmation(self):
        draft = self.saved(confirm=False)
        self.assertFalse(draft['usable'])
        with self.assertRaises(HTTPException): self.store.snapshot(self.a.id,draft['revision'])
        self.assertEqual(self.client.post('/api/profile/confirm',json={'expected_revision':1,'acknowledged':False}).status_code,422)
        self.assertEqual(self.client.post('/api/profile/confirm',json={'expected_revision':1,'acknowledged':1}).status_code,422)
        confirmed = self.client.post('/api/profile/confirm',json={'expected_revision':1,'acknowledged':True}).json()
        self.assertTrue(confirmed['usable'])
        edited = self.saved(name='修改后',confirm=False)
        self.assertFalse(edited['usable'])
        self.assertEqual(self.client.put('/api/profile',json={'expected_revision':1,'data':sample()}).status_code,409)

    def test_review_interval_and_clear_invalidate_old_requests(self):
        self.saved()
        with self.sessions() as db:
            db.execute(update(HealthProfile).where(HealthProfile.user_id==self.a.id).values(confirmed_at=time.time()-REVIEW_SECONDS-1)); db.commit()
        self.assertEqual(self.client.get('/api/profile').json()['status'],'review_required')
        with self.assertRaises(HTTPException): self.store.snapshot(self.a.id,1)
        cleared = self.client.request('DELETE','/api/profile',json={'expected_revision':1}).json()
        self.assertEqual(cleared['revision'],2)
        self.assertIsNone(cleared['data']['age'])
        self.assertEqual(cleared['data']['conditions']['items'],[])
        with self.assertRaises(HTTPException): self.store.snapshot(self.a.id,1)

    def test_validation_distinguishes_unknown_and_none_and_bounds_fields(self):
        bad = sample(); bad['conditions']['status']='none_reported'
        for data in [bad,{**sample(),'age':True},{**sample(),'age':131},{**sample(),'extra':'ignored?'}]:
            self.assertEqual(self.client.put('/api/profile',json={'expected_revision':0,'data':data}).status_code,422)

    def test_chat_uses_server_identity_and_requires_opt_in(self):
        self.saved(); chat_id=str(uuid.uuid4())
        with patch('web.app.executor.submit') as submit:
            response=self.other.post('/api/chat',json={'message':'测试','images':[],'chat_id':chat_id,'use_profile':True,'profile_revision':1})
            self.assertEqual(response.status_code,409); submit.assert_not_called()
            response=self.client.post('/api/chat',json={'message':'测试','images':[],'chat_id':chat_id})
            self.assertEqual(response.status_code,202)
            self.assertIsNone(submit.call_args.args[2]['profile_snapshot'])
            response=self.client.post('/api/chat',json={'message':'测试','images':[],'chat_id':chat_id,'use_profile':True,'profile_revision':1})
            self.assertEqual(response.status_code,202)
            args=submit.call_args.args
            self.assertEqual(args[3],f'web-{self.a.id}-{chat_id}')
            self.assertIn('A专属病史',str(args[2]['profile_snapshot']))
            job=response.json()['job_id']
            self.assertEqual(self.other.get('/api/jobs/'+job).status_code,404)
            response=self.other.post('/api/chat',json={'message':'测试','chat_id':chat_id,'user_id':self.a.id})
            self.assertEqual(response.status_code,400)

    def capture_analysis(self,user_id,snapshot,session='shared',remember=False,images=None):
        captured={}
        class KB:
            def search(self,query,top_k): captured['query']=query; return []
        class Client:
            async def close(self): pass
        class VisionClient:
            def __init__(self): self.client = Client()
            async def chat(self, messages, max_tokens): return '虚构病历：2020年记录，血压120/80，归属待核对'
        class Coordinator:
            def __init__(self,**kwargs):
                captured['options']=kwargs; self.worker_pool=[]; self.llm_client=SimpleNamespace(client=Client()); self.long_term_memory=SimpleNamespace(enabled=kwargs['enable_long_term_memory'])
            async def process(self,question,context,session_id):
                captured.update(prompt=question,context=context,session=session_id)
                return {'answer':'虚构测试回答','agent_id':'test'}
        job={'owner_user_id':user_id,'started':time.monotonic(),'steps':[]}
        payload={'message':'请分析本次病历，日期尚未确认','images':images or [],'remember':remember,'profile_snapshot':snapshot}
        from config import LLM_CONFIG
        with patch.dict(LLM_CONFIG, {'api_key':'test-only-placeholder'}), patch('core.LLMClient', VisionClient), patch.dict('sys.modules',{'knowledge.milvus_kb':SimpleNamespace(MedicalKnowledgeBase=KB),'swarm':SimpleNamespace(SwarmCoordinator=Coordinator)}):
            asyncio.run(analyze(job,payload,session,f'medix:test:user:{user_id}'))
        captured['result']=job['result']; return captured

    def test_actual_retrieval_and_model_context_are_account_scoped(self):
        a=self.saved(name='A私有标签'); b=self.saved(self.other,'B私有标签')
        result_a=self.capture_analysis(self.a.id,a,f'web-{self.a.id}-same')
        result_b=self.capture_analysis(self.b.id,b,f'web-{self.b.id}-same')
        for key in ['query','prompt']:
            self.assertIn('A私有标签',result_a[key]); self.assertNotIn('A私有标签',result_b[key]); self.assertIn('B私有标签',result_b[key])
        self.assertIn('不是当前诊断',result_a['prompt'])
        self.assertIn('不擅自合并或覆盖',result_a['prompt'])
        self.assertTrue(result_a['result']['profile_used'])

    def test_opt_out_drops_prior_profile_history_and_does_not_write_profile(self):
        snapshot=self.saved(); before=copy.deepcopy(snapshot)
        first=self.capture_analysis(self.a.id,snapshot,remember=True)
        self.assertFalse(first['options']['enable_long_term_memory'])
        self.assertTrue(first['result']['memory_suppressed_for_profile'])
        contexts['shared']['history']=[{'role':'assistant','content':'A专属病史'}]
        second=self.capture_analysis(self.a.id,None)
        self.assertNotIn('A专属病史',second['query']+second['prompt']+str(second['context']))
        self.assertEqual(self.store.load(self.a.id),before)

    def test_queued_profile_cannot_be_used_after_edit_or_clear(self):
        old=self.saved(); self.saved(name='新草稿',confirm=False)
        with self.assertRaises(HTTPException): self.capture_analysis(self.a.id,old)

    def test_report_and_profile_remain_distinct_and_analysis_does_not_update_profile(self):
        snapshot = self.saved()
        captured = self.capture_analysis(self.a.id,snapshot,images=['data:image/jpeg;base64,test'])
        self.assertIn('2020年记录',captured['query'])
        self.assertIn('附图的客观读取结果',captured['prompt'])
        self.assertIn('用户确认的历史背景',captured['query'])
        self.assertIn('不是当前诊断',captured['prompt'])
        self.assertEqual(self.store.load(self.a.id),snapshot)
        self.assertEqual(captured['result']['image_count'],1)

    def test_foreign_snapshot_cannot_pass_job_owner_check(self):
        a=self.saved(); self.saved(self.other,'B私有标签')
        # Queue snapshots are internal, but owner revalidation must reject mixed data too.
        with self.assertRaises(ValueError): self.capture_analysis(self.b.id,a)


if __name__=='__main__': unittest.main()
