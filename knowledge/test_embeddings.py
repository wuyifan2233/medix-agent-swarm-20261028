"""Gitee OpenAPI contract tests using the actual SDK and in-process HTTP transport."""
import json
import os
import unittest
from unittest.mock import patch
import httpx
import numpy as np
from openai import OpenAI
from knowledge.embeddings import GiteeQwenEmbedding, EmbeddingError, normalize_vectors, create_embedder, load_api_key


class Tokenizer:
    init_kwargs={'_commit_hash':'test-tokenizer-revision'}


class EmbeddingTests(unittest.TestCase):
    def backend(self, handler):
        client=OpenAI(api_key='unit-test-token',base_url='https://ai.gitee.com/v1',max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(client.close)
        return GiteeQwenEmbedding(client=client,tokenizer=Tokenizer())

    def test_auth_batching_order_query_instruction_and_normalization(self):
        requests=[]
        def handler(request):
            body=json.loads(request.content);requests.append(body)
            self.assertEqual(request.url.path,'/v1/embeddings')
            self.assertEqual(request.headers['authorization'],'Bearer unit-test-token')
            self.assertEqual(body['model'],'Qwen3-Embedding-8B')
            self.assertEqual(body['encoding_format'],'float')
            self.assertEqual(body['dimensions'],4096)
            data=[{'index':i,'embedding':[float(i+1),1.0]+[0.0]*4094} for i in reversed(range(len(body['input'])))]
            return httpx.Response(200,json={'object':'list','model':body['model'],'data':data})
        with patch.dict(os.environ,{'MEDIX_EMBEDDING_BATCH_SIZE':'2'}):backend=self.backend(handler)
        vectors=backend.encode_documents(['doc-a','doc-b','doc-c'])
        self.assertEqual(vectors.shape,(3,4096))
        np.testing.assert_allclose(np.linalg.norm(vectors,axis=1),1,rtol=1e-6)
        self.assertLess(vectors[0][0],vectors[1][0])
        self.assertEqual(requests[0]['input'],['doc-a','doc-b'])
        self.assertEqual(requests[1]['input'],['doc-c'])
        backend.encode_query('高血压')
        self.assertEqual(requests[-1]['input'],['Instruct: '+backend.query_instruction+'\nQuery: 高血压'])
        self.assertNotIn('unit-test-token',json.dumps(backend.identity))

    def test_duplicate_or_missing_indices_rejected(self):
        def handler(request):return httpx.Response(200,json={'object':'list','data':[{'index':0,'embedding':[1.0]*4096}]*2})
        backend=self.backend(handler)
        with self.assertRaisesRegex(EmbeddingError,'indices'):backend.encode_documents(['a','b'])

    def test_wrong_dimensions_rejected(self):
        backend=self.backend(lambda request:httpx.Response(200,json={'data':[{'index':0,'embedding':[1.0]*512}]}))
        with self.assertRaisesRegex(EmbeddingError,'shape'):backend.encode_query('query')

    def test_zero_nan_and_infinite_vectors_rejected(self):
        for values in ([[0,0]],[[float('nan'),1]],[[float('inf'),1]]):
            with self.assertRaises(EmbeddingError):normalize_vectors(values,2,1)

    def test_auth_error_does_not_echo_server_body_or_inputs(self):
        backend=self.backend(lambda request:httpx.Response(401,json={'error':{'message':'unit-test-token sensitive-text'}}))
        with self.assertRaises(EmbeddingError) as caught:backend.encode_query('sensitive-text')
        self.assertNotIn('unit-test-token',str(caught.exception));self.assertNotIn('sensitive-text',str(caught.exception))

    def test_missing_key_fails_instead_of_falling_back_to_bge(self):
        with patch.dict(os.environ,{'GITEE_AI_API_KEY':'','MEDIX_EMBEDDING_PROVIDER':'gitee'}), patch('knowledge.embeddings.load_gitee_key',return_value=''):
            with self.assertRaisesRegex(EmbeddingError,'GITEE_AI_API_KEY'):create_embedder()

    def test_provider_identity_changes_index_version(self):
        from knowledge.corpus import digest
        backend=self.backend(lambda request:None)
        identity=backend.identity
        other={**identity,'provider':'local','model':'BAAI/bge-small-zh-v1.5'}
        self.assertNotEqual(digest(json.dumps(identity,sort_keys=True)),digest(json.dumps(other,sort_keys=True)))

    def test_environment_overrides_shared_local_key_file(self):
        with patch.dict(os.environ,{'GITEE_AI_API_KEY':'env-key'}),patch('dotenv.dotenv_values',side_effect=AssertionError('must not read local key')):
            self.assertEqual(load_api_key('GITEE_AI_API_KEY'),'env-key')

    def test_two_services_read_separate_keys_from_same_local_file(self):
        with patch.dict(os.environ,{'GITEE_AI_API_KEY':'','SILICONFLOW_API_KEY':''}),patch('dotenv.dotenv_values',return_value={'GITEE_AI_API_KEY':'gitee-test','SILICONFLOW_API_KEY':'xxx'}):
            self.assertEqual(load_api_key('GITEE_AI_API_KEY'),'gitee-test')
            self.assertEqual(load_api_key('SILICONFLOW_API_KEY'),'xxx')

if __name__=='__main__':unittest.main()
