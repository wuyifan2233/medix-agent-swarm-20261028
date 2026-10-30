import asyncio
import copy
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from sqlalchemy import update
from personalization.test_profile import ProfileTests, sample
from personalization.models import ProfileImport
from personalization.report_imports import ReportInput, extract_report
from personalization.context import select_fields, retrieval_query, profile_context, scope


class EvolutionTests(unittest.TestCase):
    setUp=ProfileTests.setUp
    tearDown=ProfileTests.tearDown
    client_for=ProfileTests.client_for
    saved=ProfileTests.saved
    capture_analysis=ProfileTests.capture_analysis

    def candidate(self,field='conditions',name='新病史',uncertain=False):
        return dict(id=str(uuid.uuid4()),field=field,
                    value={'name':name,'note':'旧病历','status':'unknown' if uncertain else 'historical','source':None},
                    evidence=name,uncertain=uncertain,
                    source={'kind':'report','label':'虚构病历','report_date':'2020-01-01','excerpt':name})

    def batch(self,candidates):
        revision=self.client.get('/api/profile').json()['revision']
        with patch('personalization.report_imports.extract_report',AsyncMock(return_value=candidates)):
            response=self.client.post('/api/profile/imports',json={'text':'虚构病历文字','label':'虚构病历','report_date':'2020-01-01','subject':'self','consent_to_model':True,'expected_revision':revision})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def apply(self,batch,selections,client=None):
        return (client or self.client).post('/api/profile/imports/'+batch['id']+'/apply',json={'expected_revision':batch['base_revision'],'selections':selections})

    def test_extraction_is_not_profile_write_and_selection_creates_unconfirmed_draft(self):
        before=self.saved(); a=self.candidate(name='新病史'); b=self.candidate('allergies','虚构过敏')
        batch=self.batch([a,b]);self.assertEqual(self.client.get('/api/profile').json(),before)
        self.assertIn('existing',batch['candidates'][0])
        response=self.apply(batch,[{'candidate_id':a['id'],'action':'append'}])
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertFalse(result['usable']);self.assertIsNone(result['confirmed_at'])
        self.assertEqual(len(result['data']['conditions']['items']),2)
        self.assertEqual(result['data']['allergies']['status'],'unknown')
        self.assertEqual(result['data']['conditions']['items'][1]['source']['report_date'],'2020-01-01')
        self.assertEqual(self.apply(batch,[{'candidate_id':b['id'],'action':'append'}]).status_code,409)

    def test_unrelated_record_cannot_be_replaced_but_can_be_appended(self):
        self.saved(name='头痛')
        candidate=self.candidate(name='感冒');batch=self.batch([candidate])
        rejected=self.apply(batch,[{'candidate_id':candidate['id'],'action':'replace','target_index':0}])
        self.assertEqual(rejected.status_code,422,rejected.text)
        self.assertEqual(self.client.get('/api/profile').json()['data']['conditions']['items'][0]['name'],'头痛')
        self.assertFalse(self.client.get('/api/profile/imports/'+batch['id']).json()['consumed'])
        saved=self.apply(batch,[{'candidate_id':candidate['id'],'action':'append'}])
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual([item['name'] for item in saved.json()['data']['conditions']['items']],['头痛','感冒'])

    def test_uncertain_candidate_requires_separate_acknowledgement(self):
        a=self.candidate(uncertain=True);batch=self.batch([a])
        self.assertEqual(self.apply(batch,[{'candidate_id':a['id'],'action':'append'}]).status_code,422)
        self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
        response=self.apply(batch,[{'candidate_id':a['id'],'action':'append','acknowledge_uncertainty':True}])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['conditions']['items'][0]['status'],'unknown')

    def test_conflict_requires_explicit_replace_and_stale_revision_is_rejected(self):
        self.saved(name='原病史');a=self.candidate(name='原病史');batch=self.batch([a])
        self.assertEqual(self.apply(batch,[{'candidate_id':a['id'],'action':'append'}]).status_code,422)
        response=self.apply(batch,[{'candidate_id':a['id'],'action':'replace','target_index':0}])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['data']['conditions']['items']),1)
        next_batch=self.batch([self.candidate()]);self.saved(name='其他窗口修改')
        self.assertEqual(self.apply(next_batch,[{'candidate_id':next_batch['candidates'][0]['id'],'action':'append'}]).status_code,409)

    def test_foreign_account_cannot_read_apply_or_delete_import(self):
        batch=self.batch([self.candidate()]);path='/api/profile/imports/'+batch['id']
        self.assertEqual(self.other.get(path).status_code,404)
        self.assertEqual(self.apply(batch,[{'candidate_id':batch['candidates'][0]['id'],'action':'append'}],self.other).status_code,404)
        self.assertEqual(self.other.request('DELETE',path,json={}).status_code,404)
        self.assertEqual(self.other.get('/api/profile/history').json()['items'],[])

    def test_expired_import_and_discard(self):
        batch=self.batch([self.candidate()])
        with self.sessions() as db:
            db.execute(update(ProfileImport).where(ProfileImport.id==batch['id']).values(expires_at=time.time()-1));db.commit()
        self.assertEqual(self.client.get('/api/profile/imports/'+batch['id']).status_code,410)
        self.assertEqual(self.client.request('DELETE','/api/profile/imports/'+batch['id'],json={}).status_code,204)

    def test_invalid_selection_rolls_back_without_consuming_candidates(self):
        a=self.candidate();batch=self.batch([a]);selection={'candidate_id':a['id'],'action':'append'}
        for choices in [[selection,selection],[{'candidate_id':'unknown','action':'append'}],
                        [{'candidate_id':a['id'],'action':'replace','target_index':0}]]:
            self.assertEqual(self.apply(batch,choices).status_code,422)
            self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
            self.assertFalse(self.client.get('/api/profile/imports/'+batch['id']).json()['consumed'])

    def test_upgrade_preserves_existing_profile_as_baseline(self):
        from pathlib import Path
        from alembic import command
        from alembic.config import Config
        from auth.models import User
        from personalization.models import HealthProfile
        from personalization.store import ProfileStore
        from storage.database import make_database
        from storage.migrate import upgrade_database
        url='sqlite:///'+(Path(self.temp.name)/'legacy.db').as_posix()
        config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'));config.attributes['database_url']=url
        command.upgrade(config,'20261029_02')
        engine,sessions=make_database(url)
        try:
            with sessions() as db:
                db.add(User(id='legacy',username='legacy',display_name='legacy',password_hash='unused',role='user',is_active=True,created_at=1,updated_at=1));db.flush()
                db.add(HealthProfile(user_id='legacy',profile_data=sample('升级前资料'),revision=7,updated_at=100,confirmed_at=200));db.commit()
            upgrade_database(url)
            history=ProfileStore(sessions).history('legacy')
            self.assertEqual(len(history),1);self.assertEqual(history[0]['revision'],7)
            self.assertEqual(history[0]['action'],'baseline')
            self.assertEqual(history[0]['data']['conditions']['items'][0]['name'],'升级前资料')
        finally:engine.dispose()

    def test_history_restore_export_and_clear(self):
        self.saved(name='旧病史');self.saved(name='新病史')
        history=self.client.get('/api/profile/history').json()['items'];self.assertEqual([x['revision'] for x in history],[2,1])
        response=self.client.post('/api/profile/restore',json={'expected_revision':2,'target_revision':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['revision'],3);self.assertFalse(response.json()['usable'])
        self.assertEqual(response.json()['data']['conditions']['items'][0]['name'],'旧病史')
        self.assertEqual(self.other.post('/api/profile/restore',json={'expected_revision':1,'target_revision':1}).status_code,404)
        self.assertEqual(self.client.get('/api/profile/export').json()['schema_version'],2)
        batch=self.batch([self.candidate()])
        self.client.request('DELETE','/api/profile',json={'expected_revision':3})
        remaining=self.client.get('/api/profile/history').json()['items']
        self.assertEqual(len(remaining),1);self.assertEqual(remaining[0]['action'],'clear')
        self.assertEqual(self.client.get('/api/profile/imports/'+batch['id']).status_code,404)

    def test_selected_fields_are_removed_from_retrieval_model_and_prior_history(self):
        snapshot=self.saved(name='禁止传入模型的病史')
        selected=select_fields(snapshot,['allergies'])
        self.assertNotEqual(scope(selected),scope(snapshot))
        captured=self.capture_analysis(self.a.id,selected)
        self.assertNotIn('禁止传入模型',captured['prompt']+captured['query'])
        self.assertIsNone(selected['data']['age'])
        self.assertEqual(captured['result']['profile_fields'],['allergies'])
        self.assertEqual(self.store.load(self.a.id),snapshot)

    def test_chat_rejects_invalid_field_selection(self):
        self.saved()
        for fields in [[],['age','age'],['user_id']]:
            response=self.client.post('/api/chat',json={'message':'测试','chat_id':str(uuid.uuid4()),'use_profile':True,'profile_revision':1,'profile_fields':fields})
            self.assertEqual(response.status_code,400,response.text)

    def test_report_input_requires_consent_subject_and_date(self):
        for changes in [{'consent_to_model':False},{'subject':'other'},{'report_date':'2999-01-01'}]:
            response=self.client.post('/api/profile/imports',json={'text':'虚构病历','label':'测试','report_date':'2020-01-01','subject':'self','consent_to_model':True,'expected_revision':0,**changes})
            self.assertEqual(response.status_code,422)

    def test_extractor_rejects_fabricated_evidence_and_does_not_infer_current_medication(self):
        data=ReportInput(text='药品甲每日一次',label='虚构病历',report_date='2020-01-01',subject='self',consent_to_model=True,expected_revision=0)
        async def run(evidence):
            payload={'candidates':[{'field':'medications','value':{'name':'药品甲','status':'current'},'evidence':evidence,'uncertain':False}]}
            response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))),close=AsyncMock())
            from config import LLM_CONFIG
            with patch.dict(LLM_CONFIG,{'api_key':'test-only-placeholder'}),patch('openai.AsyncOpenAI',return_value=client):
                return await extract_report(data)
        result=asyncio.run(run('药品甲每日一次'));self.assertEqual(result[0]['value']['status'],'historical')
        self.assertEqual(result[0]['source']['report_date'],'2020-01-01')
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as raised:asyncio.run(run('凭空编造的原文'))
        self.assertEqual(raised.exception.status_code,502)


if __name__=='__main__':unittest.main()


class PersonalizedContextTests(unittest.TestCase):
    def test_status_aware_retrieval_and_actionable_answer_contract(self):
        from personalization.test_profile import sample
        snapshot={'revision':1,'confirmed_at':time.time(),'data':sample('测试病史')}
        snapshot['data']['medications']={'status':'reported','items':[{'name':'测试药','status':'stopped','note':''}]}
        query=retrieval_query('本次问题','',snapshot)
        self.assertIn('本次问题',query)
        self.assertIn('用药:测试药（已停用）',query)
        prompt=profile_context(snapshot)
        for expected in ['结合你的档案','具体建议一一对应','不强行制造差异','不能把旧症状当作现在仍存在','不能据性别推断妊娠']:
            self.assertIn(expected,prompt)
        scoped=select_fields(snapshot,['allergies'])
        self.assertNotIn('测试病史',profile_context(scoped)+retrieval_query('问题','',scoped))
        self.assertNotIn('测试药',profile_context(scoped)+retrieval_query('问题','',scoped))
        self.assertEqual(profile_context(None),'')
