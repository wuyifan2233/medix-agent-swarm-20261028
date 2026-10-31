"""Offline setup contracts: no QQ login, subprocesses, downloads or messages."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from qq.napcat_runtime import (DATA_PATH_LINE, ISOLATED_DATA_LINE, LocalAPI, local_settings,
                                login_page, onebot_config, prepare, publish_env)


class NapCatSetupTests(unittest.TestCase):
    def test_tokens_are_machine_local_stable_and_separate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = local_settings(root)
            second = local_settings(root)
            self.assertEqual(first, second)
            self.assertEqual(len({first[key] for key in ('web_token','http_token','ws_token')}), 3)
            self.assertEqual(json.loads((root/'config/webui.json').read_text())['host'], '127.0.0.1')
            publish_env(root, first)
            text = (root/'medix.env').read_text()
            self.assertIn('MEDIX_QQ_BACKEND=onebot', text)
            self.assertIn('MEDIX_QQ_WS_TOKEN='+first['ws_token'], text)

    def test_invalid_ports_do_not_create_runtime(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/'unused'
            with self.assertRaises(ValueError): local_settings(root, 3000, 3000, 3001)
            self.assertFalse(root.exists())

    def test_official_archive_is_checked_and_qq_data_path_is_isolated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); archive = root/'official.zip'; home = root/'install'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for name in ('node.exe','index.js','wrapper.node'): bundle.writestr(name, b'fixture')
                bundle.writestr('napcat/napcat.mjs', DATA_PATH_LINE)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch('qq.napcat_runtime.SHA256', digest):
                prepare(home, archive)
                prepare(home, archive)  # Repeated preparation keeps the existing verified install.
            self.assertEqual((home/'napcat/napcat.mjs').read_bytes(), ISOLATED_DATA_LINE)
            self.assertEqual((home/'napcat/napcat.mjs.official').read_bytes(), DATA_PATH_LINE)

    def test_hash_failure_never_extracts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); archive = root/'bad.zip'; archive.write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError,'SHA256'): prepare(root/'install', archive)
            self.assertFalse((root/'install').exists())

    def test_archive_path_traversal_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); archive = root/'bad.zip'
            with zipfile.ZipFile(archive, 'w') as bundle: bundle.writestr('../escape.txt', b'bad')
            with patch('qq.napcat_runtime.SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(RuntimeError,'不安全路径'): prepare(root/'install', archive)
            self.assertFalse((root/'escape.txt').exists())
            self.assertFalse((root/'install').exists())

    def test_qr_page_has_no_credentials_and_escapes_status(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); settings = local_settings(root)
            login_page(root, '<script>bad</script>')
            page = (root/'login.html').read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;', page)
            for key in ('web_token','http_token','ws_token'): self.assertNotIn(settings[key], page)

    def test_onebot_only_binds_loopback_with_distinct_tokens(self):
        with TemporaryDirectory() as directory:
            settings = local_settings(Path(directory))
            config = onebot_config({'musicSignUrl':'existing'}, settings)
            http = config['network']['httpServers'][0]; ws = config['network']['websocketServers'][0]
            self.assertEqual(http['host'], '127.0.0.1'); self.assertEqual(ws['host'], '127.0.0.1')
            self.assertNotEqual(http['token'], ws['token'])
            self.assertFalse(http['enableCors'])
            self.assertEqual(config['musicSignUrl'], 'existing')


if __name__ == '__main__': unittest.main()
