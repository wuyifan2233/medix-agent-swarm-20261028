"""The existing account database is the source of truth for web conversations."""
import json
import time
from collections.abc import MutableMapping
from storage.business import connect


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class ChatStore:
    def require(self, owner, chat_id):
        with connect() as db:
            row = db.execute('SELECT * FROM chat_sessions WHERE owner=? AND id=?', (owner,chat_id)).fetchone()
        if row is None:
            raise LookupError('未找到会话。')
        return dict(row)

    def create_turn(self, owner, chat_id, request_id, turn_id, payload):
        now = time.time()
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id,chat_id,payload FROM chat_turns WHERE owner=? AND request_id=?',(owner,request_id)).fetchone()
            if old:
                if old['chat_id'] != chat_id or old['payload'] != dumps(payload): raise ValueError('请求编号已用于其他内容。')
                return old['id'], False
            if db.execute("SELECT 1 FROM chat_turns WHERE owner=? AND chat_id=? AND status IN ('queued','running')",(owner,chat_id)).fetchone():
                raise ValueError('当前会话正在生成，请等待完成或停止生成。')
            db.execute('INSERT OR IGNORE INTO chat_sessions(owner,id,title,created,updated,channel) VALUES(?,?,?,?,?,?)',
                       (owner,chat_id,(payload['message'] or '图片解读')[:40],now,now,payload.get('channel','web')))
            db.execute('INSERT INTO chat_turns VALUES(?,?,?,?,?,?,NULL,NULL,?,?)',
                       (turn_id,owner,chat_id,request_id,dumps(payload),'queued',now,now))
            db.execute('UPDATE chat_sessions SET updated=? WHERE owner=? AND id=?',(now,owner,chat_id))
        return turn_id, True

    def turn(self, owner, turn_id):
        with connect() as db:
            row = db.execute('SELECT * FROM chat_turns WHERE owner=? AND id=?',(owner,turn_id)).fetchone()
        if not row: raise LookupError('未找到这次分析。')
        data = dict(row)
        for key in ('payload','result'):
            data[key] = json.loads(data[key]) if data[key] else None
        return data

    def update(self, turn_id, status, result=None, error=None):
        with connect() as db:
            db.execute('UPDATE chat_turns SET status=?, result=?, error=?, updated=? WHERE id=?',
                       (status,dumps(result) if result is not None else None,error,time.time(),turn_id))

    def finish(self, turn_id, status, result, error, pending):
        # Commit the answer and the next-turn inference snapshot together.
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE chat_turns SET status=?,result=?,error=?,updated=? WHERE id=?',
                       (status,dumps(result) if result is not None else None,error,time.time(),turn_id))
            if status=='completed':
                for key,value in pending.items():
                    owner=PersistentContexts.owner(key)
                    if owner:
                        db.execute('INSERT INTO chat_contexts VALUES(?,?,?) ON CONFLICT(owner,key) DO UPDATE SET value=excluded.value',(owner,key,dumps(value)))

    def event(self, turn_id, value):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM chat_events WHERE turn_id=?',(turn_id,)).fetchone()[0]
            db.execute('INSERT INTO chat_events VALUES(?,?,?)',(turn_id,seq,dumps(value)))
        return seq

    def events(self, turn_id, after=0):
        with connect() as db:
            return [(r['seq'],json.loads(r['data'])) for r in db.execute(
                'SELECT seq,data FROM chat_events WHERE turn_id=? AND seq>? ORDER BY seq LIMIT 128',(turn_id,after))]

    def recover(self):
        with connect() as db:
            db.execute("UPDATE chat_turns SET status='interrupted',error='服务已重启，本次生成已中断；已有内容已保存。' WHERE status IN ('queued','running')")
            db.execute("UPDATE model_usage SET status='interrupted' WHERE status='running'")
            db.execute("UPDATE care_ledger SET kind='pending' WHERE kind='reserved'")

    def list(self, owner):
        with connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM chat_sessions WHERE owner=? ORDER BY updated DESC LIMIT 100',(owner,))]

    def detail(self, owner, chat_id):
        session = self.require(owner,chat_id)
        with connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM chat_turns WHERE owner=? AND chat_id=? ORDER BY created,id',(owner,chat_id))]
        session['turns'] = [self.turn(owner,tid) for tid in ids]
        return session

    def rename(self, owner, chat_id, title):
        self.require(owner,chat_id)
        with connect() as db:
            db.execute('UPDATE chat_sessions SET title=?,updated=? WHERE owner=? AND id=?',(title,time.time(),owner,chat_id))

    def delete(self, owner, chat_id):
        self.require(owner,chat_id)
        with connect() as db:
            if db.execute("SELECT 1 FROM chat_turns WHERE owner=? AND chat_id=? AND status IN ('queued','running')",(owner,chat_id)).fetchone():
                raise ValueError('请先停止此会话的生成。')
            key = f'web-{owner}-{chat_id}'
            db.execute('DELETE FROM chat_contexts WHERE owner=? AND key=?',(owner,key))
            db.execute('DELETE FROM chat_sessions WHERE owner=? AND id=?',(owner,chat_id))


class PersistentContexts(MutableMapping):
    """Write-through context snapshots; legacy test/CLI keys remain ephemeral.

    Full transcripts are separate from these bounded, privacy-filtered inference snapshots.
    """
    def __init__(self): self.cache = {}

    @staticmethod
    def owner(key):
        import uuid
        if key.startswith('web-'):
            try: return str(uuid.UUID(key[4:40]))
            except ValueError: pass
        return None

    def __getitem__(self,key):
        from core.chat_runtime import runtime
        active=runtime.get()
        if active and key in active.pending_contexts: return active.pending_contexts[key]
        if key in self.cache: return self.cache[key]
        owner = self.owner(key)
        if owner:
            with connect() as db:
                row=db.execute('SELECT value FROM chat_contexts WHERE owner=? AND key=?',(owner,key)).fetchone()
            if row:
                self.cache[key]=json.loads(row[0]); return self.cache[key]
        raise KeyError(key)

    def __setitem__(self,key,value):
        from core.chat_runtime import runtime
        active=runtime.get()
        if active:
            active.pending_contexts[key]=value
            return
        owner=self.owner(key)
        if owner:
            with connect() as db:
                db.execute('INSERT INTO chat_contexts VALUES(?,?,?) ON CONFLICT(owner,key) DO UPDATE SET value=excluded.value',(owner,key,dumps(value)))
        self.cache[key]=value

    def __delitem__(self,key):
        self[key]
        owner=self.owner(key)
        if owner:
            with connect() as db: db.execute('DELETE FROM chat_contexts WHERE owner=? AND key=?',(owner,key))
        self.cache.pop(key,None)

    def __iter__(self):
        with connect() as db: keys=[r[0] for r in db.execute('SELECT key FROM chat_contexts')]
        return iter(set(keys)|set(self.cache))

    def __len__(self): return sum(1 for _ in self)


store=ChatStore()
