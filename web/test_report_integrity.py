import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from web import case_memory as store
from web.case_context import extraction_proposal,prepare_context,propose_changes
from web.report_identity import deduplicate,report_rows

class IntegrityTests(unittest.TestCase):
    def test_chinese_date_and_prefixed_name_keep_old_record(self):
        facts=[{'data':{'name':'尿酸','date':'2026-10-30'}},{'data':{'name':'Ua 尿酸','date':'2018-05-22'}}]
        self.assertIn(facts[1],store.related_facts(facts,'2018年5月22日的尿酸从480改成460'))

    def test_overlap_formatting_and_conflicting_values(self):
        a={'name':'Ua 尿酸','result':'360','unit':'umol/L','reference':'155~428','quote':'a'}
        b=dict(a,name='尿酸',reference='155～428',quote='b')
        rows,conflicts=deduplicate([a,b])
        self.assertEqual(len(rows),1);self.assertFalse(conflicts)
        rows,conflicts=deduplicate([a,dict(b,result='380')])
        self.assertFalse(rows);self.assertTrue(conflicts)

    def observed(self,date='2026-10-30',ident='a'):
        return '【图片 1】\n【报告标识 '+ident*64+'】\n'+date+'\nUa 尿酸【结果】360【单位】umol/L【参考】155~428'

    def test_image_date_not_dependent_on_extractor(self):
        with patch('web.case_context.propose_changes',AsyncMock(return_value={'operations':[]})):
            result=asyncio.run(extraction_proposal('看看',self.observed(),[]))
        self.assertEqual(len(result['operations']),1)
        self.assertEqual(result['operations'][0]['fact']['date'],'2026-10-30')

    def test_unknown_or_ambiguous_date_is_not_invented(self):
        for dates in ('','2026-10-30 和 2026-10-29'):
            self.assertEqual(list(report_rows(self.observed(dates)))[0][1]['date'],'')

    def test_reupload_keeps_correction_and_new_report_same_value_is_new(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DB_PATH',Path(tmp)/'db.sqlite'):
            line,fact=list(report_rows(self.observed()))[0]
            proposal={'operations':[{'action':'add','source':'image','quote':line,'fact':fact}]}
            saved=store.apply_changes('a','chat','','1',proposal,'',self.observed())
            case=saved['case_id'];old=store.current_facts('a',case)[0]
            store.apply_changes('a','chat',case,'2',{'operations':[{'action':'correct','source':'user','quote':'尿酸应为350','target_id':old['id'],'expected_revision':1,'fact':{'value':'350'}}]},'尿酸应为350','')
            store.apply_changes('a','chat',case,'3',proposal,'',self.observed())
            self.assertEqual(len(store.current_facts('a',case)),1)
            self.assertEqual(store.current_facts('a',case)[0]['data']['value'],'350')
            line,fact=list(report_rows(self.observed('2026-11-01','b')))[0]
            store.apply_changes('a','chat',case,'4',{'operations':[{'action':'add','source':'image','quote':line,'fact':fact}]},'',self.observed('2026-11-01','b'))
            self.assertEqual(len(store.current_facts('a',case)),2)

    def test_question_objects_normalized_at_boundary(self):
        class Client:
            client=SimpleNamespace(close=AsyncMock())
            chat=AsyncMock(return_value=json.dumps({'operations':[],'questions':[{'question':'请核对日期'}]}))
        with patch('core.LLMClient',Client):
            result=asyncio.run(propose_changes('纠错','',[]))
        self.assertEqual(result['questions'],['请核对日期'])

    def test_old_same_value_does_not_satisfy_current_report_coverage(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'DB_PATH',Path(tmp)/'db.sqlite'):
            line,fact=list(report_rows(self.observed('2018-05-22','b')))[0]
            saved=store.apply_changes('a','chat','','old',{'operations':[{'action':'add','source':'image','quote':line,'fact':fact}]},'',self.observed('2018-05-22','b'))
            with patch('web.case_context.extraction_proposal',AsyncMock(return_value={'operations':[]})):
                result=asyncio.run(prepare_context('a','chat',saved['case_id'],'new','看看',self.observed(),object()))
            self.assertEqual(result['extraction_check']['unmatched_rows'],1)
