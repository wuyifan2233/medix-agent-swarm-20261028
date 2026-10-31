"""Background query/summary uploads, independent of local report storage."""
import json
import os
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
                ExchangeMemory().save_exchange(**data)
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
