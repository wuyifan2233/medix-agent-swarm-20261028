"""Backend fallback must be visible and must never replace explicit evidence mode."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from knowledge.mini_kb import MiniKnowledgeBase, get_knowledge_base


class MiniBackendTests(unittest.TestCase):
    def setUp(self):
        self.old_instance = MiniKnowledgeBase._instance
        MiniKnowledgeBase._instance = None
        self.environment = patch.dict(os.environ, {'MEDIX_KB_MODE':'', 'MEDIX_KB_BACKEND':'auto'})
        self.environment.start()

    def tearDown(self):
        MiniKnowledgeBase._instance = self.old_instance
        self.environment.stop()

    def test_keyword_backend_reads_text_and_filters_types(self):
        with TemporaryDirectory() as directory:
            Path(directory,'synthetic.txt').write_text('虚构资料：高血压患者应核对用药时间。',encoding='utf-8')
            kb=MiniKnowledgeBase(directory)
            self.assertEqual(kb.count_documents(),1)
            self.assertTrue(kb.search('高血压 用药'))
            self.assertEqual(kb.search('高血压',filter_type='other'),[])

    def test_vague_intake_returns_no_documents(self):
        kb=MiniKnowledgeBase()
        query='我最近有些不舒服。请先问我症状、持续时间和相关情况，帮我一起梳理需要关注的信息。'
        self.assertEqual(kb.search(query),[])

    def test_auto_and_explicit_milvus_report_failure(self):
        with patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic unavailable')):
            with self.assertRaises(RuntimeError):get_knowledge_base()
            with patch.dict(os.environ,{'MEDIX_KB_BACKEND':'milvus'}):
                with self.assertRaises(RuntimeError):get_knowledge_base()

    def test_evidence_mode_does_not_fall_back_even_when_mini_requested(self):
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence','MEDIX_KB_BACKEND':'mini'}), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic evidence failure')):
            with self.assertRaises(RuntimeError):get_knowledge_base()

    def test_default_warmup_uses_local_evidence_and_reports_failure(self):
        from web.app import warmup, health
        with patch.dict(os.environ), patch.dict(health):
            os.environ.pop('MEDIX_KB_MODE',None)
            os.environ.pop('MEDIX_EMBEDDING_PROVIDER',None)
            with patch('knowledge.initialize.ensure_sources',side_effect=RuntimeError('synthetic missing corpus')), patch('knowledge.mini_kb.MiniKnowledgeBase') as mini:
                warmup()
                self.assertEqual(os.environ['MEDIX_KB_MODE'],'evidence')
                self.assertEqual(os.environ['MEDIX_EMBEDDING_PROVIDER'],'local')
                self.assertEqual(health['knowledge'],'error')
                mini.assert_not_called()

    def test_warmup_reports_failure_without_fallback(self):
        from web.app import warmup, health
        with patch.dict(health),patch('knowledge.scripts.migrate_legacy_db.migrate',side_effect=RuntimeError('synthetic lock')), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic unavailable')):
            warmup()
            self.assertEqual(health['knowledge'],'error')
            self.assertEqual(health['documents'],0)
            self.assertIn('未切换',health['error'])


class ReminderToolSelectionTests(unittest.TestCase):
    def test_non_consultation_worker_cannot_select_or_execute_reminders(self):
        from agents.base_agent import BaseAgent
        registry=SimpleNamespace(to_openai_format=lambda:[{'function':{'name':'scheduled_reminder'}},
                                                         {'function':{'name':'search_knowledge'}}],execute=AsyncMock())
        agent=SimpleNamespace(agent_id='diagnostic_agent',skill_registry=registry)
        self.assertEqual([t['function']['name'] for t in BaseAgent.get_tools_for_llm(agent)],['search_knowledge'])
        result=asyncio.run(BaseAgent.execute_tool(agent,'scheduled_reminder',{}))
        self.assertFalse(result['success'])
        registry.execute.assert_not_awaited()
