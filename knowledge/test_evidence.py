"""Meaningful source/chunk, citation and web integration regressions, no API calls."""
import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from knowledge.corpus import chunk_document
from knowledge.evidence import insufficient_medication, normalize_query, validate_citations


class CharacterTokenizer:
    def encode(self,text,add_special_tokens=True):return list(text)+([0,1] if add_special_tokens else [])


class EvidenceTests(unittest.TestCase):
    def test_chunk_budget_stable_ids_offsets_and_long_paragraph_coverage(self):
        body='第一句话。第二句话。'*100
        doc={'id':'synthetic','content':'# 标题\n\n## 章节\n\n'+body,'metadata':{'title':'标题','publisher':'测试来源'}}
        chunks=chunk_document(doc,CharacterTokenizer())
        self.assertGreater(len(chunks),1)
        self.assertEqual(chunks,chunk_document(doc,CharacterTokenizer()))
        covered=set()
        for row in chunks:
            self.assertLessEqual(len(CharacterTokenizer().encode(row['content'])),384)
            m=row['metadata'];self.assertEqual(row['content'].split('\n\n',1)[1],doc['content'][m['start_char']:m['end_char']])
            covered.update(range(m['start_char'],m['end_char']))
        start=doc['content'].index(body)
        self.assertTrue(set(range(start,start+len(body))).issubset(covered))

    def test_bad_chunk_configuration_is_rejected(self):
        with self.assertRaises(ValueError):chunk_document({'id':'x'},CharacterTokenizer(),overlap=384)

    def test_alias_and_medication_boundary(self):
        self.assertEqual(normalize_query('扑热息痛'),'对乙酰氨基酚')
        self.assertTrue(insufficient_medication('布洛芬吃多少毫升'))
        self.assertFalse(insufficient_medication('布洛芬有哪些剂型'))

    def test_invalid_citations_are_removed_without_inventing_evidence(self):
        answer,bad=validate_citations('结论[1]，另一结论[8]和[0]',2)
        self.assertEqual(bad,[0,8]);self.assertIn('[1]',answer);self.assertNotIn('[8]',answer)

    def test_legacy_factory_stays_legacy_unless_opted_in(self):
        from knowledge.milvus_kb import MedicalKnowledgeBase
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'legacy'}):
            obj=MedicalKnowledgeBase.__new__(MedicalKnowledgeBase)
            self.assertIsInstance(obj,MedicalKnowledgeBase)

    def test_retrieval_without_model_does_not_claim_generated_answer(self):
        import web.app as web
        from config import LLM_CONFIG
        retrieval={'status':'no_results','hits':[],'trace':{'selected':0},'message':'资料不足'}
        job={'started':time.monotonic(),'steps':[]}
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence'}), patch.dict(LLM_CONFIG,{'api_key':'not-configured'}), patch('knowledge.milvus_kb.MedicalKnowledgeBase') as factory:
            factory.return_value.retrieve.return_value=retrieval
            asyncio.run(web.analyze(job,{'message':'库外问题','images':[],'remember':False},'session','user'))
        self.assertEqual(job['result']['generation'],'not_called')
        self.assertEqual(job['result']['sources'],[])

    def test_retrieval_failure_is_not_treated_as_no_results(self):
        import web.app as web
        from config import LLM_CONFIG
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence'}), patch.dict(LLM_CONFIG,{'api_key':'not-configured'}), patch('knowledge.milvus_kb.MedicalKnowledgeBase') as factory:
            factory.return_value.retrieve.return_value={'status':'error','message':'failed'}
            with self.assertRaises(RuntimeError):
                asyncio.run(web.analyze({'started':time.monotonic(),'steps':[]},{'message':'高血压','images':[],'remember':False},'s','u'))

    def test_http_invalid_query_and_source_catalog(self):
        from fastapi.testclient import TestClient
        import web.app as web
        with patch.dict(web.health,{'mode':'evidence','knowledge':'ready'}), patch('knowledge.evidence.EvidenceKnowledgeBase') as factory:
            factory.return_value.version='test';factory.return_value.rows=[];factory.return_value.documents=[]
            client=TestClient(web.app)
            self.assertEqual(client.get('/api/knowledge/retrieve?q=').status_code,400)
            self.assertEqual(client.get('/api/knowledge/catalog').json()['version'],'test')

    def test_delivery_excludes_local_unlicensed_snapshots(self):
        import package_project
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.object(package_project,'ROOT',Path(directory)):
            root=Path(directory)
            (root/'knowledge/.local/snapshots').mkdir(parents=True)
            (root/'knowledge/.local/snapshots/source.html').write_text('private local snapshot')
            (root/'run_kb_demo.py').write_text('# entry')
            (root/'requirements.kb.txt').write_text('jieba')
            names=[name for name,_ in package_project.source_files()]
            self.assertEqual(set(names),{'run_kb_demo.py','requirements.kb.txt'})

if __name__=='__main__':unittest.main()
