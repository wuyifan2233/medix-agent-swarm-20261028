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

    def test_disabled_does_not_queue(self):
        with patch.dict('os.environ',{'MEDIX_EXCHANGE_MEMORY':'0'}),patch('memory.exchange_mem0._pool') as pool:
            submit_exchange({'owner':'a'},{'answer':'answer'})
            pool.submit.assert_not_called()

    def test_queue_is_nonblocking_and_does_not_mutate_ui_result(self):
        payload={'owner':'a','chat_id':'c','request_id':'r','message':'完整问题','images':['never upload']}
        result={'answer':'回答一。回答二。回答三。','case_sources':[{'value':'secret report value'}]}
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
            factory.return_value.save_exchange.side_effect=Mem0Error('private provider message')
            _upload({'request_id':'r'})
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
