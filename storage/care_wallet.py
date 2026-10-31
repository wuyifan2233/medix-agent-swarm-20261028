"""Atomic virtual credits; 1 point = 1000 ledger units, no floating point money."""
import json
import os
import time
from decimal import Decimal, ROUND_CEILING
from openai import APIError
import httpx
from storage.business import connect

class CarePointsError(APIError):
    def __init__(self):
        super().__init__('关怀点不足，暂时无法继续生成。请查看账户余额。',request=httpx.Request('POST','http://medix.local/wallet'),body=None)

def ensure(db,owner):
    initial=Decimal(os.environ.get('MEDIX_INITIAL_CARE_POINTS','10000'))
    conversion=int(os.environ.get('MEDIX_CARE_POINTS_PER_CNY','1000'))
    if not initial.is_finite() or initial<0 or conversion<=0: raise ValueError('关怀点配置无效。')
    units=int(initial*1000)
    db.execute('INSERT OR IGNORE INTO care_wallets VALUES(?,?,?,?,?)',(owner,units,units,conversion*1000,time.time()))
    db.execute("INSERT OR IGNORE INTO care_ledger(id,owner,kind,amount,created) SELECT ?,owner,'welcome',initial,created FROM care_wallets WHERE owner=?",('welcome:'+owner,owner))

def view(owner):
    with connect() as db:
        ensure(db,owner)
        row=db.execute('SELECT * FROM care_wallets WHERE owner=?',(owner,)).fetchone()
        held=db.execute('SELECT COALESCE(SUM(reserved),0) FROM care_ledger WHERE owner=?',(owner,)).fetchone()[0]
        return {'name':'关怀点','balance':row['balance']/1000,'available':max(0,row['balance']-held)/1000,
                'held':held/1000,'initial':row['initial']/1000,'points_per_cny':row['units_per_cny']/1000}

def reserve(call_id,turn_id,params,price=None):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        turn=db.execute('SELECT owner,payload FROM chat_turns WHERE id=?',(turn_id,)).fetchone()
        owner=turn['owner'];channel=json.loads(turn['payload']).get('channel','web')
        ensure(db,owner)
        row=db.execute('SELECT * FROM care_wallets WHERE owner=?',(owner,)).fetchone()
        held=db.execute('SELECT COALESCE(SUM(reserved),0) FROM care_ledger WHERE owner=?',(owner,)).fetchone()[0]
        # UTF-8 payload bytes provide a deliberately conservative input bound;
        # images are included. Peak rates protect calls crossing a time boundary.
        incoming=min(1000000,len(json.dumps(params.get('messages',[]),ensure_ascii=False).encode())+4096)
        outgoing=int(params.get('max_tokens') or 8192)
        input_rate=max(Decimal('2'),Decimal(str((price or {}).get('input',2))),Decimal(str((price or {}).get('cached_input',0))))
        output_rate=max(Decimal('8'),Decimal(str((price or {}).get('output',8))))
        maximum=(Decimal(incoming)*input_rate+Decimal(outgoing)*output_rate)/1000000
        amount=int((maximum*row['units_per_cny']).to_integral_value(rounding=ROUND_CEILING))
        if row['balance']-held<amount: raise CarePointsError()
        db.execute('INSERT INTO care_ledger(id,owner,turn_id,kind,amount,reserved,created,channel) VALUES(?,?,?,?,?,?,?,?)',
                   (call_id,owner,turn_id,'reserved',0,amount,time.time(),channel))

def settle(call_id,cost,unknown=False):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item=db.execute('SELECT * FROM care_ledger WHERE id=?',(call_id,)).fetchone()
        if not item or item['kind'] not in {'reserved','pending'}: return
        if unknown:
            db.execute("UPDATE care_ledger SET kind='pending' WHERE id=?",(call_id,));return
        row=db.execute('SELECT * FROM care_wallets WHERE owner=?',(item['owner'],)).fetchone()
        amount=int((Decimal(cost or 0)*row['units_per_cny']).to_integral_value(rounding=ROUND_CEILING))
        # Never silently forgive real consumption or allow a negative wallet.
        if amount>row['balance']: raise ValueError('实际消耗超出余额，需核对用量。')
        db.execute('UPDATE care_wallets SET balance=balance-? WHERE owner=?',(amount,item['owner']))
        db.execute("UPDATE care_ledger SET kind='debit',amount=?,reserved=0,cost_cny=? WHERE id=?",(amount,str(cost or 0),call_id))

def turn_charge(turn_id):
    with connect() as db:
        row=db.execute("SELECT COALESCE(SUM(CASE WHEN kind='debit' THEN amount ELSE 0 END),0),COALESCE(SUM(reserved),0),COUNT(*) FROM care_ledger WHERE turn_id=?",(turn_id,)).fetchone()
        return {'points':row[0]/1000,'held_points':row[1]/1000,'recorded':bool(row[2])}

def history(owner,offset=0,limit=20):
    """Page charged turns; deleted chats retain debits but no private usage data."""
    with connect() as db:
        groups=db.execute('''SELECT turn_id,MAX(created) AS latest FROM care_ledger
            WHERE owner=? AND turn_id IS NOT NULL GROUP BY turn_id
            ORDER BY latest DESC,turn_id DESC LIMIT ? OFFSET ?''',(owner,limit+1,offset)).fetchall()
        entries=[]
        for group in groups[:limit]:
            tid=group['turn_id']
            turn=db.execute('''SELECT t.status,s.title FROM chat_turns t JOIN chat_sessions s
                ON s.owner=t.owner AND s.id=t.chat_id WHERE t.id=? AND t.owner=?''',(tid,owner)).fetchone()
            rows=db.execute('''SELECT l.id,l.kind,l.amount,l.reserved,l.created,l.channel,
                u.agent,u.model,u.status,u.input_tokens,u.output_tokens,u.cache_hit_tokens,u.usage_known
                FROM care_ledger l LEFT JOIN model_usage u ON u.id=l.id AND u.turn_id=l.turn_id
                WHERE l.owner=? AND l.turn_id=? ORDER BY l.created,l.id''',(owner,tid)).fetchall()
            calls=[dict(row) for row in rows]
            for call in calls:
                call['points']=call.pop('amount')/1000
                call['held_points']=call.pop('reserved')/1000
            assistants={r['agent'] for r in rows if r['agent'] and not r['agent'].startswith('stage:')}
            entries.append({'id':tid,'title':turn['title'] if turn else '已删除的对话',
                'deleted':turn is None,'status':turn['status'] if turn else 'deleted',
                'created':rows[0]['created'],'channel':rows[0]['channel'],'points':sum(c['points'] for c in calls),
                'held_points':sum(c['held_points'] for c in calls),'requests':len(calls),
                'agent_count':len(assistants),
                'assistant_requests':sum(bool(r['agent'] in assistants) for r in rows),
                'input_tokens':sum(r['input_tokens'] or 0 for r in rows),
                'output_tokens':sum(r['output_tokens'] or 0 for r in rows),
                'cache_hit_tokens':sum(r['cache_hit_tokens'] or 0 for r in rows),
                'unknown_requests':sum(not r['usage_known'] for r in rows),'calls':calls})
        return {'entries':entries,'has_more':len(groups)>limit,'next_offset':offset+len(entries)}
