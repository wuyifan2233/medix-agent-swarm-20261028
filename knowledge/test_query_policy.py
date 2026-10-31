"""Intent, follow-up, audience and evidence support regressions, no network."""
import asyncio
import os
import time
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from knowledge.query_policy import contextualize_query, insufficient_medication, applicability, requested_audience, knowledge_gap, evidence_links
from knowledge.evidence import validate_citations


class QueryPolicyTests(unittest.TestCase):
    def test_food_questions_are_not_personal_drug_dosing(self):
        for q in ['高血压患者水果能不能吃','糖尿病可以吃水果吗','饮食用多少盐','布洛芬有哪些剂型']:
            self.assertFalse(insufficient_medication(q),q)
        for q in ['孩子布洛芬吃多少毫升','虚构：我吃了一片布洛芬，现在该怎么办','怀孕了氯雷他定能吃吗','降压药能停药吗']:
            self.assertTrue(insufficient_medication(q),q)
        self.assertTrue(insufficient_medication('头孢克洛吃多少毫克'))
        self.assertTrue(insufficient_medication('华法林和阿司匹林能合用吗'))

    def test_followup_uses_user_topic_and_new_topic_resets(self):
        history=[{'role':'user','content':'高血压日常管理'},{'role':'assistant','content':'布洛芬'}]
        query,changed=contextualize_query('那饮食应该注意什么',history)
        self.assertTrue(changed);self.assertIn('高血压',query);self.assertNotIn('布洛芬',query)
        self.assertEqual(contextualize_query('糖尿病怎样运动',history),('糖尿病怎样运动',False))
        self.assertEqual(contextualize_query('那应该怎么做',[]),('那应该怎么做',False))

    def test_population_matching_is_not_inferred_from_disease_alone(self):
        child={'audiences':['children']}
        self.assertEqual(applicability({'audiences':['unspecified']},'unspecified'),'needs_confirmation')
        self.assertEqual(applicability({'audiences':['unspecified']},'adults'),'needs_confirmation')
        self.assertEqual(applicability(child,requested_audience('成人鼻炎')),'mismatch')
        self.assertEqual(applicability(child,requested_audience('鼻炎')),'needs_confirmation')
        self.assertEqual(applicability(child,requested_audience('儿童鼻炎')),'matched')

    def test_monograph_gap_is_explicit(self):
        docs=[{'metadata':{'evidence_kind':'popular_science'}}]
        self.assertEqual(knowledge_gap('氯雷他定有哪些禁忌',docs)['kind'],'missing_product_label')

    def test_verbatim_support_and_valid_but_unverified_claims_differ(self):
        sources=[{'citation':1,'content':'这是足够长的原文测试句子。'}]
        links=evidence_links('这是足够长的原文测试句子。[1]\n这项推断没有原文逐字支持[1]。\n这个句子没有提供任何引用。',sources)
        self.assertEqual([x['status'] for x in links],['verbatim_match','needs_review','uncited'])
        answer,invalid=validate_citations('合并引用[1,2,9]',2)
        self.assertEqual(invalid,[9]);self.assertIn('[1][2]',answer)

    def test_retrieval_only_chat_keeps_context_for_followup(self):
        import web.app as web
        from config import LLM_CONFIG
        web.contexts.pop('followup-policy-test',None)
        def retrieve(q):return {'status':'no_results','hits':[],'trace':{},'message':'资料不足'}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence'}),patch.dict(LLM_CONFIG,{'api_key':'not-configured'}),patch('knowledge.milvus_kb.MedicalKnowledgeBase') as factory:
            factory.return_value.retrieve.side_effect=retrieve
            for question in ['高血压如何管理','那饮食呢']:
                job={'started':time.monotonic(),'steps':[]}
                asyncio.run(web.analyze(job,{'message':question,'images':[],'remember':False},'followup-policy-test','u'))
            self.assertIn('高血压',factory.return_value.retrieve.call_args.args[0])
            self.assertTrue(job['result']['retrieval']['context_rewritten'])
        web.contexts.pop('followup-policy-test',None)

    def test_failed_fetch_keeps_published_manifest(self):
        import knowledge.scripts.fetch_sources as fetcher
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'local';local.mkdir()
            original='{"documents":[]}'
            (local/'manifest.json').write_text(original)
            registry=root/'sources.json';registry.write_text(json.dumps({'documents':[{'id':'x'}]}))
            with patch.object(fetcher,'LOCAL',local),patch.object(fetcher,'REGISTRY',registry),patch.object(fetcher,'fetch',side_effect=RuntimeError('synthetic fetch failure')):
                with self.assertRaises(RuntimeError):fetcher.main([])
            self.assertEqual((local/'manifest.json').read_text(),original)

    def test_source_labels_are_present_without_refetching_snapshots(self):
        # Real local corpus is optional in CI; labeling registry itself is tracked.
        from knowledge.corpus import ROOT
        labels=json.loads((ROOT/'applicability.json').read_text(encoding='utf8'))['documents']
        self.assertEqual(labels['rhinitis']['audiences'],['children'])
        self.assertEqual(labels['literacy']['evidence_kind'],'popular_science')

if __name__=='__main__':unittest.main()
