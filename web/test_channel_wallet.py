"""Bound channels use the managed completion path; no live messages or payments."""
import asyncio
import json
import unittest
import uuid
from unittest.mock import patch
import httpx
from openai import AsyncOpenAI
from storage.test_support import account_clients
from storage import care_wallet,care_orders
from storage.business import connect
from messenger import save_channel_state,clear_channel_state
from core.chat_runtime import completion,runtime


class ChannelWalletTests(unittest.TestCase):
    def setUp(self):
        self.scope=account_clients();self.accounts=self.scope.__enter__();self.owner=self.accounts.users[0].id
        self.requests=[];self.known=True
        for channel in ('qq','wechat'):save_channel_state(channel,self.owner,{'owner_browser':self.owner})
    def tearDown(self):self.scope.__exit__(None,None,None)

    def provider(self,request):
        self.requests.append(json.loads(request.content))
        frames=[{'id':'mock','object':'chat.completion.chunk','created':0,'model':'deepseek-flash',
            'choices':[{'index':0,'delta':{'content':'虚构渠道回答'},'finish_reason':None}]},
            {'id':'mock','object':'chat.completion.chunk','created':0,'model':'deepseek-flash',
            'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
        if self.known:frames.append({'id':'mock','object':'chat.completion.chunk','created':0,'model':'deepseek-flash','choices':[],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_cache_hit_tokens':40}})
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames).encode())

    async def analyze(self,job,payload,session_id,memory_user_id):
        from web.app import contexts
        async with AsyncOpenAI(api_key='mock',http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.provider))) as client:
            for agent in ('stage:patient','consultation_agent'):
                await completion(client,{'model':'deepseek-flash','messages':[{'role':'user','content':payload['message']}]},visible=True,agent=agent)
        contexts[session_id]={'history':[{'question':payload['message'],'answer':'虚构渠道回答'}]}
        job['result']={'answer':'虚构渠道回答'}

    def answer(self,channel,ident='bot:peer:1'):
        from web.app import _answer_phone
        box={}
        with patch('web.app.analyze',self.analyze),patch.dict('web.app.health',{'knowledge':'ready'}),patch('qq.bridge.get_bridge') as qq,patch('wechat.bridge.get_bridge') as wx:
            _answer_phone(box,channel,self.owner,f'web-{self.owner}-{channel}','虚构渠道验收',ident)
            qq.assert_not_called();wx.assert_not_called()
        return box

    def test_both_channels_share_balance_usage_and_durable_deduplication(self):
        initial=care_wallet.view(self.owner)['balance']
        qq=self.answer('qq');wx=self.answer('wechat')
        self.assertNotIn('error',qq);self.assertNotIn('error',wx)
        self.assertEqual(qq['answer'],'虚构渠道回答');self.assertEqual(wx['answer'],'虚构渠道回答')
        self.assertEqual(len(self.requests),4)
        self.assertTrue(all(request['stream'] for request in self.requests))
        spent=qq['usage']['charge']['points']+wx['usage']['charge']['points']
        self.assertAlmostEqual(care_wallet.view(self.owner)['balance'],initial-spent)
        self.assertEqual(care_wallet.view(self.accounts.users[1].id)['balance'],10000)
        entries=care_wallet.history(self.owner)['entries'];self.assertEqual({e['channel'] for e in entries},{'qq','wechat'})
        self.assertTrue(all(e['requests']==2 and e['assistant_requests']==1 for e in entries))
        before=care_wallet.view(self.owner)
        duplicate=self.answer('qq')
        self.assertEqual(duplicate['answer'],qq['answer']);self.assertEqual(len(self.requests),4)
        self.assertEqual(care_wallet.view(self.owner),before)
        with connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_turns WHERE owner=?',(self.owner,)).fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_contexts WHERE owner=?',(self.owner,)).fetchone()[0],2)
        self.assertIsNone(runtime.get())

    def test_zero_balance_blocks_provider_and_gives_channel_message(self):
        with patch.dict('os.environ',{'MEDIX_INITIAL_CARE_POINTS':'0'}):box=self.answer('qq')
        self.assertIn('关怀点不足',str(box['error']));self.assertEqual(self.requests,[])
        self.assertEqual(care_wallet.view(self.owner)['balance'],0)

    def test_unknown_usage_holds_credits_and_disconnected_binding_blocks_calls(self):
        self.known=False;box=self.answer('wechat')
        self.assertNotIn('error',box);self.assertEqual(box['answer'],'虚构渠道回答')
        self.assertGreater(box['usage']['charge']['held_points'],0)
        self.assertEqual(care_wallet.view(self.owner)['balance'],10000)
        self.assertGreater(care_wallet.view(self.owner)['held'],0)
        clear_channel_state('wechat',self.owner);box=self.answer('wechat','bot:peer:2')
        self.assertIn('渠道已断开',str(box['error']));self.assertEqual(len(self.requests),2)


class RechargeTests(unittest.TestCase):
    def setUp(self):
        self.scope=account_clients();self.accounts=self.scope.__enter__();self.owner=self.accounts.users[0].id
        self.a,self.b=self.accounts.clients
    def tearDown(self):self.scope.__exit__(None,None,None)

    def test_orders_are_server_priced_idempotent_unpaid_and_account_owned(self):
        before=care_wallet.view(self.owner);plans=self.a.get('/api/wallet/plans').json()
        self.assertFalse(plans['payment_enabled']);self.assertEqual(plans['plans'][0]['points'],10000)
        payload={'plan_id':'light','request_id':str(uuid.uuid4())}
        response=self.a.post('/api/wallet/orders',json=payload);self.assertEqual(response.status_code,201,response.text)
        order=response.json();self.assertEqual(order['amount_fen'],1000);self.assertEqual(order['status'],'awaiting_payment')
        self.assertFalse(order['payment_enabled']);self.assertEqual(self.a.post('/api/wallet/orders',json=payload).json()['id'],order['id'])
        self.assertEqual(self.a.post('/api/wallet/orders',json={**payload,'plan_id':'daily'}).status_code,409)
        self.assertEqual(self.a.post('/api/wallet/orders',json={**payload,'amount_fen':1,'points':999999,'status':'paid','owner':self.accounts.users[1].id}).status_code,422)
        self.assertEqual(self.a.post('/api/wallet/orders',json=payload,headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(self.b.get('/api/wallet/orders').json()['orders'],[])
        self.assertEqual(self.b.post('/api/wallet/orders/'+order['id']+'/cancel',json={}).status_code,404)
        self.assertEqual(self.a.post('/api/wallet/orders/'+order['id']+'/cancel',json={}).json()['status'],'cancelled')
        self.assertEqual(self.a.post('/api/wallet/orders/'+order['id']+'/cancel',json={}).json()['status'],'cancelled')
        self.assertEqual(care_wallet.view(self.owner),before)
        with connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM care_ledger WHERE kind!='welcome'").fetchone()[0],0)

    def test_expiry_pending_limit_and_wallet_conversion_snapshot(self):
        with patch.dict('os.environ',{'MEDIX_CARE_POINTS_PER_CNY':'2000'}):care_wallet.view(self.owner)
        self.assertEqual(care_orders.catalog(self.owner)['plans'][0]['points'],20000)
        for _ in range(5):care_orders.create(self.owner,'light',str(uuid.uuid4()))
        with self.assertRaises(ValueError):care_orders.create(self.owner,'daily',str(uuid.uuid4()))
        with connect() as db:db.execute('UPDATE care_orders SET expires=0 WHERE owner=?',(self.owner,))
        order=care_orders.create(self.owner,'daily',str(uuid.uuid4()))
        self.assertEqual(order['points'],60000)
        page=care_orders.list_orders(self.owner,limit=2);self.assertTrue(page['has_more'])
        self.assertEqual(page['orders'][1]['status'],'expired')
        self.assertEqual(care_orders.list_orders(self.owner,offset=4)['has_more'],False)
        self.assertEqual(care_wallet.view(self.owner)['balance'],10000)
