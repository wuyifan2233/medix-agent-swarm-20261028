"""Live subject-resolution check with synthetic sentences; no Mem0 operations."""
import asyncio
import json
from pathlib import Path
from loguru import logger
from memory.patient_resolver import resolve_patient

async def main():
    logger.remove()
    previous={'patient':'father','history':[{'role':'user','content':'我爸最近三天睡眠不好'}]}
    pending={'patient':None,'awaiting_patient_confirmation':True,'history':[{'role':'user','content':'最近头晕三天了'}]}
    fixtures=[
        ('colloquial','家里老爷子最近睡不着',{},'father'),
        ('followup','持续三天了',previous,'father'),
        ('switch','我自己今天也有点头晕',previous,'self'),
        ('ambiguous','他最近头晕',{},'unknown'),
        ('general','高血压是什么？',{},'general'),
        ('multiple','我和爸爸最近都头晕，帮我们一起看看',{},'multiple'),
        ('confirmation','是我爸爸的情况',pending,'father')]
    checks=[]
    for name,question,context,expected in fixtures:
        result=await resolve_patient(question,context)
        checks.append({'case':name,'expected':expected,'actual':result['subject'],
                       'passed':result['subject']==expected and (name!='confirmation' or result['confirms_previous'])})
    output={'status':'passed' if all(c['passed'] for c in checks) else 'failed','checks':checks}
    Path('verification_patient_resolver.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False),flush=True)
    return 0 if output['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(asyncio.run(main()))
