import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import httpx
from memory.test_web_mem0 import FakePlatform
from memory.exchange_mem0 import ExchangeMemory, submit_exchange, _upload
from memory.answer_summary import summarize_answer
from memory.web_mem0 import Mem0Error

class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.platform=FakePlatform()
        self.store=ExchangeMemory(api_key='synthetic',transport=httpx.MockTransport(self.platform.handle))

    def test_full_query_summary_only_and_two_requests(self):
        query=' 原始问题\n'+('长问题'*1000)+' '
        full='报告日期2018年5月22日。尿酸480偏高。不能据此确诊。建议复查。还有说明一。还有说明二。'
        summary=summarize_answer(full)
        ident=self.store.save_exchange('a','c','r',query,summary)
        row=self.platform.records[ident];data=json.loads(row['memory'])
        self.assertEqual(data,{'request_id':'r','query':query,'answer_summary':summary})
        self.assertNotIn(full,row['memory'])
        self.assertEqual(len(self.platform.calls),2)
        self.assertFalse(self.platform.calls[0][2]['infer'])
        self.assertNotIn('observations',row['metadata'])

    def test_foreign_readback_rejected(self):
        original=self.store._request
        def foreign(method,*args,**kwargs):
            row=original(method,*args,**kwargs)
            if method=='GET':row['user_id']='other'
            return row
        with patch.object(self.store,'_request',side_effect=foreign),self.assertRaises(Mem0Error):
            self.store.save_exchange('a','c','r','query','summary')

    def test_library_reads_full_query_and_summary_and_rejects_foreign_owner(self):
        ident = self.store.save_exchange('a','c','r','完整问题','回答摘要')
        other = self.store.save_exchange('b','c','other','其他账号','不可泄露')
        self.platform.foreign = self.platform.records[other]
        rows = self.store.list_exchanges('a')
        self.assertEqual([r['id'] for r in rows], [ident])
        self.assertEqual(rows[0]['query'], '完整问题')
        self.assertEqual(rows[0]['answer_summary'], '回答摘要')

    def test_library_does_not_treat_provider_failure_as_empty(self):
        self.platform.fail = True
        with self.assertRaises(Mem0Error):
            self.store.list_exchanges('a')

    def test_low_value_missing_or_ambiguous_decision_never_uploads(self):
        base={'subject':'self','should_store':True,'long_term_value':True,'memory_evidence':'做过手术'}
        with patch.dict('os.environ',{'MEDIX_EXCHANGE_MEMORY':'1'}),patch('memory.exchange_mem0._pool') as pool:
            for decision in ({}, base|{'long_term_value':False}, base|{'should_store':False},
                             base|{'subject':'unknown'}, base|{'memory_evidence':'编造病史'}):
                submit_exchange({'owner':'a','message':'我做过手术'}, {'answer':'建议','patient_resolution':decision})
            pool.submit.assert_not_called()

    def test_duplicate_query_same_person_skips_write(self):
        with patch('memory.exchange_mem0.ExchangeMemory') as factory,patch('memory.exchange_mem0._slots') as slots:
            factory.return_value.list_exchanges.return_value=[{'patient':'self','query':'我做过手术。'}]
            _upload({'owner':'a','subject':'self','query':'我做过手术','request_id':'r'})
            factory.return_value.save_exchange.assert_not_called()
            slots.release.assert_called_once()

    def test_edit_and_outdated_roundtrip_preserves_other_cards(self):
        ident = self.store.save_exchange('a','c','r','问题','摘要','self')
        other = self.store.save_exchange('a','c','r2','另一问题','另一摘要','self')
        updated = self.store.edit_exchange('a',ident,'更正问题','更正摘要',0)
        self.assertEqual(updated['revision'],1)
        self.assertEqual(json.loads(self.platform.records[ident]['memory'])['query'],'更正问题')
        from memory.case_memory import MemoryConflict
        with self.assertRaises(MemoryConflict): self.store.edit_exchange('a',ident,'旧页面','旧摘要',0)
        with self.assertRaises(MemoryConflict): self.store.delete_exchange('a',ident,0)
        self.assertTrue(self.store.delete_exchange('a',ident,1))
        self.assertNotIn(ident,self.platform.records)
        self.assertIn(other,self.platform.records)

    def test_foreign_account_cannot_edit_or_delete(self):
        ident = self.store.save_exchange('a','c','r','私有问题','私有摘要','self')
        self.assertIsNone(self.store.edit_exchange('b',ident,'篡改','篡改',0))
        self.assertFalse(self.store.delete_exchange('b',ident,0))
        self.assertIn(ident,self.platform.records)
        self.assertFalse(any(method in ('PUT','DELETE') for method,_,_ in self.platform.calls))

    def test_mutation_api_validates_account_and_body(self):
        from fastapi.testclient import TestClient
        from auth.dependencies import require_user
        from web.app import app
        ident = self.store.save_exchange('a','c','r','问题','摘要','self')
        previous = dict(app.dependency_overrides)
        try:
            app.dependency_overrides[require_user] = lambda: SimpleNamespace(id='b')
            with TestClient(app) as client, patch('memory.exchange_mem0.ExchangeMemory',return_value=self.store):
                path='/api/memory-exchanges/'+ident
                headers={'Origin':'http://127.0.0.1:8765','X-Medix-Request':'1'}
                self.assertEqual(client.post(path,json={'action':'outdated','expected_revision':0},headers=headers).status_code,404)
                app.dependency_overrides[require_user] = lambda: SimpleNamespace(id='a')
                self.assertEqual(client.post(path,json={'action':'edit','query':'','answer_summary':'摘要','expected_revision':0},headers=headers).status_code,400)
                response=client.post(path,json={'action':'edit','query':'更正','answer_summary':'摘要','expected_revision':0},headers=headers)
                self.assertEqual(response.status_code,200,response.text)
        finally:
            app.dependency_overrides.clear(); app.dependency_overrides.update(previous)

    def test_recall_inventory_is_account_and_person_isolated(self):
        ident=self.store.save_exchange('a','c','r','我青霉素过敏','历史AI建议','self')
        self.store.save_exchange('a','c','r2','爸爸有高血压','父亲建议','father')
        self.store.save_exchange('b','c','r3','另一个账号','另一建议','self')
        rows,status=self.store.recall('a','我的健康记忆里有什么内容','general')
        self.assertEqual(status,'available')
        self.assertEqual([r['id'] for r in rows],[ident])
        self.assertEqual(rows[0]['content'],'我青霉素过敏')
        self.assertEqual(rows[0]['answer_summary'],'历史AI建议')
        self.assertEqual(self.store.recall('a','他应该吃什么','unknown'),([], 'not_applicable'))

    def test_recall_search_refetches_edited_and_deleted_records(self):
        import copy
        ident=self.store.save_exchange('a','c','r','旧内容','旧摘要','self')
        self.platform.search_override=[copy.deepcopy(self.platform.records[ident])]
        self.store.edit_exchange('a',ident,'新内容','新摘要',0)
        rows,status=self.store.recall('a','我用什么药','self')
        self.assertEqual(rows[0]['content'],'新内容')
        self.store.delete_exchange('a',ident,1)
        self.assertEqual(self.store.recall('a','我用什么药','self'),([], 'empty'))

    def test_family_and_self_libraries_do_not_mix(self):
        for person in ('self','father','mother'):
            self.store.save_exchange('a','c',person,person,'摘要',person)
        self.assertEqual([r['patient'] for r in self.store.list_exchanges('a','self')],['self'])
        self.assertEqual({r['patient'] for r in self.store.list_exchanges('a','family')},{'father','mother'})
        self.assertEqual([r['patient'] for r in self.store.list_exchanges('a','mother')],['mother'])
        self.assertEqual(self.store.list_exchanges('b','family'),[])

    def test_parent_classification_is_preserved_when_queued(self):
        with patch.dict('os.environ',{'MEDIX_EXCHANGE_MEMORY':'1'}),patch('memory.exchange_mem0._pool') as pool,patch('memory.exchange_mem0._slots') as slots:
            slots.acquire.return_value=True
            for person in ('father','mother'):
                payload={'owner':'a','chat_id':'c','request_id':person,'message':'有高血压病史'}
                result={'answer':'建议','patient_resolution':{'subject':person,'should_store':True,'long_term_value':True,'memory_evidence':'高血压病史'}}
                submit_exchange(payload,result)
                self.assertEqual(pool.submit.call_args.args[1]['subject'],person)

    def test_disabled_does_not_queue(self):
        with patch.dict('os.environ',{'MEDIX_EXCHANGE_MEMORY':'0'}),patch('memory.exchange_mem0._pool') as pool:
            submit_exchange({'owner':'a'},{'answer':'answer'})
            pool.submit.assert_not_called()

    def test_queue_is_nonblocking_and_does_not_mutate_ui_result(self):
        payload={'owner':'a','chat_id':'c','request_id':'r','message':'完整问题','images':['never upload']}
        result={'patient_resolution':{'subject':'self','should_store':True,'long_term_value':True,'memory_evidence':'完整问题'},'answer':'回答一。回答二。回答三。','case_sources':[{'value':'secret report value'}]}
        original=dict(result)
        with patch.dict('os.environ',{'MEDIX_EXCHANGE_MEMORY':'1'}),patch('memory.exchange_mem0._pool') as pool,patch('memory.exchange_mem0._slots') as slots:
            slots.acquire.return_value=True
            submit_exchange(payload,result)
        self.assertEqual(result,original)
        data=pool.submit.call_args.args[1]
        self.assertEqual(data['query'],'完整问题');self.assertNotIn('images',data);self.assertNotIn('case_sources',data)
        slots.acquire.assert_called_once_with(blocking=False)

    def test_failures_retry_bounded_and_release_slot(self):
        with patch('memory.exchange_mem0.ExchangeMemory') as factory,patch('memory.exchange_mem0._slots') as slots,patch('memory.exchange_mem0.time.sleep'),patch('memory.exchange_mem0.logger') as log:
            factory.return_value.list_exchanges.return_value=[]
            factory.return_value.save_exchange.side_effect=Mem0Error('private provider message')
            _upload({'request_id':'r','owner':'a','subject':'self','query':'q'})
        self.assertEqual(factory.return_value.save_exchange.call_count,3)
        slots.release.assert_called_once()
        self.assertNotIn('private provider message',str(log.warning.call_args))

    def test_completed_event_precedes_background_upload(self):
        import web.app as web
        events=[];active=SimpleNamespace(pending_contexts={},emit=lambda *a,**kw:events.append(a[0]))
        job={'id':'turn','owner_user_id':'a','_persistent':True}
        def execute(job,*args):job.update(status='completed',result={'answer':'ok'})
        with patch.object(web,'ChatRuntime',return_value=active),patch.object(web,'_execute_job',execute), \
             patch.object(web,'usage_summary',return_value={}),patch('storage.care_wallet.view',return_value={}), \
             patch.object(web,'chat_store'),patch.object(web,'contexts',SimpleNamespace(cache={})), \
             patch.dict(web.controls,{'turn':{'cancel':threading.Event()}}), \
             patch('memory.exchange_mem0.submit_exchange',side_effect=lambda *args:events.append('upload')):
            web.run_job(job,{'owner':'a'},'s','a')
        self.assertEqual(events,['done','upload'])
