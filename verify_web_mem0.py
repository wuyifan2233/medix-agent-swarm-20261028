"""Real Mem0 web-adapter check, scoped to disposable synthetic users only."""
import json
import tempfile
import time
import uuid
from pathlib import Path
from loguru import logger
from memory.case_memory import CaseMemory, memory_context, referenced, MemoryConflict
from memory.web_mem0 import WebMem0Memory, Mem0Error


def main():
    logger.remove()
    owner = 'medix-web-verification-' + uuid.uuid4().hex
    result = {'check':'web_mem0_roundtrip', 'test_user':owner, 'status':'failed'}
    with tempfile.TemporaryDirectory() as directory:
        store = WebMem0Memory(CaseMemory(Path(directory)/'source-a.db'))
        try:
            ident = store.save(owner, 'synthetic-previous', '功能测试的虚构描述：我最近三天晚上头晕，准备记录时间。')
            family = store.save(owner, 'synthetic-father', '功能测试的虚构描述：我父亲最近血压偏高，正在记录家庭血压。', 'father')
            mother = store.save(owner, 'synthetic-mother', '虚构功能测试：我母亲今天有点感冒，想咨询日常照护。', 'mother')
            result.update(write_verified=bool(ident and family and mother))
            fresh = WebMem0Memory(CaseMemory(Path(directory)/'source-b.db'))
            matches = []
            for _ in range(6):
                matches = fresh.related(owner, 'synthetic-new', '我今天白天也头晕', 'self')
                if any(row['id'] == ident for row in matches): break
                time.sleep(2)
            assert any(row['id']==ident and row['backend']=='mem0' for row in matches), 'Cross-session search did not find the cloud record'
            result['cross_session_search'] = True
            assert not fresh.related(owner, 'synthetic-new', '我今天白天也头晕', 'father'), 'Patient scope leaked'
            assert not fresh.related(owner+'-stranger', 'synthetic-new', '我今天白天也头晕', 'self'), 'Owner scope leaked'
            result['patient_and_owner_isolation'] = True
            people = fresh.list(owner, include_inactive=True, scope='family')
            assert len(people)==2 and {row['patient'] for row in people}=={'father','mother'}
            mother_row=next(row for row in people if row['patient']=='mother')
            assert mother_row['id']==mother and '感冒' in mother_row['topics']
            result['mother_cold_saved'] = True
            result['family_grouping'] = True
            updated = fresh.update(owner,mother,'虚构功能测试（用户更正）：我母亲最近睡眠不好。','',mother_row['revision'])
            assert updated['id']==mother and updated['patient']=='mother' and updated['revision']==1
            assert '睡眠' in updated['topics'] and '感冒' not in updated['topics']
            assert updated['content']=='虚构功能测试（用户更正）：我母亲最近睡眠不好。'
            assert len(fresh.list(owner,include_inactive=True,scope='family'))==2
            reread = fresh._get(owner,mother)
            assert reread['memory']==updated['content']
            try:
                fresh.update(owner,mother,'虚构的过期覆盖','',0)
                raise AssertionError('Stale edit was not rejected')
            except MemoryConflict: pass
            result['edit_same_id_readback_no_duplicate'] = True
            result['stale_edit_rejected'] = True
            refs = memory_context(matches)
            answer, used = referenced('参考之前的头晕记录 [M1]。', refs)
            assert used and used[0]['content'].startswith('功能测试') and used[0].get('highlight_terms')
            result['original_and_highlight_data'] = True
            assert fresh.change(owner, ident, 'exclude', 'synthetic-new')
            assert not fresh.related(owner, 'synthetic-new', '我今天也头晕', 'self')
            result['exclude_verified'] = True
            assert not fresh.change(owner+'-stranger', ident, 'delete')
            assert fresh.change(owner, ident, 'retire')
            assert not fresh.related(owner, 'synthetic-after-retire', '我今天也头晕', 'self')
            result['retire_verified'] = True
            result['status'] = 'passed'
        except Exception as exc:
            result['error_type'] = type(exc).__name__
            result['error'] = str(exc) if isinstance(exc, (Mem0Error, AssertionError)) else 'Verification failed; inspect adapter without printing provider credentials.'
        finally:
            try:
                deleted = 0
                for person in ('self','father','mother'):
                    for row in store.cloud_list(owner, person, include_inactive=True):
                        store.change(owner, row['id'], 'delete'); deleted += 1
                remaining = sum(len(store.cloud_list(owner, person, include_inactive=True)) for person in ('self','father','mother'))
                result.update(test_memories_deleted=deleted, test_memories_remaining=remaining)
                if remaining: result.update(status='failed',cleanup_error='Synthetic records remain')
            except Exception as exc:
                result.update(status='failed', cleanup_error=type(exc).__name__)
    Path('verification_web_mem0.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__': raise SystemExit(main())
