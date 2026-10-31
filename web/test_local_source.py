import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from knowledge.corpus import digest
from web.local_source import read_article, article_html

class LocalSourceTests(unittest.TestCase):
    def test_full_article_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'documents').mkdir()
            content='完整原文\n'+('内容'*1000)
            (root/'documents/article.md').write_text(content,encoding='utf-8')
            (root/'manifest.json').write_text(json.dumps({'documents':[{'id':'article','title':'文章','publisher':'平台','content_sha256':digest(content)}]}),encoding='utf-8')
            self.assertEqual(read_article('article.md',root)['content'],content)
            self.assertIsNone(read_article('../article.md',root))
            self.assertIsNone(read_article('missing.md',root))
            (root/'documents/article.md').write_text('tampered',encoding='utf-8')
            with self.assertRaises(ValueError):read_article('article.md',root)

    def test_html_never_executes_source_markup(self):
        rendered=article_html({'title':'<script>bad</script>','publisher':'x','content':'<img src=https://example.com onerror=bad()>'})
        self.assertNotIn('<script>',rendered)
        self.assertNotIn('<img',rendered)
        self.assertIn('&lt;img',rendered)

    def test_route_returns_local_html_and_explicit_missing(self):
        from fastapi.testclient import TestClient
        from web.app import app
        with TestClient(app) as client,patch('web.local_source.read_article',return_value={'title':'文章','publisher':'平台','content':'完整原文'}) as read:
            response=client.get('/knowledge/source/article.md')
            self.assertEqual(response.status_code,200)
            self.assertIn('完整原文',response.text)
            self.assertIn("default-src 'none'",response.headers['content-security-policy'])
            read.return_value=None
            self.assertEqual(client.get('/knowledge/source/missing.md').status_code,404)
