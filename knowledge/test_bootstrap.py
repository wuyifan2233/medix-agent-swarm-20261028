"""Knowledge bootstrap regressions; fake clients never start a Milvus server."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knowledge.bootstrap import ensure_knowledge_collection, read_legacy_rows, validate_target, LEGACY_SOURCE


class Client:
    def __init__(self, exists=False, count=0, dimension=512):
        self.exists,self.count,self.dimension=exists,count,dimension
        self.inserts=0
    def has_collection(self,_):return self.exists
    def describe_collection(self,_):return {"fields":[{"name":"vector","params":{"dim":self.dimension}}]}
    def get_collection_stats(self,_):return {"row_count":self.count}
    def create_collection(self,**kwargs):self.exists=True;self.dimension=kwargs["dimension"]
    def load_collection(self,_):pass
    def insert(self,_,rows):self.count+=len(rows);self.inserts+=1
    def flush(self,_):pass
    def close(self):pass


class BootstrapTests(unittest.TestCase):
    def rows(self):return [{"vector":[0.0]*512,"content":"synthetic","metadata":"{}","doc_type":"general"}]*180

    def test_fresh_default_is_seeded_and_repeated_start_does_not_duplicate(self):
        client=Client()
        with patch("knowledge.bootstrap.read_legacy_rows",return_value=self.rows()) as loader:
            self.assertEqual(ensure_knowledge_collection(client)["rows"],180)
            self.assertEqual(ensure_knowledge_collection(client)["imported"],0)
        self.assertEqual(client.inserts,1);self.assertEqual(loader.call_count,1)

    def test_existing_empty_collection_is_repaired(self):
        client=Client(exists=True)
        with patch("knowledge.bootstrap.read_legacy_rows",return_value=self.rows()):
            self.assertEqual(ensure_knowledge_collection(client)["status"],"seeded")

    def test_existing_user_documents_are_preserved_without_reading_source(self):
        client=Client(exists=True,count=181)
        with patch("knowledge.bootstrap.read_legacy_rows",side_effect=AssertionError("must not reseed")):
            self.assertEqual(ensure_knowledge_collection(client)["rows"],181)
        self.assertEqual(client.inserts,0)

    def test_custom_empty_collection_can_opt_out_of_bundled_vectors(self):
        client=Client()
        with patch("knowledge.bootstrap.read_legacy_rows",side_effect=AssertionError("must not seed")):
            self.assertEqual(ensure_knowledge_collection(client,"private",64,bootstrap=False)["rows"],0)

    def test_wrong_dimensions_are_rejected_before_writing(self):
        client=Client(exists=True,dimension=768)
        with self.assertRaisesRegex(ValueError,"dimensions"):
            ensure_knowledge_collection(client)
        self.assertEqual(client.inserts,0)

    def test_missing_source_never_creates_an_empty_default_collection(self):
        client=Client()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                ensure_knowledge_collection(client,source=Path(directory)/"absent.db")
        self.assertFalse(client.exists)

    def test_incomplete_import_is_not_reported_as_ready(self):
        client=Client()
        def incomplete(_,rows):client.count=10
        client.insert=incomplete
        with patch("knowledge.bootstrap.read_legacy_rows",return_value=self.rows()):
            with self.assertRaisesRegex(RuntimeError,"did not finish"):
                ensure_knowledge_collection(client)

    def test_source_is_read_only_and_all_180_vectors_have_content(self):
        original=hashlib.sha256(LEGACY_SOURCE.read_bytes()).hexdigest()
        rows=read_legacy_rows()
        self.assertEqual(len(rows),180)
        self.assertTrue(all(len(row["vector"])==512 and row["content"].strip() for row in rows))
        self.assertEqual(hashlib.sha256(LEGACY_SOURCE.read_bytes()).hexdigest(),original)

    def test_legacy_file_cannot_be_selected_as_v3_target(self):
        with self.assertRaisesRegex(ValueError,"legacy source"):
            validate_target(LEGACY_SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/"other.db";file.write_bytes(b"SQLite format 3")
            with self.assertRaisesRegex(ValueError,"directory"):
                validate_target(file)

    def test_direct_kb_initialization_invokes_bootstrap(self):
        import knowledge.milvus_kb as module
        module.MedicalKnowledgeBase._instance=None
        client=Client()
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(module,"SentenceTransformer") as model, patch.object(module,"MilvusClient",return_value=client), patch("knowledge.bootstrap.read_legacy_rows",return_value=self.rows()), patch("knowledge.embeddings.LocalBGEEmbedding") as local:
                local.return_value.model_instance=model.return_value
                model.return_value.get_sentence_embedding_dimension.return_value=512
                kb=module.MedicalKnowledgeBase(db_path=str(Path(directory)/"v3.db"))
                self.assertEqual(kb.count_documents(),180)
                self.assertEqual(client.inserts,1)
        finally:module.MedicalKnowledgeBase._instance=None

    def test_custom_embedding_does_not_load_bge_cache_or_seed_bge_vectors(self):
        import knowledge.milvus_kb as module
        module.MedicalKnowledgeBase._instance=None
        client=Client()
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(module,"SentenceTransformer") as model, patch.object(module,"MilvusClient",return_value=client):
                model.return_value.get_sentence_embedding_dimension.return_value=64
                module.MedicalKnowledgeBase(db_path=str(Path(directory)/"v3.db"),embedding_model="custom-embedding")
                model.assert_called_once_with("custom-embedding",device="cpu")
                self.assertEqual(client.count,0)
        finally:module.MedicalKnowledgeBase._instance=None


if __name__=="__main__":unittest.main()
