"""Embedding backends: Gitee/SiliconFlow Qwen API or explicit local BGE."""
import os
from pathlib import Path
import numpy as np

GITEE_URL = 'https://ai.gitee.com/v1'
QWEN_MODEL = 'Qwen3-Embedding-8B'
QUERY_INSTRUCTION = 'Given a medical question, retrieve relevant passages that answer the question'


from runtime_settings import load_setting


def load_api_key(name):
    return load_setting(name)


def load_gitee_key():
    return load_api_key('GITEE_AI_API_KEY')


class EmbeddingError(RuntimeError):
    """Sanitized backend failure; never include credentials or input texts."""


def normalize_vectors(vectors, dimension, count):
    try:
        result = np.asarray(vectors, dtype=np.float32)
    except (ValueError, TypeError) as exc:
        raise EmbeddingError('Embedding response contains invalid numeric vectors') from None
    if result.shape != (count, dimension) or not np.isfinite(result).all():
        raise EmbeddingError('Embedding response shape or numeric values are invalid')
    norms = np.linalg.norm(result, axis=1, keepdims=True)
    if np.any(norms <= 0) or not np.isfinite(norms).all():
        raise EmbeddingError('Embedding response contains zero or invalid vectors')
    return result / norms


class GiteeQwenEmbedding:
    provider='gitee'
    endpoint=GITEE_URL
    model_name=QWEN_MODEL
    key_name='GITEE_AI_API_KEY'

    def __init__(self, client=None, tokenizer=None):
        key = load_gitee_key() if self.provider=='gitee' else load_api_key(self.key_name)
        if client is None and (not key or key.lower()=='xxx'):
            raise EmbeddingError(f'请在 .env.local 或环境变量设置 {self.key_name}；离线 BGE 请显式设置 MEDIX_EMBEDDING_PROVIDER=local')
        self.model = self.model_name
        self.dimension = 4096
        self.batch_size = int(load_setting('MEDIX_EMBEDDING_BATCH_SIZE', '8'))
        if not 1 <= self.batch_size <= 1000:
            raise ValueError('MEDIX_EMBEDDING_BATCH_SIZE must be 1–1000')
        self.query_instruction = QUERY_INSTRUCTION
        if tokenizer is None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(os.environ.get('MEDIX_EMBEDDING_TOKENIZER_PATH', 'Qwen/Qwen3-Embedding-8B'), trust_remote_code=False)
        self.tokenizer = tokenizer
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=self.endpoint, timeout=30.0, max_retries=2)
        self.client = client
        # Separate provider, dimension and query template even if vector sizes match.
        self.identity = {'provider':self.provider,'endpoint':self.endpoint,'model':self.model,
                         'dimension':self.dimension,'normalization':'l2',
                         'query_instruction':self.query_instruction,'document_instruction':'',
                         'tokenizer':'Qwen/Qwen3-Embedding-8B',
                         'tokenizer_revision':getattr(tokenizer,'init_kwargs',{}).get('_commit_hash','unversioned')}

    def _encode(self, texts):
        if not texts:
            return np.empty((0,self.dimension),dtype=np.float32)
        if any(not isinstance(t,str) or not t.strip() for t in texts):
            raise ValueError('Embedding inputs must be nonempty strings')
        batches=[]
        for start in range(0,len(texts),self.batch_size):
            batch=texts[start:start+self.batch_size]
            try:
                response=self.client.embeddings.create(model=self.model,input=batch,encoding_format='float',dimensions=self.dimension)
                data=response.data
                indices=[item.index for item in data]
                if len(data)!=len(batch) or sorted(indices)!=list(range(len(batch))):
                    raise EmbeddingError('Embedding response has missing or duplicate indices')
                vectors=[item.embedding for item in sorted(data,key=lambda item:item.index)]
            except EmbeddingError:
                raise
            except Exception as exc:
                status=getattr(exc,'status_code',None)
                suffix=f' (HTTP {status})' if isinstance(status,int) else ''
                raise EmbeddingError(f'{self.provider} embedding request failed{suffix}; check credentials, quota and network') from None
            batches.append(normalize_vectors(vectors,self.dimension,len(batch)))
        return np.concatenate(batches)

    def encode_documents(self,texts):
        return self._encode(list(texts))

    def encode_query(self,text):
        return self._encode([f'Instruct: {self.query_instruction}\nQuery: {text}'])[0]

    def close(self):
        self.client.close()


class LocalBGEEmbedding:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        model='BAAI/bge-small-zh-v1.5'
        cache=Path(os.environ.get('HF_HOME',str(Path.home()/'.cache/huggingface')))
        available=sorted((cache/'hub/models--BAAI--bge-small-zh-v1.5/snapshots').glob('*'))
        path=str(available[-1]) if available else model
        self.model_instance=SentenceTransformer(path,device='cpu')
        self.tokenizer=self.model_instance.tokenizer
        self.dimension=self.model_instance.get_sentence_embedding_dimension()
        self.identity={'provider':'local','model':model,'dimension':self.dimension,
                       'revision':Path(path).name if available else model,'normalization':'l2'}

    def encode_documents(self,texts):
        return normalize_vectors(self.model_instance.encode(texts,normalize_embeddings=True,show_progress_bar=False),self.dimension,len(texts))

    def encode_query(self,text):
        return self.encode_documents([text])[0]

    def close(self):
        pass


class SiliconFlowQwenEmbedding(GiteeQwenEmbedding):
    provider='siliconflow'
    endpoint='https://api.siliconflow.cn/v1'
    model_name='Qwen/Qwen3-Embedding-8B'
    key_name='SILICONFLOW_API_KEY'


def create_embedder():
    provider=load_setting('MEDIX_EMBEDDING_PROVIDER','gitee').lower()
    if provider=='gitee':return GiteeQwenEmbedding()
    if provider=='siliconflow':return SiliconFlowQwenEmbedding()
    if provider=='local':return LocalBGEEmbedding()
    raise ValueError('MEDIX_EMBEDDING_PROVIDER must be gitee, siliconflow or local')
