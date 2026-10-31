"""Reproducible retrieval evaluation. Does not claim to test LLM answers."""
import json
import sys
import statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.evidence import EvidenceKnowledgeBase
from knowledge.query_policy import contextualize_query

def main():
    kb=EvidenceKnowledgeBase()
    originals={d['id']:d['content'] for d in kb.documents}
    for row in kb.rows:
        metadata=row['metadata']
        assert len(kb.embedding_model.tokenizer.encode(row['content']))<=384
        assert row['content'].split('\n\n',1)[1]==originals[metadata['doc_id']][metadata['start_char']:metadata['end_char']]
    assert kb.count_documents()==len(kb.rows)==len({r['id'] for r in kb.rows})
    kb.retrieve('高血压')
    cases=json.loads((Path(__file__).resolve().parents[1]/'evaluation_cases.json').read_text(encoding='utf-8'))
    results=[]
    for case in cases:
        query,rewritten=contextualize_query(case['query'],case.get('history',[]))
        result=kb.retrieve(query)
        hits=result['hits']
        if case['kind']=='in_domain':
            passed=any(h['metadata']['doc_id'] in case['expected_docs'] and any(t in h['content'] for t in case['evidence_terms']) for h in hits)
        elif case['kind']=='audience_mismatch':
            passed=result['status']=='no_results' and not hits and result['trace'].get('audience_excluded',0)>0
        elif case['kind']=='knowledge_gap':
            passed=result['status']!='error' and (result['trace'].get('knowledge_gap') or {}).get('kind')==case['expected_gap']
        else:
            passed=not hits and result['status']==('no_results' if case['kind']=='out_of_domain' else 'needs_information')
        results.append({**case,'passed':passed,'status':result['status'],'docs':[h['metadata']['doc_id'] for h in hits],'elapsed_ms':result['trace']['elapsed_ms'],'query_rewritten':rewritten})
    regular=[r for r in results if r['kind']=='in_domain']
    durations=sorted(r['elapsed_ms'] for r in results if r['kind']!='needs_information')
    summary={'version':kb.version,'documents':len(kb.documents),'chunks':len(kb.rows),'chunk_budget_and_offsets_verified':True,'in_domain_hit_at_3':sum(r['passed'] for r in regular)/len(regular),'out_of_domain_passed':sum(r['passed'] for r in results if r['kind']=='out_of_domain'),'needs_information_passed':sum(r['passed'] for r in results if r['kind']=='needs_information'),'retrieval_p95_ms':durations[min(len(durations)-1,__import__('math').ceil(.95*len(durations))-1)],'generation_evaluated':False}
    report={'summary':summary,'cases':results}
    summary['embedding']=kb.embedding_model.identity
    summary['reranker']=kb.reranker.identity if kb.reranker else {'provider':'none'}
    summary['cases_total']=len(cases)
    summary['cases_passed']=sum(r['passed'] for r in results)
    summary['in_domain_total']=len(regular)
    summary['functional_gate_passed']=all(r['passed'] for r in results)
    summary['latency_target_ms']=2000
    summary['latency_gate_passed']=summary['retrieval_p95_ms']<=summary['latency_target_ms']
    Path('verification_evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    kb.milvus_client.close()
    kb.embedding_model.close()
    if kb.reranker:kb.reranker.close()
    return int(not summary['functional_gate_passed'] or not summary['latency_gate_passed'])

if __name__=='__main__':raise SystemExit(main())
