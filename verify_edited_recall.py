"""Real web/Mem0 edit-and-recall regression with a disposable fictional user."""
import argparse
import json
import re
import time
import uuid
from pathlib import Path

import httpx


def chat(client,chat_id,message):
    response=client.post('/api/chat',json={'chat_id':chat_id,'message':message})
    assert response.status_code==202,'Chat was not accepted'
    job_id=response.json()['job_id']
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        response=client.get('/api/jobs/'+job_id)
        response.raise_for_status()
        job=response.json()
        if job['status']=='completed': return job['result']
        assert job['status']!='failed','Chat processing failed'
        time.sleep(1)
    raise AssertionError('Chat timed out')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8767')
    args=parser.parse_args()
    report={'check':'edited_memory_recall','status':'failed'}
    chat_id=str(uuid.uuid4())
    with httpx.Client(base_url=args.base_url,cookies={'medix_browser':uuid.uuid4().hex},timeout=30) as client:
        try:
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                health=client.get('/api/health').json()
                if health['knowledge']!='loading': break
                time.sleep(1)
            assert health['knowledge']=='ready','Knowledge unavailable'
            initial=chat(client,chat_id,'我昨晚发烧到39度。请用一句话简短回复。')
            assert initial['memory_status']=='saved','Initial fictional fact was not saved'
            ident=initial['memory_saved']['id']
            row=next(row for row in client.get('/api/memories?scope=self').json()['memories'] if row['id']==ident)
            response=client.post('/api/memories/'+ident+'/edit',json={
                'chat_id':chat_id,'content':'我昨晚发烧到38度。','observations':'','expected_revision':row['revision']})
            assert response.status_code==200,'Edit failed'
            assert response.json()['record']['id']==ident
            report['same_id_edit_verified']=True
            for label,session,question in (
                ('same_chat',chat_id,'我昨晚发烧到多少度？请根据记忆简短回答。'),
                ('new_chat',str(uuid.uuid4()),'我昨晚的体温是多少？请根据记忆简短回答。')):
                result=chat(client,session,question)
                report[label]={'answer':result['answer'],'memory_status':result['memory_status'],
                               'patient_resolution':result.get('patient_resolution'),
                               'references':result.get('memory_references',[]),
                               'candidates':result.get('memory_candidates',[]),
                               'memory_error':result.get('memory_error')}
                first_temperature=re.search(r'(?<!\d)(38|39)(?:\.0)?(?!\d)',result['answer'])
                assert first_temperature and first_temperature.group(1)=='38',label+': edited value not answered'
                refs=result['memory_references']
                assert any(row['id']==ident and '38' in row['content'] and '39' not in row['content'] for row in refs),label+': source not cited'
                assert result['memory_status']=='skipped',label+': recall question was saved as a new fact'
                report[label]={'answer':result['answer'],'latest_source_cited':True,'query_not_saved':True}
            assert len(client.get('/api/memories?scope=self').json()['memories'])==1,'Duplicate memory created'
            report['status']='passed'
        except Exception as exc:
            report['error']=str(exc) if isinstance(exc,AssertionError) else type(exc).__name__
        finally:
            try:
                deleted=0
                for row in client.get('/api/memories?scope=self').json()['memories']:
                    response=client.post('/api/memories/'+row['id'],json={'chat_id':chat_id,'action':'delete'})
                    assert response.status_code==200,'Cleanup failed'
                    deleted+=1
                remaining=len(client.get('/api/memories?scope=self').json()['memories'])
                report.update(test_memories_deleted=deleted,test_memories_remaining=remaining)
                if remaining: report['status']='failed'
            except Exception as exc:
                report.update(status='failed',cleanup_error=type(exc).__name__)
    Path('verification_edited_recall.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
