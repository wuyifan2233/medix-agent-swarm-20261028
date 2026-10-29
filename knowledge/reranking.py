"""Optional SiliconFlow reranking; separate from vector encoding and storage."""
import math
import os
import time
import httpx
from knowledge.embeddings import load_api_key

URL='https://api.siliconflow.cn/v1/rerank'
MODEL='Qwen/Qwen3-Reranker-8B'
INSTRUCTION='Given a medical question, rank passages by how directly they provide evidence that answers the question.'


class RerankError(RuntimeError):
    pass


class SiliconFlowReranker:
    def __init__(self,client=None):
        key=load_api_key('SILICONFLOW_API_KEY')
        if client is None and (not key or key.lower()=='xxx'):
            raise ValueError('请在 .env.local 或环境变量配置 SILICONFLOW_API_KEY，xxx 仅为占位；或设置 MEDIX_RERANK_PROVIDER=none')
        self.key=key
        self.client=client or httpx.Client(timeout=30.0)
        self.identity={'provider':'siliconflow','model':MODEL,'endpoint':URL,'instruction':INSTRUCTION}

    def rerank(self,query,hits):
        if not hits:return []
        try:
            response=self.client.post(URL,headers={'Authorization':'Bearer '+self.key},json={
                'model':MODEL,'query':query,'documents':[h['content'] for h in hits],
                'instruction':INSTRUCTION,'top_n':len(hits),'return_documents':False})
            response.raise_for_status()
            results=response.json()['results']
            indices=[r['index'] for r in results]
            if len(results)!=len(hits) or any(type(i) is not int for i in indices) or sorted(indices)!=list(range(len(hits))):
                raise RerankError('Rerank response has missing, duplicate or invalid indices')
            scores=[float(r['relevance_score']) for r in results]
            if not all(math.isfinite(s) for s in scores):raise RerankError('Invalid rerank scores')
            ranked=sorted(zip(results,scores),key=lambda item:-item[1])
            return [{**hits[r['index']],'rerank_score':score} for r,score in ranked]
        except RerankError:
            raise
        except Exception:
            raise RerankError('SiliconFlow rerank failed; using hybrid retrieval order') from None

    def close(self):self.client.close()


def create_reranker():
    provider=os.environ.get('MEDIX_RERANK_PROVIDER','none').lower()
    if provider=='none':return None
    if provider=='siliconflow':return SiliconFlowReranker()
    raise ValueError('MEDIX_RERANK_PROVIDER must be none or siliconflow')


def rerank_candidates(reranker,query,hits,top_k):
    if reranker is None:return hits[:top_k],{'status':'disabled'}
    if not hits:return [],{'status':'skipped','candidates':0,'model':MODEL}
    started=time.perf_counter()
    candidates=hits[:10]
    try:
        ranked=reranker.rerank(query,candidates)
        return ranked[:top_k],{'status':'ok','model':MODEL,'candidates':len(candidates),'elapsed_ms':round((time.perf_counter()-started)*1000,1)}
    except RerankError:
        return hits[:top_k],{'status':'degraded','model':MODEL,'candidates':len(candidates),'elapsed_ms':round((time.perf_counter()-started)*1000,1),'message':'重排暂不可用，已使用混合检索排序。'}
