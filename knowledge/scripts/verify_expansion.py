"""Validate persisted BGE corpus and representative retrieval without chat LLM calls."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.corpus import LOCAL, digest
from knowledge.embeddings import LocalBGEEmbedding
from knowledge.evidence import EvidenceKnowledgeBase


def main():
    # A complete existing index must start without re-encoding its documents.
    with patch.object(LocalBGEEmbedding,'encode_documents',side_effect=AssertionError('Unexpected document re-encoding')):
        kb=EvidenceKnowledgeBase()
    assert kb.embedding_model.identity['provider']=='local'
    docs=kb.documents
    assert len(docs)>=3000
    assert len({d['metadata']['url'] for d in docs})==len(docs)
    assert len({digest(''.join(d['content'].split('\n',1)[-1].split())) for d in docs})==len(docs)
    assert all(d['metadata'].get('language','zh')=='zh' for d in docs)
    assert kb.count_documents()==len(kb.rows)
    queries=[('高血压的常见症状有哪些','高血压'),('糖尿病的常见症状有哪些','糖尿病'),
             ('哮喘的常见症状有哪些','哮喘'),('痛风的常见症状有哪些','痛风'),
             ('尿路感染的常见症状有哪些','尿路感染'),('湿疹的常见症状有哪些','湿疹'),
             ('阿莫西林是什么药','阿莫西林'),('奥美拉唑是什么药','奥美拉唑'),
             ('华法林是什么药','华法林'),('氯雷他定是什么药','氯雷他定'),
             ('司美格鲁肽是什么药','司美格鲁肽'),('艾司唑仑是什么药','艾司唑仑')]
    results=[]
    for query,term in queries:
        result=kb.retrieve(query)
        results.append({'query':query,'status':result['status'],'passed':result['status']=='ok' and any(term in h['content'] for h in result['hits']),
                        'titles':[h['metadata']['title'] for h in result['hits']], 'elapsed_ms':result['trace']['elapsed_ms']})
    for query in ['华法林和阿司匹林能一起吃吗','孩子布洛芬吃多少毫克']:
        result=kb.retrieve(query)
        results.append({'query':query,'status':result['status'],'passed':result['status']=='needs_information' and not result['hits']})
    coverage=json.loads((LOCAL/'coverage.json').read_text(encoding='utf8'))
    gaps={group:[k for k,v in coverage[group].items() if v['status']=='gap'] for group in ['diseases','drugs']}
    report={'documents':len(docs),'chunks':len(kb.rows),'version':kb.version,'database':kb.db_path,'embedding':kb.embedding_model.identity,
            'persistent_reload_without_document_encoding':True,'coverage_gaps':gaps,'cases_passed':sum(r['passed'] for r in results),
            'cases_total':len(results),'cases':results,'chat_llm_calls':0}
    Path('docs/bulk-retrieval-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    kb.milvus_client.close();kb.embedding_model.close()
    if kb.reranker:kb.reranker.close()
    return int(not all(r['passed'] for r in results) or any(gaps.values()))


if __name__=='__main__':raise SystemExit(main())
