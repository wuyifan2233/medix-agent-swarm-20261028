import unittest
from unittest.mock import patch
from sqlalchemy import select
from personalization.test_profile import ProfileTests
from personalization.models import RegistrationProfile
from personalization.registration_profile import BaselineStore,select_fields,profile_context,retrieval_query

class RegistrationProfileTests(unittest.TestCase):
    setUp=ProfileTests.setUp
    tearDown=ProfileTests.tearDown
    client_for=ProfileTests.client_for
    def register(self,username='newperson',**changes):
        return self.client.post('/api/auth/register',json={'username':username,'password':'Test-Password2026!','basic_profile':{'name':'测试甲','birth_month':'1995-06','sex':'female',**changes}})
    def test_registration_is_atomic_private_and_immutable(self):
        result=self.register();self.assertEqual(result.status_code,201,result.text)
        client=self.client_for('newperson')
        try:
            body=client.get('/api/profile').json();self.assertTrue(body['usable']);self.assertTrue(body['read_only']);self.assertEqual(body['data']['birth_month'],'1995-06')
            self.assertIsNone(self.other.get('/api/profile').json()['data']['birth_month'])
            for method,path in [('PUT','/api/profile'),('POST','/api/profile/confirm'),('POST','/api/profile/restore'),('POST','/api/profile/imports'),('POST','/api/profile/conversation-candidates')]:
                self.assertIn(client.request(method,path,json={}).status_code,[404,405])
            self.assertEqual(client.get('/api/profile').json(),body)
            self.assertEqual(self.register().status_code,409)
            with self.sessions() as db:self.assertEqual(len(db.scalars(select(RegistrationProfile)).all()),1)
        finally:client.close()
    def test_registration_fields_and_bounds(self):
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'missing','password':'Test-Password2026!'}).status_code,422)
        for change in [{'name':'甲'*51},{'name':123},{'name':'甲\n乙'},{'birth_month':'2999-01'},{'birth_month':'1995-13'},{'birth_month':'1995-06-01'},{'height_cm':165},{'weight_kg':55},{'age':30},{'conditions':[]}]:
            self.assertEqual(self.register(**change).status_code,422)
        self.assertEqual(self.register(birth_month=None,sex='undisclosed').status_code,201)
    def test_question_generation_receives_no_followup_policy(self):
        captured=ProfileTests.capture_analysis(self,self.a.id,None)
        self.assertIn('不主动追问',captured['prompt'])
        self.assertIn('不要求用户补充',captured['prompt'])
        self.assertIn('不得主动新增、更新、补全用户档案',captured['prompt'])
        self.assertEqual(self.client.get('/api/profile').json()['revision'],0)

    def test_legacy_records_not_reused(self):
        self.assertFalse(self.client.get('/api/profile').json()['usable'])
        self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
    def test_context_scope_and_no_implicit_update(self):
        result=self.register();user_id=result.json()['id']
        store=BaselineStore(self.sessions);snapshot=store.snapshot(user_id,1)
        selected=select_fields(snapshot,['birth_month'])
        self.assertEqual(selected['data'],{'birth_month':'1995-06'})
        self.assertNotIn('height_cm',profile_context(selected))
        self.assertIn('默认用于相关回答',profile_context(selected));self.assertIn('不得询问是否授权使用',profile_context(selected));self.assertIn('注册时',profile_context(selected));self.assertIn('不写回档案',profile_context(selected))
        self.assertNotIn('30',retrieval_query('问题','',None))
        self.assertEqual(store.load(user_id),snapshot)
    def test_chat_uses_baseline_and_rejects_clinical_fields(self):
        import uuid
        self.register();client=self.client_for('newperson')
        try:
            with patch('web.app.executor.submit') as submit:
                request={'message':'测试','chat_id':str(uuid.uuid4()),'use_profile':True,'profile_revision':1,'profile_fields':['birth_month']}
                response=client.post('/api/chat',json=request);self.assertEqual(response.status_code,202,response.text)
                self.assertEqual(submit.call_args.args[2]['profile_snapshot']['data'],{'birth_month':'1995-06'})
                automatic={'message':'测试默认引用','chat_id':str(uuid.uuid4())}
                self.assertEqual(client.post('/api/chat',json=automatic).status_code,202)
                self.assertEqual(submit.call_args.args[2]['profile_snapshot']['data']['birth_month'],'1995-06')
                self.assertEqual(self.other.post('/api/chat',json=automatic).status_code,202)
                self.assertIsNone(submit.call_args.args[2]['profile_snapshot'])
                request['profile_fields']=['conditions']
                self.assertEqual(client.post('/api/chat',json=request).status_code,400)
        finally:client.close()

    def test_old_measurements_are_not_exposed_or_reinferred(self):
        self.register()
        with self.sessions() as db:
            row=db.scalars(select(RegistrationProfile)).one()
            row.data={'age':30,'sex':'female','height_cm':165,'weight_kg':55};db.commit()
            owner=row.user_id
        profile=BaselineStore(self.sessions).load(owner)
        self.assertEqual(profile['data'],{'name':None,'birth_month':None,'sex':'female'})
        self.assertNotIn('height_cm',profile_context(profile)+retrieval_query('问题','',profile))
        self.assertNotIn('weight_kg',profile_context(profile)+retrieval_query('问题','',profile))

    def test_account_profiles_persist_across_login_and_database_reopen(self):
        from storage.database import make_database
        first=self.register(username='personone',name='测试甲',birth_month='1990-01',sex='male').json()
        second=self.register(username='persontwo',name='测试乙',birth_month='2000-02',sex='female').json()
        expected={}
        for username in ['personone','persontwo']:
            client=self.client_for(username)
            try:expected[username]=client.get('/api/profile').json()
            finally:client.close()
        engine,sessions=make_database(self.url)
        try:
            self.assertEqual(BaselineStore(sessions).load(first['id']),expected['personone'])
            self.assertEqual(BaselineStore(sessions).load(second['id']),expected['persontwo'])
        finally:engine.dispose()
        for username,othername in [('personone','测试乙'),('persontwo','测试甲')]:
            client=self.client_for(username)
            try:
                result=client.get('/api/profile',params={'user_id':second['id'] if username=='personone' else first['id']})
                self.assertEqual(result.json(),expected[username])
                self.assertNotIn(othername,result.text)
            finally:client.close()
        self.assertNotIn('测试甲',retrieval_query('问题','',expected['personone']))
