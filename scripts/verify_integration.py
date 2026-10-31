"""Offline integration regressions: synthetic accounts and mocked external APIs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MODULES = '''auth.test_auth auth.test_sms_provider
personalization.test_profile personalization.test_evolution personalization.test_conversation personalization.test_preferences
core.test_deepseek tests.test_deepseek_config
knowledge.test_mini knowledge.test_bulk knowledge.test_initialize knowledge.test_bootstrap knowledge.test_embeddings knowledge.test_reranking knowledge.test_evidence knowledge.test_answering knowledge.test_query_policy
web.test_case_memory web.test_case_pipeline web.test_web web.test_speech web.test_startup web.test_provider_errors
memory.test_case_memory memory.test_patient_resolver memory.test_web_mem0
storage.test_integration web.test_reminders qq.test_bridge wechat.test_bridge'''.split()

if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    sys.exit(0 if result.wasSuccessful() else 1)
