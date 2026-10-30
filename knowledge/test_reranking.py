"""SiliconFlow API contract and fail-open ranking behavior without network calls."""
import json
import unittest
from unittest.mock import patch
import httpx
from knowledge.reranking import SiliconFlowReranker, create_reranker, rerank_candidates, RerankError


class RerankingTests(unittest.TestCase):
    def backend(self,handler):
        client=httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        with patch('knowledge.reranking.load_api_key',return_value='test-key'):
            return SiliconFlowReranker(client=client)

    def test_request_and_scores_reorder_original_evidence(self):
        hits=[{'id':'a','content':'原文甲'},{'id':'b','content':'原文乙'}]
        def handler(request):
            self.assertEqual(str(request.url),'https://api.siliconflow.cn/v1/rerank')
            self.assertEqual(request.headers['authorization'],'Bearer test-key')
            body=json.loads(request.content)
            self.assertEqual(body['model'],'Qwen/Qwen3-Reranker-8B')
            self.assertEqual(body['documents'],['原文甲','原文乙'])
            self.assertEqual(body['top_n'],2);self.assertFalse(body['return_documents'])
            self.assertNotIn('overlap_tokens',body);self.assertNotIn('max_chunks_per_doc',body)
            return httpx.Response(200,json={'results':[{'index':0,'relevance_score':.1,'document':{'text':'不可替换原文'}},{'index':1,'relevance_score':.9}]})
        ranked,trace=rerank_candidates(self.backend(handler),'问题',hits,1)
        self.assertEqual(ranked[0]['id'],'b');self.assertEqual(ranked[0]['content'],'原文乙')
        self.assertEqual(trace['status'],'ok')

    def test_network_or_auth_failure_is_visible_and_keeps_rrf_order(self):
        backend=self.backend(lambda req:httpx.Response(401,json={'message':'test-key private query'}))
        hits=[{'content':'a'},{'content':'b'}]
        ranked,trace=rerank_candidates(backend,'private query',hits,1)
        self.assertEqual(ranked,hits[:1]);self.assertEqual(trace['status'],'degraded')
        self.assertNotIn('test-key',json.dumps(trace));self.assertNotIn('private query',json.dumps(trace))

    def test_invalid_indices_and_nonfinite_scores_are_rejected(self):
        for results in ([{'index':9,'relevance_score':.9}],[{'index':0,'relevance_score':'nan'}]):
            backend=self.backend(lambda req:httpx.Response(200,json={'results':results}))
            with self.assertRaises(RerankError):backend.rerank('q',[{'content':'a'}])

    def test_disabled_and_empty_do_not_call_service(self):
        hits=[{'content':'a'}]
        self.assertEqual(rerank_candidates(None,'q',hits,1),(hits,{'status':'disabled'}))
        with patch.dict('os.environ',{'MEDIX_RERANK_PROVIDER':'none'}):self.assertIsNone(create_reranker())

    def test_placeholder_rejected_only_when_explicitly_enabled(self):
        with patch.dict('os.environ',{'MEDIX_RERANK_PROVIDER':'siliconflow'}),patch('knowledge.reranking.load_api_key',return_value='xxx'):
            with self.assertRaisesRegex(ValueError,'xxx'):create_reranker()

if __name__=='__main__':unittest.main()
