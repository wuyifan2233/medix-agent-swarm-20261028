import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from memory.patient_resolver import resolve_patient, validate_resolution


class PatientResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_handles_colloquial_relation(self):
        client=SimpleNamespace(chat=AsyncMock(return_value='{"subject":"father","confidence":0.98,"evidence":"老爷子","basis":"current"}'))
        result=await resolve_patient('家里老爷子最近睡不着',client=client)
        self.assertEqual(result['patient'],'father')
        self.assertFalse(result['needs_confirmation'])
        client.chat.assert_awaited_once()

    async def test_followup_inherits_only_same_chat_confirmed_person(self):
        previous={'patient':'mother','history':[{'role':'user','content':'我妈最近头晕'}]}
        client=SimpleNamespace(chat=AsyncMock(return_value='{"subject":"mother","confidence":0.95,"evidence":"我妈","basis":"history"}'))
        self.assertEqual((await resolve_patient('持续三天了',previous,client=client))['patient'],'mother')
        self.assertEqual((await resolve_patient('她还头晕',client=client))['subject'],'unknown')

    async def test_low_confidence_and_invalid_response_do_not_default_to_self(self):
        for raw in ['not-json','{"subject":"father","confidence":0.4,"evidence":"爸爸"}', '{"subject":"father","confidence":0.99,"evidence":"编造的称呼"}']:
            client=SimpleNamespace(chat=AsyncMock(return_value=raw))
            self.assertEqual((await resolve_patient('爸爸头晕',client=client))['patient'],'other')
        client=SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError('provider-error')))
        result=await resolve_patient('我头晕',client=client)
        self.assertEqual(result['subject'],'unknown')
        self.assertEqual(result['method'],'unavailable')

    async def test_explicit_legacy_override_never_calls_model(self):
        client=SimpleNamespace(chat=AsyncMock())
        result=await resolve_patient('头晕',override='father',client=client)
        self.assertEqual(result['patient'],'father')
        client.chat.assert_not_awaited()

    def test_general_and_multiple_do_not_touch_patient_memory(self):
        for subject in ['general','multiple','unknown']:
            result=validate_resolution({'subject':subject,'confidence':.99},'问题',{})
            self.assertEqual(result['patient'],'other')
            self.assertEqual(result['needs_confirmation'],subject != 'general')

    def test_new_explicit_person_overrides_previous(self):
        result=validate_resolution({'subject':'self','confidence':.99,'evidence':'我自己','basis':'current'},'我自己也头晕',{'patient':'father'})
        self.assertEqual(result['patient'],'self')
        self.assertFalse(result['corrects_previous'])

    def test_correction_requires_user_correction_language(self):
        data={'subject':'mother','confidence':.99,'evidence':'我妈','basis':'current','corrects_previous':True}
        self.assertTrue(validate_resolution(data,'刚才其实是我妈的情况',{'patient':'father'})['corrects_previous'])
        self.assertFalse(validate_resolution(data,'我妈也有头晕',{'patient':'father'})['corrects_previous'])


class ConfirmationTests(unittest.TestCase):
    def test_memory_decision_requires_explicit_model_vote_and_quoted_fact(self):
        data = dict(subject='mother',confidence=.99,evidence='妈妈',basis='current',should_store=True,memory_evidence='鼻塞两天')
        self.assertTrue(validate_resolution(data,'妈妈鼻塞两天',{})['should_store'])
        for changes in ({'memory_evidence':'编造事实'},{'should_store':False},{'should_store':'true'},{'memory_evidence':''}):
            self.assertFalse(validate_resolution(data|changes,'妈妈鼻塞两天',{})['should_store'])
        self.assertFalse(validate_resolution({k:v for k,v in data.items() if k!='should_store'},'妈妈鼻塞两天',{})['should_store'])

    def test_memory_fact_cannot_be_inherited_without_confirmation(self):
        previous={'patient':'mother','history':[{'role':'user','content':'妈妈鼻塞两天'}]}
        data=dict(subject='mother',confidence=.99,evidence='妈妈',basis='history',should_store=True,memory_evidence='鼻塞两天')
        self.assertFalse(validate_resolution(data,'应该怎么办',previous)['should_store'])
        data.update(basis='current',confirms_previous=True)
        previous['awaiting_patient_confirmation']=True
        self.assertTrue(validate_resolution(data,'是妈妈的情况',previous)['should_store'])

    def test_person_confirmation_only_in_pending_chat(self):
        data={'subject':'father','confidence':.99,'evidence':'我爸爸','basis':'current','confirms_previous':True}
        self.assertTrue(validate_resolution(data,'是我爸爸',{'awaiting_patient_confirmation':True})['confirms_previous'])
        self.assertFalse(validate_resolution(data,'是我爸爸',{})['confirms_previous'])
