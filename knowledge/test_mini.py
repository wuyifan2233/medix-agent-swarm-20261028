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

    def test_auto_falls_back_but_explicit_milvus_reports_failure(self):
        with patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic unavailable')):
            self.assertEqual(get_knowledge_base().backend,'mini')
            with patch.dict(os.environ,{'MEDIX_KB_BACKEND':'milvus'}):
                with self.assertRaises(RuntimeError):get_knowledge_base()

    def test_evidence_mode_does_not_fall_back_even_when_mini_requested(self):
        with patch.dict(os.environ,{'MEDIX_KB_MODE':'evidence','MEDIX_KB_BACKEND':'mini'}), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic evidence failure')):
            with self.assertRaises(RuntimeError):get_knowledge_base()

    def test_warmup_labels_fallback_backend(self):
        from web.app import warmup, health
        with patch.dict(health),patch('knowledge.scripts.migrate_legacy_db.migrate',side_effect=RuntimeError('synthetic lock')), \
             patch('knowledge.milvus_kb.MedicalKnowledgeBase',side_effect=RuntimeError('synthetic unavailable')):
            warmup()
            self.assertEqual(health['knowledge'],'ready')
            self.assertEqual(health['knowledge_backend'],'mini')
            self.assertGreater(health['documents'],0)


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
