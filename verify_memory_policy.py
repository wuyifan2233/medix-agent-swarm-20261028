"""Live model checks with fictional fixtures only; never writes to Mem0."""
import asyncio
import json
from pathlib import Path
from loguru import logger
from memory.patient_resolver import resolve_patient


async def main():
    logger.remove()
    previous={'patient':'mother','history':[{'role':'user','content':'我妈妈最近鼻塞两天'}]}
    fixtures=[
        ('new_health_fact','我妈妈最近鼻塞两天，今天开始咳嗽。',{},True),
        ('greeting','谢谢你的帮助',{},False),
        ('general','感冒是什么，通常有哪些表现？',{},False),
        ('hypothetical','假如我妈妈以后感冒，可以怎么照护？现在她没有这些症状。',{},False),
        ('advice_only','那我妈妈应该注意什么？',previous,False),
        ('do_not_store','虚构功能测试：我妈妈最近鼻塞两天，但不要保存或记住这次信息。',{},False)]
    async def check(fixture):
        name,question,history,expected=fixture
        result=await resolve_patient(question,history)
        return dict(case=name,expected=expected,actual=result['should_store'],subject=result['subject'],
                    reason=result['memory_reason'],passed=result['should_store']==expected and result['method']=='model')
    checks=[]
    for fixture in fixtures:
        checks.append(await check(fixture))
    output={'status':'passed' if all(row['passed'] for row in checks) else 'failed','checks':checks}
    Path('verification_memory_policy.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False),flush=True)
    return 0 if output['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(asyncio.run(main()))
