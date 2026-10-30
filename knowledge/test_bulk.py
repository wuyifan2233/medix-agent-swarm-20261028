"""Offline regressions for original-document selection and large-corpus caches."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from knowledge.scripts.supplement_common import matching_links
from knowledge.corpus import cached_chunks
from knowledge.test_evidence import CharacterTokenizer


class BulkTests(unittest.TestCase):
    def test_highlighted_names_keep_characters_and_exclude_qa(self):
        html='<a href="/drug/123.html"><em>华</em><em>法</em>林</a><a href="/qa/4.html">华法林</a><a href="https://evil.test/drug/123.html">华法林</a>'
        self.assertEqual(matching_links(html,'drug','华法林'),[('华法林','/drug/123.html','123')])

    def test_incremental_fetch_preserves_order_and_repeats_without_network(self):
        import hashlib
        from knowledge.scripts import fetch_sources
        with tempfile.TemporaryDirectory() as directory:
            local=Path(directory);(local/'documents').mkdir();(local/'snapshots').mkdir()
            sources=[{'id':key,'title':key,'url':'https://example.test/'+key,'required_terms':[]} for key in ['a','b']]
            records=[]
            for source in reversed(sources):
                key=source['id'];text='# '+key+'\n\nsynthetic '+key;raw=b'<html>synthetic</html>'
                (local/'documents'/(key+'.md')).write_bytes(text.encode())
                (local/'snapshots'/(key+'.html')).write_bytes(raw)
                records.append({**source,'content_sha256':hashlib.sha256(text.encode()).hexdigest(),'snapshot_sha256':hashlib.sha256(raw).hexdigest()})
            registry=local/'sources.json';registry.write_text(json.dumps({'documents':sources}),encoding='utf8')
            (local/'manifest.json').write_text(json.dumps({'documents':records}),encoding='utf8')
            with patch.object(fetch_sources,'LOCAL',local),patch.object(fetch_sources,'REGISTRY',registry),patch.object(fetch_sources,'fetch',side_effect=AssertionError('Unexpected fetch')):
                fetch_sources.main(['--incremental']);first=json.loads((local/'manifest.json').read_text(encoding='utf8'))
                fetch_sources.main(['--incremental']);second=json.loads((local/'manifest.json').read_text(encoding='utf8'))
            self.assertEqual([d['id'] for d in first['documents']],['b','a'])
            self.assertEqual(first,second)

    def test_reused_chunk_cache_needs_no_tokenizer(self):
        doc={'id':'synthetic','content':'# 标题\n\n这是足够长的虚构段落。','metadata':{'title':'标题','publisher':'测试'}}
        with tempfile.TemporaryDirectory() as directory,patch('knowledge.corpus.LOCAL',Path(directory)):
            expected=cached_chunks([doc],CharacterTokenizer(),{'model':'test'})
            self.assertEqual(cached_chunks([doc],None,{'model':'test'}),expected)
            p=next((Path(directory)/'chunks').glob('*.json'));payload=json.loads(p.read_text(encoding='utf8'))
            payload['rows'][0]['content']='corrupted';p.write_text(json.dumps(payload),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):cached_chunks([doc],None,{'model':'test'})


if __name__=='__main__':unittest.main()
