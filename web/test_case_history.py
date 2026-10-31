"""Cross-chat report recall uses synthetic accounts and confirmed subjects."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
from web import test_case_memory as fixtures
from web.test_case_memory import operation
from web import case_memory as store
from web.case_context import prepare_context, synchronize_index

class HistoryTests(unittest.TestCase):
    setUp = fixtures.CaseMemoryTests.setUp
    tearDown = fixtures.CaseMemoryTests.tearDown
    apply = fixtures.CaseMemoryTests.apply
    def seed_person(self, owner, chat, subject, value):
        result=self.apply([operation(value=value)],owner=owner,chat=chat)
        with store.database() as db:
            db.execute('UPDATE cases SET subject=? WHERE id=? AND owner=?',(subject,result['case_id'],owner))
        return result['case_id']

    def test_new_chat_reads_all_same_person_cases_and_excludes_others(self):
        a=self.seed_person('a','old1','self','5.0')
        b=self.seed_person('a','old2','self','6.0')
        father=self.seed_person('a','father','father','9.0')
        stranger=self.seed_person('b','other','self','11.0')
        legacy=self.seed_person('a','legacy','unknown','12.0')
        for owner,cid in [('a',father),('b',stranger),('a',legacy)]:
            synchronize_index(self.kb,store.current_facts(owner,cid))
        extractor=AsyncMock(return_value={'operations':[]})
        with patch('web.case_context.extraction_proposal',extractor):
            result=asyncio.run(prepare_context('a','new-chat','','recall','我的血糖历史','',self.kb,subject='self'))
        self.assertEqual({f['case_id'] for f in result['facts']},{a,b})
        self.assertEqual({f['case_id'] for f in extractor.call_args.args[2]},{a,b})
        self.assertEqual({f['data']['value'] for f in result['facts']},{'5.0','6.0'})
        self.assertTrue(result['index_ready'])

    def test_parent_switch_ignores_selected_self_case(self):
        own=self.seed_person('a','same-chat','self','5.0')
        dad=self.seed_person('a','dad-chat','father','8.0')
        with patch('web.case_context.extraction_proposal',AsyncMock(return_value={'operations':[]})):
            result=asyncio.run(prepare_context('a','same-chat',own,'father-read','我父亲的血糖','',self.kb,subject='father'))
        self.assertEqual(result['case_id'],dad)
        self.assertEqual([f['data']['value'] for f in result['facts']],['8.0'])
        self.assertEqual(store.bound_case('a','same-chat',dad,subject='self'),own)
        self.assertEqual(store.bound_case('a','same-chat',own,subject='unknown'),'')

    def test_correct_older_case_keeps_case_and_revision_and_rejects_other_person(self):
        old=self.seed_person('a','old','self','5.0')
        new=self.seed_person('a','new','self','6.0')
        dad=self.seed_person('a','dad','father','9.0')
        fact=store.current_facts('a',old)[0]
        foreign=store.current_facts('a',dad)[0]
        ops=[operation('correct','5.5',fact),operation('correct','8.5',foreign)]
        result=store.apply_changes('a','fresh',new,'correction',{'operations':ops},'更正为5.5，8.5','',subject='self')
        self.assertEqual(len(result['changes']),1)
        self.assertTrue(result['questions'])
        revised=store.current_facts('a',old)[0]
        self.assertEqual((revised['data']['value'],revised['revision'],revised['case_id']),('5.5',2,old))
        self.assertEqual(store.current_facts('a',dad)[0]['data']['value'],'9.0')

    def test_cross_case_reupload_deduplicates_report_identity(self):
        old=self.seed_person('a','old','self','5.0')
        new=self.seed_person('a','new','self','6.0')
        with store.database() as db:
            fact=store.current_facts('a',old)[0]
            data={**fact['data'],'report_id':'synthetic-report'}
            db.execute('UPDATE facts SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),fact['id']))
        op={'action':'add','source':'image','quote':'葡萄糖【结果】5.0','fact':data}
        result=store.apply_changes('a','new',new,'duplicate',{'operations':[op]},'',op['quote'],subject='self')
        self.assertEqual(result['changes'],[])
        self.assertEqual(len(store.history_facts('a',new,'self')),2)

    def test_unknown_case_requires_explicit_same_chat_confirmation(self):
        case=self.seed_person('a','unknown-chat','unknown','7.0')
        self.assertEqual(store.bound_case('a','other-chat',subject='self'),'')
        self.assertFalse(store.confirm_case_subject('b','unknown-chat','self'))
        self.assertTrue(store.confirm_case_subject('a','unknown-chat','self'))
        self.assertEqual(store.bound_case('a','other-chat',subject='self'),case)
        self.assertFalse(store.confirm_case_subject('a','unknown-chat','father'))
        self.assertEqual(store.require_case('a',case)['subject'],'self')
