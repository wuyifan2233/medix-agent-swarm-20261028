import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_web import configure_database


class StartupDatabaseTests(unittest.TestCase):
    def test_evidence_entry_loads_same_local_credentials_and_port_origins(self):
        from run_web import main
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv',['run_kb_demo.py','--port','8999']), \
             patch('dotenv.load_dotenv') as load, patch('uvicorn.run') as run:
            main(default_port=8766,evidence=True)
            self.assertEqual([call.args[0].name for call in load.call_args_list],['.env.local','.env.sms'])
            self.assertEqual(os.environ['MEDIX_KB_MODE'],'evidence')
            self.assertIn('http://127.0.0.1:8999',os.environ['MEDIX_ALLOWED_ORIGINS'])
            self.assertEqual(run.call_args.kwargs['port'],8999)

    def setUp(self):
        import runtime_paths
        original = runtime_paths.DB_PATH
        self.addCleanup(setattr,runtime_paths,'DB_PATH',original)
    def test_default_web_ports_are_isolated_from_each_other_and_cli(self):
        from runtime_paths import DEFAULT_DB_PATH
        with patch.dict(os.environ,{},clear=True):
            first = configure_database(8744)
        with patch.dict(os.environ,{},clear=True):
            second = configure_database(8755)
        self.assertNotEqual(first,second)
        self.assertNotEqual(first,str(Path(DEFAULT_DB_PATH).resolve()))
        self.assertNotEqual(second,str(Path(DEFAULT_DB_PATH).resolve()))

    def test_configured_database_is_respected_and_flag_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = str((Path(directory)/'configured.db').resolve())
            explicit = str((Path(directory)/'explicit.db').resolve())
            with patch.dict(os.environ,{'MEDIX_DB_PATH':configured}):
                self.assertEqual(configure_database(8744),configured)
                self.assertEqual(configure_database(8744,explicit),explicit)
                self.assertEqual(os.environ['MEDIX_DB_PATH'],explicit)
                import runtime_paths
                self.assertEqual(runtime_paths.DB_PATH,explicit)

    def test_locked_database_has_actionable_error_without_provider_details(self):
        from web.app import warmup,health
        with patch.dict(os.environ,{'MEDIX_KB_BACKEND':'milvus'}),patch.dict(health),patch('knowledge.scripts.migrate_legacy_db.migrate',side_effect=RuntimeError('Open local milvus failed')):
            warmup()
            self.assertEqual(health['knowledge'],'error')
            self.assertIn('--db-path',health['error'])
            self.assertIn('其他实例',health['error'])
