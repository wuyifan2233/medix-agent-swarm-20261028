"""Clean-clone preparation, interruption recovery and model identity regressions."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
from knowledge.corpus import digest
from knowledge.scripts import fetch_sources as fetcher
from knowledge import initialize


class InitializationTests(unittest.TestCase):
    def make_registry(self,root):
        sources=[{'id':key,'title':key,'url':'https://example.test/'+key,'required_terms':[]} for key in ['a','b','c','d']]
        registry=root/'sources.json';registry.write_text(json.dumps({'documents':sources}),encoding='utf8')
        return sources,registry

    def write_source(self,source,destination):
        text='# '+source['id']+'\n\nsynthetic '+source['id'];raw=source['id'].encode()
        (destination/'documents'/(source['id']+'.md')).write_bytes(text.encode())
        (destination/'snapshots'/(source['id']+'.html')).write_bytes(raw)
        return {**source,'content_sha256':digest(text),'snapshot_sha256':hashlib.sha256(raw).hexdigest()}

    def test_interrupted_downloads_resume_and_do_not_publish_below_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sources,registry=self.make_registry(root);local=root/'local'
            calls=[]
            def interrupted(source,destination):
                calls.append(source['id'])
                if source['id']=='d':raise ConnectionError('synthetic failure')
                return self.write_source(source,destination)
            with patch.object(fetcher,'LOCAL',local),patch.object(fetcher,'REGISTRY',registry),patch.object(fetcher,'MINIMUM_DOCUMENTS',3):
                with patch.object(fetcher,'fetch',side_effect=interrupted):
                    with self.assertRaises(RuntimeError):fetcher.main(['--incremental'])
                self.assertFalse((local/'manifest.json').exists())
                with patch.object(fetcher,'fetch',side_effect=self.write_source) as download:
                    fetcher.main(['--incremental'])
                self.assertEqual([c.args[0]['id'] for c in download.call_args_list],['d'])
                self.assertEqual(len(json.loads((local/'manifest.json').read_text())['documents']),4)

    def test_partial_corpus_requires_registry_fingerprint_floor_and_missing_ids(self):
        from knowledge import corpus
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sources,registry=self.make_registry(root);local=root/'local'
            def partial(source,destination):
                if source['id']=='d':raise ConnectionError('synthetic')
                return self.write_source(source,destination)
            labels=root/'applicability.json';labels.write_text('{"documents":{}}')
            with patch.object(fetcher,'LOCAL',local),patch.object(fetcher,'REGISTRY',registry),patch.object(fetcher,'MINIMUM_DOCUMENTS',3),patch.object(fetcher,'fetch',side_effect=partial):
                fetcher.main(['--incremental','--minimum','1'])
            with patch.object(corpus,'LOCAL',local),patch.object(corpus,'REGISTRY',registry),patch.object(corpus,'ROOT',root),patch.object(corpus,'MINIMUM_DOCUMENTS',3):
                self.assertEqual(len(corpus.load_corpus()),3)
                manifest=json.loads((local/'manifest.json').read_text());manifest['registry_sha256']='invalid'
                (local/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):corpus.load_corpus()

    def test_windows_directory_rename_failure_still_publishes_verified_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sources,registry=self.make_registry(root);local=root/'local';original=Path.replace
            def locked_directory(path,target):
                if path.name.startswith('.stage-'):raise PermissionError('synthetic scanner lock')
                return original(path,target)
            with patch.object(fetcher,'LOCAL',local),patch.object(fetcher,'REGISTRY',registry),patch.object(fetcher,'fetch',side_effect=self.write_source),patch.object(Path,'replace',locked_directory):
                fetcher.main(['--incremental'])
            manifest=json.loads((local/'manifest.json').read_text());generation=local/'generations'/manifest['generation']
            self.assertTrue(all(fetcher._verified(d,d,generation) for d in manifest['documents']))

    def test_existing_sources_skip_network_and_corrupt_corpus_fails(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(initialize,'LOCAL',Path(directory)):
            (Path(directory)/'manifest.json').write_text('{}')
            with patch.object(initialize,'load_corpus',return_value=[{}]),patch.object(fetcher,'main') as fetch:
                self.assertEqual(initialize.ensure_sources()['status'],'existing');fetch.assert_not_called()
            with patch.object(initialize,'load_corpus',side_effect=ValueError('Snapshot hash mismatch: synthetic')),patch.object(fetcher,'main') as fetch:
                with self.assertRaises(ValueError):initialize.ensure_sources()
                fetch.assert_not_called()

    def test_fresh_and_cached_bge_have_same_pinned_identity(self):
        from knowledge.embeddings import LocalBGEEmbedding,BGE_REVISION
        model=SimpleNamespace(tokenizer=object(),get_sentence_embedding_dimension=lambda:512)
        factory=Mock(return_value=model)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'HF_HOME':directory}),patch.dict('sys.modules',{'sentence_transformers':SimpleNamespace(SentenceTransformer=factory),'torch':SimpleNamespace(set_num_threads=Mock())}):
            first=LocalBGEEmbedding()
            self.assertEqual(factory.call_args.kwargs['revision'],BGE_REVISION)
            (Path(directory)/'hub/models--BAAI--bge-small-zh-v1.5/snapshots'/BGE_REVISION).mkdir(parents=True)
            second=LocalBGEEmbedding();self.assertEqual(first.identity,second.identity)


if __name__=='__main__':unittest.main()
