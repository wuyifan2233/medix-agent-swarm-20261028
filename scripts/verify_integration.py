"""Offline integration regressions: synthetic accounts and mocked external APIs."""
import sys
import os
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MODULES = '''auth.test_auth auth.test_sms_provider
personalization.test_registration_profile personalization.test_preferences
core.test_deepseek tests.test_deepseek_config
knowledge.test_mini knowledge.test_bulk knowledge.test_initialize knowledge.test_bootstrap knowledge.test_embeddings knowledge.test_reranking knowledge.test_evidence knowledge.test_answering knowledge.test_query_policy
web.test_request_routing web.test_channel_wallet web.test_care_wallet web.test_chat_delivery web.test_case_memory web.test_case_pipeline web.test_web web.test_speech web.test_startup web.test_provider_errors web.test_report_integrity web.test_vision

memory.test_case_memory memory.test_patient_resolver memory.test_web_mem0
storage.test_integration web.test_reminders qq.test_bridge qq.test_snowluma_capture qq.test_napcat_runtime wechat.test_bridge'''.split()

if __name__ == '__main__':
    # Even imports and legacy fixture cleanup must never touch the preview DB.
    with TemporaryDirectory(prefix='medix-regression-') as directory:
        os.environ['MEDIX_DATA_DIR']=directory
        os.environ['MEDIX_DATABASE_URL']='sqlite:///'+(Path(directory)/'app.db').as_posix()
        os.environ['MEDIX_IDENTITY_NAMESPACE']='regression-isolated'
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
        sys.exit(0 if result.wasSuccessful() else 1)
