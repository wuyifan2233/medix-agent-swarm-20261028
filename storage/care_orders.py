"""Unpaid recharge intents. No payment callback or balance-credit API is exposed."""
import time
import uuid
from storage.business import connect
from storage.care_wallet import ensure

PLANS = {'light': ('轻量关怀', 1000), 'daily': ('日常陪伴', 3000), 'lasting': ('长久安心', 10000)}


def catalog(owner):
    with connect() as db:
        ensure(db,owner)
        ratio=db.execute('SELECT units_per_cny FROM care_wallets WHERE owner=?',(owner,)).fetchone()[0]
    return {'payment_enabled':False,'plans':[{'id':key,'name':name,'amount_fen':fen,
        'points':fen*ratio//100/1000,'currency':'CNY'} for key,(name,fen) in PLANS.items()]}


def expire(db,owner,now):
    db.execute("UPDATE care_orders SET status='expired',updated=? WHERE owner=? AND status='awaiting_payment' AND expires<=?",(now,owner,now))


def public(row):
    result=dict(row);result.pop('owner');result.pop('request_id')
    result['points']/=1000;result['payment_enabled']=False
    result['plan_name']=PLANS[result['plan_id']][0]
    return result


def create(owner,plan_id,request_id):
    if plan_id not in PLANS: raise ValueError('请选择有效的充值档位。')
    request_id=str(uuid.UUID(str(request_id)))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE');ensure(db,owner);now=time.time();expire(db,owner,now)
        old=db.execute('SELECT * FROM care_orders WHERE owner=? AND request_id=?',(owner,request_id)).fetchone()
        if old:
            if old['plan_id'] != plan_id: raise ValueError('该请求编号已用于其他充值档位。')
            return public(old)
        count=db.execute("SELECT COUNT(*) FROM care_orders WHERE owner=? AND status='awaiting_payment'",(owner,)).fetchone()[0]
        if count>=5: raise ValueError('已有5笔待支付订单，请先取消不需要的订单。')
        ratio=db.execute('SELECT units_per_cny FROM care_wallets WHERE owner=?',(owner,)).fetchone()[0]
        fen=PLANS[plan_id][1];ident=uuid.uuid4().hex
        db.execute('''INSERT INTO care_orders(id,owner,request_id,plan_id,points,amount_fen,status,created,expires,updated)
            VALUES(?,?,?,?,?,?,'awaiting_payment',?,?,?)''',(ident,owner,request_id,plan_id,fen*ratio//100,fen,now,now+86400,now))
        return public(db.execute('SELECT * FROM care_orders WHERE id=?',(ident,)).fetchone())


def list_orders(owner,offset=0,limit=20):
    with connect() as db:
        expire(db,owner,time.time())
        rows=db.execute('SELECT * FROM care_orders WHERE owner=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',(owner,limit+1,offset)).fetchall()
        return {'orders':[public(row) for row in rows[:limit]],'has_more':len(rows)>limit,'next_offset':offset+min(len(rows),limit)}


def cancel(owner,order_id):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE');expire(db,owner,time.time())
        row=db.execute('SELECT * FROM care_orders WHERE id=? AND owner=?',(order_id,owner)).fetchone()
        if not row: raise LookupError('未找到充值订单。')
        if row['status']=='awaiting_payment':
            db.execute("UPDATE care_orders SET status='cancelled',updated=? WHERE id=? AND owner=?",(time.time(),order_id,owner))
        return public(db.execute('SELECT * FROM care_orders WHERE id=? AND owner=?',(order_id,owner)).fetchone())
