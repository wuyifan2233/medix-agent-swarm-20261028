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

    def test_string_reference_numbers_keep_sentence_and_quote_link(self):
        raw=json.dumps({'sentences':[{'text':'概括测试原文。','citations':['1','99'],
                    'quotes':[{'citation':'1','quote':'这是测试用的原文片段'}]}]})
        answer,links=parse_answer(raw,SOURCES)
        self.assertIn('[1]',answer);self.assertNotIn('[99]',answer)
        self.assertEqual(links[0]['status'],'quote_located')

    def test_legacy_swarm_result_retains_inline_source_contract(self):
        import web.app as web
        from config import LLM_CONFIG
        hit={'score':.9,'content':'这是测试用的原文片段，其中没有真实患者数据。','metadata':{'filename':'synthetic.txt'}}
        coordinator=Mock();coordinator.worker_pool=[];coordinator.llm_client.client.close=AsyncMock()
        coordinator.process=AsyncMock(return_value={'answer':'这是测试用的原文片段，其中没有真实患者数据。[1]','agents_involved':['test']})
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'legacy'}),patch.dict(LLM_CONFIG,{'api_key':'mock-key'}),patch('knowledge.get_knowledge_base') as factory,patch('swarm.SwarmCoordinator',return_value=coordinator):
            factory.return_value.search.return_value=[hit]
            job={'started':time.monotonic(),'steps':[]}
            asyncio.run(web.analyze(job,{'message':'高血压一般知识','images':[],'remember':False},'legacy-citation-test','u'))
        result=job['result'];self.assertEqual(result['sources'][0]['citation'],1)
        self.assertEqual(result['generation'],'model')
        self.assertTrue(any(x['citations']==[1] for x in result['evidence_links']))
        self.assertIn('[1]',coordinator.process.call_args.args[0])
        self.assertFalse(result['sources'][0]['source_checked'])
        web.contexts.pop('legacy-citation-test',None)

    def test_complete_markdown_answer_is_preserved_without_uncited_labels(self):
        original='## 简要说明\n\n- **重点**：概括测试原文。[1]\n- 请补充情况。\n\n| 项目 | 内容 |\n|---|---|\n| 提示 | 保留格式 |'
        raw=json.dumps({'answer':original,'sentences':[{'text':'概括测试原文。[1]','citations':[1],
                       'quotes':[{'citation':1,'quote':'这是测试用的原文片段'}]}]})
        answer,links=parse_answer(raw,SOURCES)
        self.assertEqual(answer,original);self.assertEqual(len(links),1)
        self.assertNotIn('本句未附引用',answer)

    def test_one_call_no_repair_and_client_closed_on_bad_json(self):
        client=Mock();client.chat=AsyncMock(return_value='invalid-json')
        client.client.with_options.return_value=client.client
        client.client.close=AsyncMock()
        with patch('knowledge.answering.LLMClient',return_value=client):
            with self.assertRaises(ValueError):asyncio.run(generate_answer('测试',SOURCES))
        client.chat.assert_awaited_once()
        client.client.with_options.assert_called_once_with(max_retries=0)
        client.client.close.assert_awaited_once()

    def test_uncovered_question_uses_one_general_call_without_fake_citations(self):
        client=Mock();client.chat=AsyncMock(return_value=json.dumps({'answer':'先了解情况，再讨论一般处理方式。[99]','sentences':[]}));client.client.with_options.return_value=client.client;client.client.close=AsyncMock()
        with patch('knowledge.answering.LLMClient',return_value=client):
            result=asyncio.run(generate_answer('未覆盖的健康问题',[],'知识库没有覆盖'))
        self.assertEqual(result['answer_basis'],'general');self.assertEqual(result['evidence_links'],[])
        self.assertNotIn('[99]',result['answer']);client.chat.assert_awaited_once()
        self.assertIn('不编造来源',client.chat.call_args.args[0][0]['content'])

    def test_web_uncovered_question_continues_to_general_answer(self):
        import web.app as web
        from config import LLM_CONFIG
        generated={'answer':'一般健康信息。','evidence_links':[],'llm_requests':1,'answer_basis':'general'}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence','MEDIX_EVIDENCE_GENERATOR':'direct'}),patch.dict(LLM_CONFIG,{'api_key':'mock-key'}),patch('knowledge.get_knowledge_base') as kb,patch('knowledge.answering.generate_answer',new=AsyncMock(return_value=generated)) as generate:
            kb.return_value.retrieve.return_value={'status':'no_results','hits':[],'message':'范围不覆盖','trace':{}}
            job={'started':time.monotonic(),'steps':[]}
            asyncio.run(web.analyze(job,{'message':'未覆盖的健康问题','images':[],'remember':False},'general-fallback-test','u'))
        self.assertEqual(job['result']['generation'],'model');self.assertEqual(job['result']['answer_basis'],'general')
        self.assertEqual(job['result']['sources'],[]);generate.assert_awaited_once()
        web.contexts.pop('general-fallback-test',None)

    def test_general_fallback_does_not_bypass_personal_medication_guard(self):
        import web.app as web
        from config import LLM_CONFIG
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence'}),patch.dict(LLM_CONFIG,{'api_key':'mock-key'}),patch('knowledge.get_knowledge_base') as kb,patch('knowledge.answering.generate_answer',new=AsyncMock(side_effect=AssertionError('No generation for personal dosing'))) as generate:
            kb.return_value.retrieve.return_value={'status':'needs_information','hits':[],'message':'请补充用药信息','trace':{}}
            job={'started':time.monotonic(),'steps':[]}
            asyncio.run(web.analyze(job,{'message':'布洛芬吃多少毫克','images':[],'remember':False},'guard-fallback-test','u'))
        self.assertEqual(job['result']['generation'],'not_called');generate.assert_not_awaited()
        web.contexts.pop('guard-fallback-test',None)

    def test_web_direct_route_does_not_construct_swarm(self):
        import web.app as web
        from config import LLM_CONFIG
        hit={'content':SOURCES[0]['content'],'metadata':{'title':'测试资料'}}
        generated={'answer':'测试回答[1]','evidence_links':[],'llm_requests':1}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence','MEDIX_EVIDENCE_GENERATOR':'direct'}), \
             patch.dict(LLM_CONFIG,{'api_key':'mock-key'}), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase') as kb, \
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
