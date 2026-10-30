"""Import small Chinese question/evaluation samples, never authoritative answers."""
import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.corpus import LOCAL

DEST = LOCAL/'open_datasets'
TOPICS = ('高血压','糖尿病','鼻炎','流感','腹泻','布洛芬','对乙酰氨基酚','氯雷他定')


def get(url, **kwargs):
    response=requests.get(url,timeout=60,**kwargs)
    response.raise_for_status()
    return response


def questions_from_rows(rows):
    selected=[];seen=set()
    for wrapper in rows:
        row=wrapper['row']
        if row.get('related_diseases') not in TOPICS:continue
        # Keep only short, impersonal questions; no consultation answer is imported.
        question=re.split(r'[。！!\n]',row['question'])[-1].strip()
        question=re.sub(r'^想得到怎样的帮助[:：]','',question)
        if not 8<=len(question)<=80 or re.search(r'我|本人|自己|最近|这两年|检查|确诊|孩子|老公|妻|丈夫|爸爸|妈妈|父|母|\d+岁',question):continue
        if not any(t in question for t in TOPICS) or question in seen:continue
        seen.add(question)
        selected.append({'id':str(row['id']),'question':question,'topic':row.get('related_diseases',''),
                         'dataset':'Huatuo26M-Lite','evidence':False})
    return selected


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    dataset='FreedomIntelligence/Huatuo26M-Lite'
    revision=get('https://huggingface.co/api/datasets/'+dataset).json()['sha']
    rows=[]
    for offset in range(0,500,100):
        result=get('https://datasets-server.huggingface.co/rows',params={
            'dataset':dataset,'config':'default','split':'train','offset':offset,'length':100}).json()
        rows.extend(result['rows'])
    if get('https://huggingface.co/api/datasets/'+dataset).json()['sha']!=revision:
        raise ValueError('Dataset revision changed during sampling')
    questions=questions_from_rows(rows)[:30]
    if not questions:raise ValueError('No suitable Chinese questions found')
    repo=get('https://api.github.com/repos/FreedomIntelligence/CMB/commits/main').json()['sha']
    archive=get(f'https://raw.githubusercontent.com/FreedomIntelligence/CMB/{repo}/data/CMB.zip').content
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        name='CMB/CMB-Exam/CMB-val/CMB-val-merge.json'
        if z.getinfo(name).file_size>2_000_000:raise ValueError('Unexpected validation size')
        validation=json.loads(z.read(name))
    evaluation=[{'id':f'cmb-val-{i}',**item} for i,item in enumerate(validation)]
    # No archive extraction, no train/test answers inserted into the evidence index.
    questions_text=json.dumps(questions,ensure_ascii=False,indent=2)
    evaluation_text=json.dumps(evaluation,ensure_ascii=False,indent=2)
    manifest={'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'datasets':[
        {'id':dataset,'url':'https://huggingface.co/datasets/'+dataset,'revision':revision,
         'license':'Apache-2.0 (publisher declaration)','use':'question_exploration_only',
         'sampled_rows':len(rows),'selected_rows':len(questions),'file':'questions.json',
         'sha256':hashlib.sha256(questions_text.encode()).hexdigest()},
        {'id':'FreedomIntelligence/CMB','url':'https://github.com/FreedomIntelligence/CMB',
         'revision':repo,'license':'Apache-2.0 (dataset card)','use':'independent_evaluation_only',
         'sampled_rows':len(validation),'selected_rows':len(evaluation),'file':'evaluation.json',
         'archive_sha256':hashlib.sha256(archive).hexdigest(),
         'sha256':hashlib.sha256(evaluation_text.encode()).hexdigest()}]}
    for name,text in [('questions.json',questions_text),('evaluation.json',evaluation_text),
                      ('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))]:
        pending=DEST/(name+'.pending');pending.write_bytes(text.encode('utf8'));pending.replace(DEST/name)
    print(json.dumps({'datasets':2,'questions':len(questions),'evaluation_cases':len(evaluation)},ensure_ascii=False))


if __name__=='__main__':main()
