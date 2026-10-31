"""Background query/summary uploads, independent of local report storage."""
import json
import os
import re
from urllib.parse import quote
from .case_memory import MemoryConflict
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from loguru import logger
from .answer_summary import summarize_answer
from .web_mem0 import WebMem0Memory, Mem0Error

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mem0-exchanges')
_slots = threading.BoundedSemaphore(64)


def enabled():
    return os.environ.get('MEDIX_EXCHANGE_MEMORY','0') == '1'


class ExchangeMemory(WebMem0Memory):
    APP = 'medix-query-summary-v1'

    def list_exchanges(self, owner, scope='all'):
        people = {'all': {'self','father','mother','unknown'}, 'self': {'self'},
                  'family': {'father','mother'}, 'father': {'father'}, 'mother': {'mother'}}
        if scope not in people: raise ValueError('Invalid memory scope')
        records = []
        namespace = self.namespace(owner, 'exchanges')
        for page in range(1, 11):
            response = self._request('POST', '/v3/memories/',
                {'filters': {'user_id': namespace}}, params={'page': page, 'page_size': 100})
            for row in self._rows(response):
                meta = row.get('metadata') or {}
                if (row.get('user_id') != namespace or meta.get('owner_id') != owner
                    or meta.get('source_app') != self.APP or meta.get('kind') != 'ai_exchange'
                    or meta.get('patient', 'unknown') not in people[scope]):
                    continue
                try:
                    data = json.loads(row.get('memory', ''))
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ('query', 'answer_summary')):
                    continue
                records.append({'id': row['id'], 'query': data['query'],
                    'answer_summary': data['answer_summary'], 'patient': meta.get('patient', 'unknown'),
                    'created': meta.get('recorded_at') or row.get('created_at') or '', 'backend': 'mem0',
                    'revision': int(meta.get('revision', 0)), 'edited_at': meta.get('edited_at')})
            if not isinstance(response, dict) or not response.get('next'):
                break
        return sorted(records, key=lambda row: row['created'], reverse=True)[:100]

    def recall(self, owner, question, subject):
        # An explicit request for one's memory is not a general-knowledge question.
        inventory = bool(re.search(r'(健康记忆|长期记忆|记忆里|记住了|记得我)', question))
        if inventory and re.search(r'我|本人', question) and not re.search(r'爸|妈|父|母|他|她|亲友', question):
            subject = 'self'
        if subject not in {'self', 'father', 'mother'}:
            return [], 'not_applicable'
        if inventory:
            records = [r for r in self.list_exchanges(owner) if r['patient'] == subject]
        else:
            response = self._request('POST', '/v3/memories/search/', {
                'query': question, 'filters': {'user_id': self.namespace(owner, 'exchanges')}, 'top_k': 30})
            records = []
            for candidate in self._rows(response):
                if not candidate.get('id'): continue
                row = self.exchange_record(owner, candidate['id'])
                if not row or row['metadata'].get('patient') != subject: continue
                data = json.loads(row['memory'])
                records.append({'id': row['id'], 'query': data['query'], 'answer_summary': data['answer_summary'],
                    'patient': subject, 'created': row['metadata'].get('recorded_at', ''), 'revision': int(row['metadata'].get('revision',0)), 'edited_at': row['metadata'].get('edited_at')})
                if len(records) >= 8: break
        return [{'id': r['id'], 'content': r['query'], 'answer_summary': r['answer_summary'],
                 'patient': r['patient'], 'created': r['created'], 'backend': 'mem0',
                 'observations': '', 'topics': [], 'active': 1,
                 'revision': r.get('revision',0), 'edited_at': r.get('edited_at'), 'kind': 'user_query_and_ai_summary'} for r in records[:20]], ('available' if records else 'empty')

    def exchange_record(self, owner, memory_id):
        row = self._request('GET', '/v1/memories/' + quote(memory_id, safe='') + '/', missing_ok=True)
        if row is None: return None
        meta = row.get('metadata') or {}
        if (row.get('user_id') != self.namespace(owner, 'exchanges') or meta.get('owner_id') != owner
            or meta.get('source_app') != self.APP or meta.get('kind') != 'ai_exchange'):
            return None
        return row

    def edit_exchange(self, owner, memory_id, query, summary, expected_revision):
        row = self.exchange_record(owner, memory_id)
        if row is None: return None
        meta = row['metadata']
        if int(meta.get('revision', 0)) != expected_revision:
            raise MemoryConflict('记忆已发生变化，请重新打开后再编辑。')
        data = json.loads(row['memory'])
        data.update(query=query, answer_summary=summary)
        text = json.dumps(data, ensure_ascii=False)
        meta = dict(meta, revision=expected_revision + 1, edited_by='user', edited_at=datetime.now(timezone.utc).isoformat())
        self._settled(self._request('PUT', '/v1/memories/' + quote(memory_id, safe='') + '/', {'text': text, 'metadata': meta}))
        confirmed = self.exchange_record(owner, memory_id)
        if not confirmed or confirmed.get('memory') != text or confirmed['metadata'].get('revision') != expected_revision + 1:
            raise Mem0Error('修改尚未通过云端回读核验，请重新加载后确认。')
        return {'id': memory_id, 'query': query, 'answer_summary': summary,
            'patient': meta.get('patient', 'unknown'), 'created': meta.get('recorded_at', ''),
            'revision': expected_revision + 1, 'edited_at': meta['edited_at'], 'backend': 'mem0'}

    def delete_exchange(self, owner, memory_id, expected_revision):
        row = self.exchange_record(owner, memory_id)
        if row is None: return False
        if int(row['metadata'].get('revision', 0)) != expected_revision:
            raise MemoryConflict('记忆已发生变化，请重新打开后再操作。')
        self._settled(self._request('DELETE', '/v1/memories/' + quote(memory_id, safe='') + '/'))
        if self._request('GET', '/v1/memories/' + quote(memory_id, safe='') + '/', missing_ok=True) is not None:
            raise Mem0Error('删除尚未通过云端核验，请重新加载后确认。')
        return True

    def save_exchange(self, owner, chat_id, request_id, query, summary, subject='unknown'):
        namespace=self.namespace(owner,'exchanges')
        text=json.dumps({'request_id':request_id,'query':query,'answer_summary':summary},ensure_ascii=False)
        meta={'source_app':self.APP,'owner_id':owner,'kind':'ai_exchange','request_id':request_id,
              'session_id':chat_id,'patient':subject,'recorded_at':datetime.now(timezone.utc).isoformat()}
        response=self._settled(self._request('POST','/v3/memories/add/',{
            'user_id':namespace,'run_id':chat_id,'messages':[{'role':'user','content':text}],
            'infer':False,'metadata':meta}))
        ids=[r.get('id') for r in self._rows(response) if r.get('id')]
        if len(ids)!=1:raise Mem0Error('Mem0 未返回唯一问答记录编号，保存尚未确认。')
        row=self._request('GET',f'/v1/memories/{ids[0]}/')
        stored=row.get('metadata') or {}
        if (row.get('user_id')!=namespace or row.get('memory')!=text
            or any(stored.get(k)!=meta[k] for k in ('source_app','owner_id','request_id','kind'))):
            raise Mem0Error('Mem0 问答原文与摘要回读未通过。')
        return ids[0]


def _upload(data):
    try:
        for attempt in range(3):
            try:
                store = ExchangeMemory()
                normalized = lambda text: re.sub(r'[\s，。！？、,.!?；;：:]', '', text)
                existing = store.list_exchanges(data['owner'])
                if any(row['patient'] == data['subject'] and normalized(row['query']) == normalized(data['query']) for row in existing):
                    return
                store.save_exchange(**data)
                logger.info('Mem0 exchange saved and verified (request={})',data['request_id'])
                return
            except Exception as exc:
                # Provider errors, queries and medical answers must not enter logs.
                if attempt==2:
                    logger.warning('Mem0 exchange upload unconfirmed (request={}, error={})',data['request_id'],type(exc).__name__)
                else:
                    time.sleep(attempt+1)
    finally:
        _slots.release()


def submit_exchange(payload, result):
    """Called only for a newly completed turn, after its done event is published.

    No historical scan or report upload. A bounded, best-effort background queue
    keeps Mem0 latency out of the chat worker; failures remain server-side.
    """
    if not enabled() or not payload.get('owner') or not result.get('answer'):
        return
    decision = result.get('patient_resolution') or {}
    # Reuse the existing model classification; no extra blocking model call.
    # Missing/failed classification must never default to saving every exchange.
    if (decision.get('should_store') is not True or decision.get('long_term_value') is not True
        or decision.get('subject') not in {'self', 'father', 'mother'}
        or not decision.get('memory_evidence')
        or decision['memory_evidence'] not in payload.get('message', '')):
        return
    data={'owner':payload['owner'],'chat_id':payload['chat_id'],'request_id':payload['request_id'],
          'query':payload.get('message',''),'summary':summarize_answer(result['answer']),
          'subject':result.get('patient_resolution',{}).get('subject','unknown')}
    if not _slots.acquire(blocking=False):
        logger.warning('Mem0 exchange queue full (request={})',data['request_id'])
        return
    try:
        _pool.submit(_upload,data)
    except Exception:
        _slots.release()
        logger.warning('Mem0 exchange enqueue failed (request={})',data['request_id'])
