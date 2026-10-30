import unittest
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from personalization.conversation_updates import Fact,review_facts
from personalization.test_evolution import EvolutionTests


def fact(evidence,**changes):
    return Fact.model_validate(dict(field='symptoms',value={'name':'头痛','status':'reported'},evidence=evidence,
                                    uncertain=False,subject='self',assertion='affirmed',basis='self_report',**changes))


class ConversationGuards(unittest.TestCase):
    def test_self_report_is_not_diagnosis(self):
        candidates,questions=review_facts('我这两天头痛',[fact('我这两天头痛')])
        self.assertEqual(candidates[0]['field'],'symptoms')
        self.assertEqual(candidates[0]['source']['kind'],'conversation')
        self.assertIn('未经医学核实',candidates[0]['source']['label'])
        self.assertEqual(questions,[])

    def test_other_hypothetical_and_negative_are_excluded_even_if_model_is_wrong(self):
        for text in ['我父亲最近头痛','假如我头痛怎么办','我没有头痛','我朋友说他头痛']:
            candidates,_=review_facts(text,[fact(text)])
            self.assertEqual(candidates,[])

    def test_unknown_subject_and_inferred_diagnosis_need_clarification(self):
        candidate=fact('最近头痛');candidate.subject='unknown'
        result,questions=review_facts('最近头痛',[candidate]);self.assertEqual(result,[]);self.assertTrue(questions)
        candidate=fact('我头痛可能是高血压');candidate.field='conditions'
        result,questions=review_facts(candidate.evidence,[candidate]);self.assertEqual(result,[]);self.assertTrue(questions)

    def test_suspected_self_report_stays_uncertain(self):
        result,_=review_facts('我好像对牛奶过敏',[fact('我好像对牛奶过敏')])
        self.assertTrue(result[0]['uncertain']);self.assertEqual(result[0]['value']['status'],'unknown')

    def test_fabricated_evidence_is_rejected(self):
        with self.assertRaises(HTTPException):review_facts('我只是来咨询',[fact('我头痛')])

    def test_model_cannot_set_persisted_status_or_source(self):
        candidate=Fact.model_validate({'field':'symptoms','value':{'name':'头痛','status':'hypothetical'},
            'evidence':'假如我头痛','uncertain':False,'subject':'self','assertion':'hypothetical','basis':'self_report'})
        candidates,_=review_facts('假如我头痛',[candidate])
        self.assertEqual(candidates,[])


class ConversationAPI(unittest.TestCase):
    setUp=EvolutionTests.setUp
    tearDown=EvolutionTests.tearDown
    client_for=EvolutionTests.client_for

    def test_conversation_update_requires_consent_and_produces_draft_only(self):
        payload={'text':'我这两天头痛','subject':'self','consent_to_model':False,'expected_revision':0}
        self.assertEqual(self.client.post('/api/profile/conversation-candidates',json=payload).status_code,422)
        payload['consent_to_model']=True
        with patch('personalization.conversation_updates.assess',AsyncMock(return_value=[fact(payload['text'])])):
            response=self.client.post('/api/profile/conversation-candidates',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        batch=response.json();self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
        selection={'candidate_id':batch['candidates'][0]['id'],'action':'append'}
        path='/api/profile/imports/'+batch['id']+'/apply'
        self.assertEqual(self.other.post(path,json={'expected_revision':0,'selections':[selection]}).status_code,404)
        response=self.client.post(path,json={'expected_revision':0,'selections':[selection]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['usable'])
        self.assertEqual(response.json()['data']['symptoms']['items'][0]['name'],'头痛')


if __name__=='__main__':unittest.main()


class AssistantNoteGuards(unittest.TestCase):
    def test_answer_can_only_be_saved_as_separate_uncertain_note(self):
        answer='建议记录头痛持续时间，并在持续不适时就医。'
        item=fact(answer);item.field='followups'
        candidates,_=review_facts('我头痛',[item],answer)
        note=candidates[0]
        self.assertEqual(note['field'],'followups')
        self.assertEqual(note['source']['kind'],'assistant')
        self.assertEqual(note['value']['status'],'unknown')
        self.assertTrue(note['uncertain'])
        item.field='conditions'
        with self.assertRaises(HTTPException):review_facts('我头痛',[item],answer)
        item.field='followups'
        with self.assertRaises(HTTPException):review_facts('我头痛',[item],'另一条回答')


class AssistantNoteAPI(ConversationAPI):
    def test_answer_ownership_selection_and_draft(self):
        from web.app import jobs
        text='我这两天头痛';answer='建议记录头痛持续时间。';item=fact(answer);item.field='followups'
        jobs['note-test']={'owner_user_id':self.a.id,'request_text':text,'status':'completed','result':{'answer':answer}}
        payload={'text':text,'job_id':'note-test','subject':'self','consent_to_model':True,'expected_revision':0}
        try:
            self.assertEqual(self.other.post('/api/profile/conversation-candidates',json=payload).status_code,404)
            with patch('personalization.conversation_updates.assess',AsyncMock(return_value=[item])) as model:
                result=self.client.post('/api/profile/conversation-candidates',json=payload)
                model.assert_awaited_once_with(text,answer)
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual(self.client.get('/api/profile').json()['revision'],0)
            batch=result.json();selection={'candidate_id':batch['candidates'][0]['id'],'action':'append'}
            path='/api/profile/imports/'+batch['id']+'/apply'
            self.assertEqual(self.client.post(path,json={'expected_revision':0,'selections':[selection]}).status_code,422)
            selection['acknowledge_uncertainty']=True
            saved=self.client.post(path,json={'expected_revision':0,'selections':[selection]})
            self.assertEqual(saved.status_code,200,saved.text)
            data=saved.json();self.assertFalse(data['usable'])
            self.assertEqual(data['data']['conditions']['items'],[])
            self.assertEqual(data['data']['medications']['items'],[])
            self.assertEqual(data['data']['followups']['items'][0]['source']['kind'],'assistant')
            payload['text']='不匹配'
            self.assertEqual(self.client.post('/api/profile/conversation-candidates',json=payload).status_code,409)
        finally:jobs.pop('note-test',None)
