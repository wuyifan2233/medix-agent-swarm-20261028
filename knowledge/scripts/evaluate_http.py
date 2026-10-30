"""Run fixed retrieval fixtures against the running demo; never calls chat endpoints."""
import json
import math
import sys
import time
from pathlib import Path
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.query_policy import contextualize_query


def main():
    base='http://127.0.0.1:8766'
    for _ in range(120):
        health=requests.get(base+'/api/health',timeout=10).json()
        if health['knowledge']=='ready':break
        if health['knowledge']=='error':raise RuntimeError('Knowledge initialization failed')
        time.sleep(3)
    assert health['knowledge']=='ready'
    cases=json.loads(Path('knowledge/evaluation_cases.json').read_text(encoding='utf8'));results=[]
    for case in cases:
        query,rewritten=contextualize_query(case['query'],case.get('history',[]))
        response=requests.get(base+'/api/knowledge/retrieve',params={'q':query},timeout=30);response.raise_for_status();r=response.json()
        hits=r['sources'];ids=[Path(h['file']).stem for h in hits]
        if case['kind']=='in_domain':passed=any(Path(h['file']).stem in case['expected_docs'] and any(t in h['content'] for t in case['evidence_terms']) for h in hits)
        elif case['kind']=='audience_mismatch':passed=r['status']=='no_results' and not hits and r['trace'].get('audience_excluded',0)>0
        elif case['kind']=='knowledge_gap':passed=(r['trace'].get('knowledge_gap') or {}).get('kind')==case['expected_gap']
        else:passed=not hits and r['status']==('no_results' if case['kind']=='out_of_domain' else 'needs_information')
        results.append({**case,'passed':bool(passed),'status':r['status'],'docs':ids,'elapsed_ms':r['trace']['elapsed_ms'],'query_rewritten':rewritten})
    durations=sorted(x['elapsed_ms'] for x in results);regular=[x for x in results if x['kind']=='in_domain']
    report={'summary':{'version':health['version'],'documents':health['source_documents'],'chunks':health['documents'],
             'cases_passed':sum(x['passed'] for x in results),'cases_total':len(results),'in_domain_passed':sum(x['passed'] for x in regular),'in_domain_total':len(regular),
             'retrieval_p95_ms':durations[math.ceil(.95*len(durations))-1],'chat_llm_calls':0,'functional_gate_passed':all(x['passed'] for x in results)},'cases':results}
    Path('docs/bulk-http-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report['summary'],ensure_ascii=False))
    print(json.dumps([x for x in results if not x['passed']],ensure_ascii=False))
    return int(not all(x['passed'] for x in results))


if __name__=='__main__':raise SystemExit(main())
