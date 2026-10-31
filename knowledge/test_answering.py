"""Grounded quote offsets, rejection and one-request generation regressions."""
import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from knowledge.answering import parse_answer, generate_answer

SOURCES=[{'citation':1,'content':'这是测试用的原文片段，其中没有真实患者数据。',
          'title':'虚构资料','audiences':['adults'],'evidence_kind':'popular_science','applicability':'matched'}]


class AnswerTests(unittest.TestCase):
    def test_quote_offsets_are_original_substrings(self):
        raw=json.dumps({'sentences':[{'text':'概括测试原文。','citations':[1],
                                     'quotes':[{'citation':1,'quote':'这是测试用的原文片段'}]}]})
        answer,links=parse_answer(raw,SOURCES)
        self.assertIn('[1]',answer)
        quote=links[0]['quotes'][0]
        self.assertEqual(SOURCES[0]['content'][quote['start_char']:quote['end_char']],quote['quote'])
        self.assertEqual(links[0]['status'],'quote_located')

    def test_nonexistent_quote_or_reference_is_not_locatable(self):
        raw=json.dumps({'sentences':[{'text':'未经核对[99]。','citations':[1,99],
            'quotes':[{'citation':1,'quote':'这段引用文字在原文中并不存在'}]}]})
        answer,links=parse_answer(raw,SOURCES)
        self.assertNotIn('[99]',answer)
        self.assertEqual(links[0]['quotes'],[])
        self.assertEqual(links[0]['status'],'needs_review')

    def test_one_call_no_repair_and_client_closed_on_bad_json(self):
        client=Mock();client.chat=AsyncMock(return_value='invalid-json')
        client.client.with_options.return_value=client.client
        client.client.close=AsyncMock()
        with patch('knowledge.answering.LLMClient',return_value=client):
            with self.assertRaises(ValueError):asyncio.run(generate_answer('测试',SOURCES))
        client.chat.assert_awaited_once()
        client.client.with_options.assert_called_once_with(max_retries=0)
        client.client.close.assert_awaited_once()

    def test_web_direct_route_does_not_construct_swarm(self):
        import web.app as web
        from config import LLM_CONFIG
        hit={'content':SOURCES[0]['content'],'metadata':{'title':'测试资料'}}
        generated={'answer':'测试回答[1]','evidence_links':[],'llm_requests':1}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence','MEDIX_EVIDENCE_GENERATOR':'direct'}), \
             patch.dict(LLM_CONFIG,{'api_key':'mock-key'}), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase') as kb, \
             patch('web.request_routing.classify_request',new=AsyncMock(return_value={'kind':'medical','subject':'general'})), \
             patch('knowledge.evidence.evidence_sources',return_value=SOURCES), \
             patch('knowledge.answering.generate_answer',new=AsyncMock(return_value=generated)) as generate, \
             patch('swarm.SwarmCoordinator',side_effect=AssertionError('No swarm in direct mode')):
            kb.return_value.retrieve.return_value={'status':'ok','hits':[hit],'message':'','trace':{}}
            job={'started':time.monotonic(),'steps':[]}
            asyncio.run(web.analyze(job,{'message':'高血压饮食','images':[],'remember':False},'direct-test','u'))
            self.assertEqual(job['result']['llm_requests'],1)
            generate.assert_awaited_once()
        web.contexts.pop('direct-test',None)


if __name__=='__main__':unittest.main()
