"""Request-scoped streaming and provider-reported usage, including cancelled calls."""
import asyncio
import json
import os
import time
import uuid
from contextvars import ContextVar
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace as NS

from storage.business import connect
from storage.chat import store, dumps

runtime = ContextVar('chat_runtime', default=None)


from core.token_pricing import price_for
from storage import care_wallet


def usage_values(usage, price):
    if usage is None: return None
    def get(key, default=None):
        return usage.get(key,default) if isinstance(usage,dict) else getattr(usage,key,default)
    incoming, outgoing = get('prompt_tokens'),get('completion_tokens')
    if type(incoming) is not int or type(outgoing) is not int or min(incoming,outgoing)<0: return None
    hit = get('prompt_cache_hit_tokens')
    if hit is None:
        details=get('prompt_tokens_details')
        hit=(details.get('cached_tokens',0) if isinstance(details,dict) else getattr(details,'cached_tokens',0)) if details else 0
    if type(hit) is not int or not 0 <= hit <= incoming: return None
    cost = None
    if price:
        cost = str((Decimal(incoming-hit)*Decimal(str(price['input']))+
                    Decimal(hit)*Decimal(str(price['cached_input']))+
                    Decimal(outgoing)*Decimal(str(price['output'])))/Decimal(1000000))
    return incoming,outgoing,hit,cost


def usage_summary(turn_id):
    with connect() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM model_usage WHERE turn_id=? ORDER BY created,id',(turn_id,))]
    # Old USD estimates remain in the audit row; show a CNY reference estimate,
    # without retroactively charging conversations predating the wallet.
    for row in rows:
        saved=json.loads(row['price'])
        if saved.get('currency')=='USD' and row['usage_known']:
            from datetime import datetime, timezone
            cny=price_for(row['model'],datetime.fromtimestamp(row['created'],timezone.utc))
            values=usage_values({'prompt_tokens':row['input_tokens'],'completion_tokens':row['output_tokens'],'prompt_cache_hit_tokens':row['cache_hit_tokens']},cny)
            row['cost']=values[3];row['price']=dumps(cny or {})
    known=[r for r in rows if r['usage_known']]
    currencies={json.loads(r['price']).get('currency') for r in known if r['cost'] is not None}
    cost=str(sum((Decimal(r['cost']) for r in known if r['cost'] is not None),Decimal(0))) if len(currencies)==1 else None
    searches = [r for r in rows if json.loads(r['price']).get('service') == 'search']
    return {'charge':care_wallet.turn_charge(turn_id),'requests':len(rows)-len(searches),'search_requests':len(searches),'agents':sorted({r['agent'] for r in rows}),
            'input_tokens':sum(r['input_tokens'] for r in known),'output_tokens':sum(r['output_tokens'] for r in known),
            'cache_hit_tokens':sum(r['cache_hit_tokens'] for r in known),
            'unknown_requests':len(rows)-len(known),'estimated_cost':cost,
            'agent_count':len({r['agent'] for r in rows if not r['agent'].startswith('stage:')}),
            'currency':next(iter(currencies)) if len(currencies)==1 else None,
            'unpriced_requests':sum(r['cost'] is None for r in known),
            'calls':[{k:r[k] for k in ('id','agent','model','status','input_tokens','output_tokens','cache_hit_tokens','usage_known','cost','created','updated')} | {'price':json.loads(r['price']), 'usage_kind':'search' if r in searches else 'model'} for r in rows]}


def aggregate_usage(owner, chat_id=None):
    with connect() as db:
        query='SELECT id FROM chat_turns WHERE owner=?'; args=[owner]
        if chat_id is not None: query+=' AND chat_id=?';args.append(chat_id)
        ids=[r[0] for r in db.execute(query,args)]
    summaries=[usage_summary(tid) for tid in ids]
    result={key:sum(row[key] for row in summaries) for key in ('requests','search_requests','input_tokens','output_tokens','cache_hit_tokens','unknown_requests','unpriced_requests')}
    currencies={r['currency'] for r in summaries if r['estimated_cost'] is not None}
    result.update(agents=sorted({agent for row in summaries for agent in row['agents']}),
                  agent_count=len({agent for row in summaries for agent in row['agents'] if not agent.startswith('stage:')}),
                  currency=next(iter(currencies)) if len(currencies)==1 else None,
                  estimated_cost=str(sum((Decimal(r['estimated_cost']) for r in summaries if r['estimated_cost'] is not None),Decimal(0))) if len(currencies)==1 else None)
    return result


class ChatRuntime:
    def __init__(self, turn_id): self.turn_id=turn_id; self.stage='initial'; self.pending_contexts={}
    def emit(self, kind, **data): store.event(self.turn_id, {'type':kind,**data})


@asynccontextmanager
async def service_usage(model, price):
    """Record fixed-price calls with the same owner, reservation and cancellation rules."""
    receipt = NS(cost=None, price=price)
    active = runtime.get()
    if active is None:
        yield receipt
        return
    call_id = uuid.uuid4().hex
    care_wallet.reserve(call_id, active.turn_id, {}, price)
    try:
        with connect() as db:
            db.execute('INSERT INTO model_usage(id,turn_id,agent,model,status,price,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (call_id, active.turn_id, 'stage:search', model, 'running', dumps(price), time.time(), time.time()))
    except Exception:
        care_wallet.settle(call_id, '0')
        raise
    state = 'failed'
    try:
        yield receipt
        state = 'completed'
    except asyncio.CancelledError:
        state = 'cancelled'
        raise
    finally:
        known = receipt.cost is not None
        care_wallet.settle(call_id, receipt.cost, unknown=not known)
        with connect() as db:
            db.execute('UPDATE model_usage SET status=?,input_tokens=?,output_tokens=?,cache_hit_tokens=?,usage_known=?,cost=?,updated=? WHERE id=?',
                       (state, 0 if known else None, 0 if known else None, 0 if known else None,
                        int(known), receipt.cost, time.time(), call_id))
        active.emit('usage', usage=usage_summary(active.turn_id))


async def completion(client, params, *, visible=False, agent='system', transform=None):
    """Preserve the SDK response contract outside managed web jobs.

    In a web job every HTTP attempt is explicit (SDK retries disabled), stream chunks
    are assembled by tool-call index, and reasoning stays exclusively in memory.
    """
    active=runtime.get()
    if active is None: return await client.chat.completions.create(**params)
    call_id=uuid.uuid4().hex
    if agent=='system': agent='stage:'+active.stage
    model=params['model']; price=price_for(model)
    if not price: raise ValueError('请先为此模型配置人民币计费单价。')
    care_wallet.reserve(call_id,active.turn_id,params,price)
    with connect() as db:
        db.execute('INSERT INTO model_usage(id,turn_id,agent,model,status,price,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                   (call_id,active.turn_id,agent,model,'running',dumps(price or {}),time.time(),time.time()))
    if visible: active.emit('draft_start', agent=agent, call_id=call_id)
    stream=None; usage=None; state='failed'; content=''; reasoning=''; tools={}; finish=None
    pending=''; last=time.monotonic(); rendered=''; rejected=False
    try:
        options={**params,'stream':True,'stream_options':{'include_usage':True}}
        stream=await client.with_options(max_retries=0).chat.completions.create(**options)
        async for chunk in stream:
            if getattr(chunk,'usage',None) is not None: usage=chunk.usage
            for choice in chunk.choices:
                if choice.index != 0: continue
                delta=choice.delta
                if choice.finish_reason: finish=choice.finish_reason
                if getattr(delta,'reasoning_content',None): reasoning+=delta.reasoning_content
                if delta.content:
                    content+=delta.content
                    if visible:
                        shown=transform(content) if transform else content
                        if shown.startswith(rendered): pending+=shown[len(rendered):]
                        rendered=shown
                for tc in delta.tool_calls or []:
                    target=tools.setdefault(tc.index, {'id':'','name':'','arguments':''})
                    if tc.id: target['id']+=tc.id
                    if tc.function:
                        if tc.function.name: target['name']+=tc.function.name
                        if tc.function.arguments: target['arguments']+=tc.function.arguments
            if visible and pending and (time.monotonic()-last>=0.15 or len(pending)>=256):
                active.emit('delta', text=pending,call_id=call_id); pending=''; last=time.monotonic()
        if finish is None: raise ValueError('模型输出流意外结束。')
        state='completed'
        message=NS(content=content or None,reasoning_content=reasoning or None,
                   tool_calls=[NS(id=t['id'],type='function',function=NS(name=t['name'],arguments=t['arguments'])) for _,t in sorted(tools.items())])
        return NS(choices=[NS(message=message,finish_reason=finish)],usage=usage)
    except asyncio.CancelledError:
        state='cancelled'; raise
    except Exception as exc:
        from openai import APIStatusError
        rejected=isinstance(exc,APIStatusError) and exc.status_code in {400,401,403,404,422,429}
        raise
    finally:
        if visible and pending: active.emit('delta',text=pending,call_id=call_id)
        if visible and tools: active.emit('draft_clear',call_id=call_id)
        try:
            if stream is not None: await stream.close()
        finally:
            values=(0,0,0,'0') if rejected else usage_values(usage,price)
            care_wallet.settle(call_id,values[3] if values else None,unknown=values is None)
            with connect() as db:
                db.execute('UPDATE model_usage SET status=?,input_tokens=?,output_tokens=?,cache_hit_tokens=?,usage_known=?,cost=?,updated=? WHERE id=?',
                           (state,*(values[:3] if values else (None,None,None)),int(values is not None),values[3] if values else None,time.time(),call_id))
            active.emit('usage',usage=usage_summary(active.turn_id))
