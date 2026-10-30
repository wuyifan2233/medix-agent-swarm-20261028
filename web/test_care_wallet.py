"""Atomic credits and the official CNY peak/off-peak tariff."""
import unittest,uuid
from datetime import datetime,timezone
from decimal import Decimal
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from storage.test_support import account_clients
from storage.chat import store
from storage import care_wallet as wallet
from core.token_pricing import price_for
from storage.business import connect

class PricingTests(unittest.TestCase):
    def price(self,text):return price_for('deepseek-flash',datetime.fromisoformat(text))
    def test_peak_boundaries_weekend_holiday(self):
        for date,expected in [('2026-10-30T00:59:00+00:00','1'),('2026-10-30T01:00:00+00:00','2'),('2026-10-30T04:00:00+00:00','1'),('2026-10-30T06:00:00+00:00','2'),('2026-10-30T10:00:00+00:00','1'),('2026-10-31T02:00:00+00:00','1'),('2026-10-01T02:00:00+00:00','1')]:
            with self.subTest(date=date):
                p=self.price(date);self.assertEqual(p['input'],expected);self.assertEqual(p['currency'],'CNY')
                self.assertEqual(Decimal(p['output']),Decimal(expected)*4)
    def test_non_cny_override_rejected(self):
        with patch.dict('os.environ',{'MEDIX_TOKEN_PRICES':'{"deepseek-flash":{"currency":"USD"}}'}):
            with self.assertRaises(ValueError):self.price('2026-10-31T02:00:00+00:00')

class WalletTests(unittest.TestCase):
    def setUp(self):
        self.scope=account_clients();self.accounts=self.scope.__enter__();self.owner=self.accounts.users[0].id
        self.chat=str(uuid.uuid4());self.turn=str(uuid.uuid4())
        store.create_turn(self.owner,self.chat,str(uuid.uuid4()),self.turn,{'message':'虚构验收','images':[],'case_id':''})
    def tearDown(self):self.scope.__exit__(None,None,None)
    def test_welcome_once_account_isolation_and_rounding(self):
        self.assertEqual(wallet.view(self.owner)['balance'],10000)
        wallet.view(self.owner)
        wallet.reserve('call-a',self.turn,{})
        wallet.settle('call-a','0.0012345')
        wallet.settle('call-a','0.0012345')
        self.assertEqual(wallet.view(self.owner)['balance'],9998.765)
        self.assertEqual(wallet.view(self.accounts.users[1].id)['balance'],10000)
        self.assertEqual(wallet.turn_charge(self.turn)['points'],1.235)
    def test_pending_reservation_and_delete_does_not_refund(self):
        wallet.reserve('known',self.turn,{});wallet.settle('known','0.01')
        wallet.reserve('unknown',self.turn,{});wallet.settle('unknown',None,unknown=True)
        balance=wallet.view(self.owner)
        self.assertGreater(balance['held'],0);self.assertLess(balance['available'],balance['balance'])
        store.update(self.turn,'cancelled');store.delete(self.owner,self.chat)
        self.assertEqual(wallet.view(self.owner),balance)
        wallet.settle('unknown','0.002')
        self.assertEqual(wallet.view(self.owner)['held'],0)
        self.assertEqual(wallet.view(self.owner)['balance'],9988)
    def test_insufficient_credit_does_not_start_or_overdraw(self):
        with patch.dict('os.environ',{'MEDIX_INITIAL_CARE_POINTS':'0'}):
            with self.assertRaises(wallet.CarePointsError):wallet.reserve('no-credit',self.turn,{})
            self.assertEqual(wallet.view(self.owner)['balance'],0)
            self.assertEqual(wallet.turn_charge(self.turn)['recorded'],False)
    def test_concurrent_reservations_cannot_spend_same_balance(self):
        with patch.dict('os.environ',{'MEDIX_INITIAL_CARE_POINTS':'100'}):
            wallet.view(self.owner)
            def reserve(ident):
                try:wallet.reserve(ident,self.turn,{});return True
                except wallet.CarePointsError:return False
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,['one','two']))
            self.assertEqual(sum(results),1)
            self.assertGreaterEqual(wallet.view(self.owner)['available'],0)
    def test_wallet_api_uses_current_user(self):
        response=self.accounts.clients[0].get('/api/wallet');self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['name'],'关怀点')
        wallet.reserve('mine',self.turn,{});wallet.settle('mine','0.1')
        self.assertEqual(self.accounts.clients[1].get('/api/wallet').json()['balance'],10000)

    def test_history_groups_calls_and_isolates_accounts(self):
        for ident,agent in [('routing','stage:agents'),('answer-1','consultation_agent'),('answer-2','consultation_agent')]:
            wallet.reserve(ident,self.turn,{})
            wallet.settle(ident,'0.001')
            with connect() as db:
                db.execute('''INSERT INTO model_usage
                    (id,turn_id,agent,model,status,price,input_tokens,output_tokens,cache_hit_tokens,usage_known,created,updated)
                    VALUES(?,?,?,'deepseek-flash','completed','{}',100,20,30,1,1,1)''',(ident,self.turn,agent))
        response=self.accounts.clients[0].get('/api/wallet/history')
        self.assertEqual(response.status_code,200)
        entry=response.json()['entries'][0]
        self.assertEqual((entry['points'],entry['requests'],entry['agent_count'],entry['assistant_requests']),(3,3,1,2))
        self.assertEqual((entry['input_tokens'],entry['output_tokens'],entry['cache_hit_tokens']),(300,60,90))
        self.assertNotIn('cost_cny',entry['calls'][0])
        self.assertEqual(self.accounts.clients[1].get('/api/wallet/history').json()['entries'],[])
        self.assertEqual(self.accounts.clients[0].get('/api/wallet/history?offset=-1').status_code,400)

    def test_history_pagination_pending_and_deleted_turn(self):
        wallet.reserve('pending',self.turn,{});wallet.settle('pending',None,unknown=True)
        for index in range(2):
            tid=str(uuid.uuid4());chat=str(uuid.uuid4())
            store.create_turn(self.owner,chat,str(uuid.uuid4()),tid,{'message':'虚构分页','images':[],'case_id':''})
            wallet.reserve('page-'+str(index),tid,{});wallet.settle('page-'+str(index),'0.002')
        first=wallet.history(self.owner,limit=2)
        self.assertTrue(first['has_more']);self.assertEqual(first['next_offset'],2)
        second=wallet.history(self.owner,offset=2,limit=2)
        self.assertFalse(second['has_more']);self.assertEqual(second['entries'][0]['id'],self.turn)
        self.assertGreater(second['entries'][0]['held_points'],0)
        store.update(self.turn,'cancelled');store.delete(self.owner,self.chat)
        deleted=wallet.history(self.owner,offset=2)['entries'][0]
        self.assertTrue(deleted['deleted']);self.assertEqual(deleted['title'],'已删除的对话')
        self.assertGreater(deleted['held_points'],0)
