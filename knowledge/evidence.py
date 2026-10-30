"""Versioned evidence corpus with hybrid retrieval, separate from legacy bootstrap."""
import json
import os
import re
import threading
import time
from pathlib import Path
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from pymilvus import MilvusClient
from knowledge.embeddings import create_embedder, normalize_vectors
from knowledge.reranking import create_reranker, rerank_candidates
from knowledge.bootstrap import validate_target
from knowledge.corpus import LOCAL, CHUNK_VERSION, chunk_document, digest, load_corpus
from knowledge.query_policy import normalize_query, insufficient_medication, requested_audience, applicability, knowledge_gap

def tokens(text):
    return [x.lower() for x in jieba.cut_for_search(text) if re.search(r'[\w\u4e00-\u9fff]', x)]


def validate_citations(answer, count):
    answer=re.sub(r'\[(\d+(?:\s*[,，]\s*\d+)+)\]',lambda m:''.join('['+n+']' for n in re.findall(r'\d+',m[1])),answer)
    invalid = sorted({int(n) for n in re.findall(r'\[(\d+)\]', answer) if not 1 <= int(n) <= count})
    answer = re.sub(r'\[(\d+)\]', lambda m: m.group() if 1 <= int(m[1]) <= count else '（引用无效）', answer)
    return answer, invalid


class EvidenceKnowledgeBase:
    _instance = None
    _init_lock = threading.RLock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        with self._init_lock:
            if getattr(self, '_initialized', False):
                return
            docs = load_corpus()
            self.reranker = create_reranker()
            self.embedding_model = create_embedder()
            self.embedding_dim = self.embedding_model.dimension
            self.rows = [chunk for doc in docs for chunk in chunk_document(doc, self.embedding_model.tokenizer)]
            if not self.rows or len({r['id'] for r in self.rows}) != len(self.rows):
                raise ValueError('Empty corpus or duplicate chunk IDs')
            self.version = digest(json.dumps({'chunks':[(r['id'],r['metadata']['content_sha256'],r['metadata']['url']) for r in self.rows],'metadata':[d['metadata'] | {'retrieved_at':''} for d in docs],'embedding':self.embedding_model.identity,'chunker':CHUNK_VERSION},sort_keys=True,ensure_ascii=False))[:16]
            # MEDIX_DB_PATH remains the legacy database setting. Evidence uses its own
            # versioned root so migration cannot accidentally insert bundled samples.
            import tempfile
            default = Path(tempfile.gettempdir())/'medix-evidence'
            self.db_path = validate_target(Path(os.environ.get('MEDIX_EVIDENCE_ROOT', str(default)))/self.version/'milvus.db')
            self.collection_name = 'medical_evidence'
            self._lock = threading.RLock()
            self.milvus_client = MilvusClient(self.db_path)
            try:
                if not self.milvus_client.has_collection(self.collection_name):
                    self.milvus_client.create_collection(collection_name=self.collection_name,dimension=self.embedding_dim,metric_type='COSINE',auto_id=False,id_type='string',max_length=64)
                count = self.count_documents()
                if count not in (0,len(self.rows)):
                    raise ValueError('Incomplete evidence index; choose a fresh MEDIX_EVIDENCE_ROOT')
                if count == 0:
                    vectors = self.embedding_model.encode_documents([r['content'] for r in self.rows])
                    self.milvus_client.insert(self.collection_name,[{'id':r['id'],'vector':v.tolist(),'content':r['content'],'metadata':json.dumps(r['metadata'],ensure_ascii=False),'doc_type':r['metadata']['type']} for r,v in zip(self.rows,vectors)])
                    self.milvus_client.flush(self.collection_name)
                self.milvus_client.load_collection(self.collection_name)
                description=self.milvus_client.describe_collection(self.collection_name)
                field=next(f for f in description['fields'] if f['name']=='vector')
                if int(field['params']['dim'])!=self.embedding_dim:
                    raise ValueError('Evidence index dimension does not match embedding backend')
                actual = self.milvus_client.query(self.collection_name,filter='',output_fields=['id','vector'],limit=len(self.rows)+1)
                if {r['id'] for r in actual} != {r['id'] for r in self.rows}:
                    raise ValueError('Evidence index identity mismatch')
                stored=normalize_vectors([r['vector'] for r in actual],self.embedding_dim,len(actual))
                self.document_vectors={r['id']:v for r,v in zip(actual,stored)}
            except Exception:
                self.milvus_client.close()
                raise
            self.lexical = BM25Okapi([tokens(r['content']) for r in self.rows])
            self.by_id = {r['id']:r for r in self.rows}
            self.documents = docs
            self.scope_terms = set(t for doc in docs for t in doc['metadata']['topics']) | {'用药','抗生素','咳嗽','补液盐','退热','退烧','低血糖','胰岛素'}
            self._initialized = True
            (LOCAL/'index.json').write_text(json.dumps({'version':self.version,'database':self.db_path,'documents':len(docs),'chunks':len(self.rows),'embedding':self.embedding_model.identity,'chunk_version':CHUNK_VERSION},ensure_ascii=False,indent=2),encoding='utf-8')

    def count_documents(self):
        return int(self.milvus_client.get_collection_stats(self.collection_name)['row_count'])

    def retrieve(self, query, top_k=3, filter_type=None):
        started = time.perf_counter()
        if not isinstance(query,str) or not query.strip() or len(query)>8000 or not 1<=top_k<=20:
            raise ValueError('Query must be 1–8000 characters and top_k 1–20')
        query = normalize_query(query)
        audience=requested_audience(query)
        gap=knowledge_gap(query,self.documents)
        trace = {'vector_candidates':0,'keyword_candidates':0,'merged_candidates':0,'selected':0,'version':self.version,'audience':audience,'knowledge_gap':gap,'rerank':{'status':'skipped' if self.reranker else 'disabled'}}
        if insufficient_medication(query):
            return {'status':'needs_information','hits':[],'trace':{**trace,'elapsed_ms':round((time.perf_counter()-started)*1000,1)},'message':'当前知识库提供基础科普，不能据此确定个人用药、剂量或联合用药。请提供具体制剂、规格、年龄、相关病史及当前用药，并咨询医生或药师。'}
        # This is a deliberately small demo corpus: do not claim general medicine
        # coverage merely because an unrelated query has a high dense similarity.
        if not any(term in query for term in self.scope_terms):
            return {'status':'no_results','hits':[],'trace':{**trace,'elapsed_ms':round((time.perf_counter()-started)*1000,1)},'message':'当前知识库资料不足，该问题不在本批资料明确覆盖的主题内。'}
        try:
            with self._lock:
                vector = self.embedding_model.encode_query(query)
                filt = 'doc_type == '+json.dumps(filter_type) if filter_type else ''
                found = self.milvus_client.search(collection_name=self.collection_name,data=[vector.tolist()],limit=10,filter=filt,output_fields=['content','metadata'])
                dense = found[0]
                scores = self.lexical.get_scores(tokens(query))
                sparse = [self.rows[i]['id'] for i in np.argsort(-scores) if scores[i]>0 and (not filter_type or self.rows[i]['metadata']['type']==filter_type)][:10]
                similarities = {h['id']:float(h['distance']) for h in dense}
                extra = [self.by_id[cid] for cid in sparse if cid not in similarities]
                if extra:
                    similarities.update({r['id']:float(np.dot(self.document_vectors[r['id']],vector)) for r in extra})
                ranks = {}
                for ids in ([h['id'] for h in dense],sparse):
                    for rank,cid in enumerate(ids,1):ranks[cid]=ranks.get(cid,0)+1/(60+rank)
                ranked = sorted(ranks,key=lambda cid:(-ranks[cid],cid))
                subjects={term for term in ('对乙酰氨基酚','布洛芬','氯雷他定','口服补液盐','高血压','糖尿病','流感','鼻炎','哮喘','胃肠炎','腹泻') if term in query}
                hits=[];seen=set();audience_excluded=0;per_document={}
                for cid in ranked:
                    row=self.by_id[cid]
                    if similarities.get(cid,-1)<.4 or row['content'] in seen:continue
                    if subjects and not subjects.intersection(row['metadata']['topics']):continue
                    subtopics=[word for word in ('水果','血压计','食盐') if word in query]
                    if subtopics and not all(word in row['content'] for word in subtopics):continue
                    if '饮食' in query and not any(word in row['content'] for word in ('饮食','膳食','食物')):continue
                    suitability=applicability(row['metadata'],audience)
                    if suitability=='mismatch':
                        audience_excluded+=1
                        continue
                    seen.add(row['content'])
                    doc_id=row['metadata']['doc_id']
                    if per_document.get(doc_id,0)>=2:continue
                    per_document[doc_id]=per_document.get(doc_id,0)+1
                    hits.append({**row,'score':similarities[cid],'rrf_score':ranks[cid],'applicability':suitability})
                hits,trace['rerank']=rerank_candidates(self.reranker,query,hits,top_k)
                trace.update(vector_candidates=len(dense),keyword_candidates=len(sparse),merged_candidates=len(ranks),selected=len(hits),audience_excluded=audience_excluded)
                message=gap['message'] if gap else ''
                if not hits and not message:message='当前没有适合所述人群的相关资料。' if audience_excluded else '当前知识库资料不足，未找到足够相关的证据。'
                return {'status':'ok' if hits else 'no_results','hits':hits,'trace':{**trace,'elapsed_ms':round((time.perf_counter()-started)*1000,1)},'message':message}
        except Exception as exc:
            return {'status':'error','hits':[],'trace':{**trace,'elapsed_ms':round((time.perf_counter()-started)*1000,1)},'message':'知识库检索故障：'+type(exc).__name__}

    def search(self, query, top_k=5, filter_type=None):
        result=self.retrieve(query,top_k=top_k,filter_type=filter_type)
        if result['status']=='error':raise RuntimeError(result['message'])
        return result['hits']


def evidence_sources(hits, query=''):
    return [{'citation':i,'id':r['id'],'title':r['metadata']['title'],'file':r['metadata']['filename'],
             'excerpt':r['content'][:220],'content':r['content'],'publisher':r['metadata']['publisher'],
             'published_at':r['metadata'].get('published_at'),'url':r['metadata']['url'],
             'section':r['metadata']['section'],'start_char':r['metadata']['start_char'],
             'source_checked':r['metadata']['source_checked'],'clinical_reviewed':False,
             'audiences':r['metadata'].get('audiences',['unspecified']),'evidence_kind':r['metadata'].get('evidence_kind','unspecified'),
             'applicability':r.get('applicability','needs_confirmation'),
             'content_sha256':r['metadata']['content_sha256'],
             'highlight_terms':list(dict.fromkeys(t for t in tokens(normalize_query(query)) if len(t)>=2))[:16]} for i,r in enumerate(hits,1)]
