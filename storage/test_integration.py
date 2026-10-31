"""Cross-module ownership and single-database checks with synthetic records only."""
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, text
from auth.models import User
from storage.test_support import account_clients
from storage.migrate import upgrade_database


class SharedDatabaseTests(unittest.TestCase):
    def test_reminders_and_channel_preferences_use_account_database(self):
        from reminders.service import get_service
        from messenger import save_channel_state, load_channel_state, set_channel, current_channel
        from datetime import datetime
        from reminders.schedule import SHANGHAI
        with account_clients() as accounts:
            alice, bob = accounts.clients
            a,b = [user.id for user in accounts.users]
            service=get_service()
            created=service.handle(a,a+'-chat',action='create',kind='medication',drug='维生素C',repeat='once',
                                   fire_at='2030-01-02T09:00:00+08:00')
            self.assertTrue(created['success'])
            self.assertEqual(len(alice.get('/api/reminders').json()['upcoming']),1)
            self.assertEqual(bob.get('/api/reminders').json()['upcoming'],[])
            self.assertEqual(bob.post('/api/reminders/'+created['reminder_id']+'/cancel',json={}).status_code,404)
            set_channel('qq',a)
            self.assertEqual(current_channel(a),'qq')
            self.assertEqual(current_channel(b),'wechat')
            save_channel_state('qq',a,{'owner_browser':a,'secret':'fixture-not-a-real-key'})
            with self.assertRaises(ValueError):save_channel_state('qq',b,{'owner_browser':b})
            from reminders.service import reset_service
            reset_service()
            service=get_service()
            self.assertEqual(service.store.get(created['reminder_id'])['user_id'],a)
            self.assertEqual(load_channel_state('qq')['owner_browser'],a)
            with accounts.sessions() as db:
                db.get(User,a).is_active=False
                db.commit()
            self.assertIsNone(load_channel_state('qq'))
            service.sync(now=datetime(2030,1,2,9,1,tzinfo=SHANGHAI))
            self.assertEqual(service.store.count_deliveries(created['reminder_id']),0)
            with accounts.sessions() as db:
                db.delete(db.get(User,a));db.commit()
                for table in ['reminders','reminder_deliveries','channel_bindings','channel_preferences']:
                    self.assertEqual(db.execute(text('SELECT count(*) FROM '+table)).scalar(),0,table)

    def test_qq_requires_target_to_confirm_binding_before_answering(self):
        from qq.bridge import QQBridge
        from qq.test_bridge import FakeOneBot
        import re
        with account_clients() as accounts:
            owner=accounts.users[0].id
            fake=FakeOneBot()
            answers=[]
            bridge=QQBridge('unused-test-file',client=fake,reply=lambda *args:answers.append(args) or 'ok')
            bridge.database_backed=True
            bridge.begin_login(owner)
            bridge.add_friend(owner,'20002')
            code=re.search(r'绑定 ([A-F0-9]{6})',fake.sent[-2][1] if len(fake.sent)>1 else fake.sent[-1][1])
            if not code:
                code=next(re.search(r'绑定 ([A-F0-9]{6})',message) for _,message in fake.sent if '5分钟' in message)
            def incoming(ident,text,user=20002):
                bridge.handle_event({'post_type':'message','message_type':'private','message_id':ident,'user_id':user,
                    'message':[{'type':'text','data':{'text':text}}]})
                bridge.run_pending()
            incoming(1,'私密问题')
            self.assertEqual(answers,[])
            incoming(2,'绑定 '+code[1],user=30003)
            self.assertFalse(bridge.view(owner)['can_push'])
            incoming(3,'绑定 '+code[1])
            self.assertTrue(bridge.view(owner)['can_push'])
            incoming(4,'合成测试问题')
            self.assertEqual(answers[0][0],owner)
            def switching_reply(*args):
                answers.append(args)
                bridge.owner=accounts.users[1].id
                return '不得发送的迟到回答'
            bridge.reply=switching_reply
            incoming(5,'生成期间切换了渠道归属')
            self.assertEqual(answers[-1][0],owner)
            self.assertFalse(any('不得发送的迟到回答' in message for _,message in fake.sent))
            bridge.owner=owner
            with accounts.sessions() as db:
                db.get(User,owner).is_active=False;db.commit()
            incoming(6,'已停用账号的问题')
            self.assertEqual(len(answers),2)

    def test_reports_profile_and_memory_share_database_and_account(self):
        from web import case_memory
        from memory.case_memory import CaseMemory
        with account_clients() as accounts:
            alice, bobby = accounts.clients
            a, b = [user.id for user in accounts.users]
            operation = {'action':'add','source':'user','quote':'体温38',
                         'fact':{'name':'体温','value':'38'}}
            with patch.object(case_memory, 'DB_PATH', None):
                saved = case_memory.apply_changes(a,'chat','','request',
                         {'operations':[operation],'questions':[]},'体温38','')
                self.assertEqual(alice.get('/api/cases').json()['cases'][0]['id'], saved['case_id'])
                self.assertEqual(bobby.get('/api/cases').json()['cases'], [])
                with self.assertRaises(LookupError):
                    case_memory.require_case(b, saved['case_id'])
            journal = CaseMemory()
            ident = journal.save(a,'test','我今天头晕','self')
            self.assertEqual(journal.list(b), [])
            self.assertEqual(journal.list(a)[0]['id'], ident)
            self.assertFalse(journal.change(b,ident,'delete'))
            with accounts.sessions() as db:
                tables = inspect(db.bind).get_table_names()
                for name in ['users','health_profiles','report_cases','memory_cases','demo_memory_cases']:
                    self.assertIn(name, tables)
                self.assertEqual(db.execute(text('SELECT owner FROM report_cases')).scalar(),a)
                self.assertEqual(db.execute(text('SELECT owner FROM memory_cases')).scalar(),a)
            upgrade_database(accounts.url)

    def test_real_authentication_and_csrf_protect_imported_routes(self):
        from fastapi.testclient import TestClient
        from web.app import app
        with account_clients() as accounts:
            with patch('web.app.warmup'), TestClient(app) as anonymous:
                for endpoint in ['/api/cases','/api/memories?demo=true','/api/profile']:
                    self.assertEqual(anonymous.get(endpoint).status_code,401,endpoint)
            alice = accounts.clients[0]
            csrf = alice.headers.pop('X-CSRF-Token')
            self.assertEqual(alice.post('/api/memory/demo',json={}).status_code,403)
            alice.headers['X-CSRF-Token'] = csrf

    def test_deleting_user_cascades_local_private_records(self):
        from web import case_memory
        from memory.case_memory import CaseMemory
        with account_clients() as accounts:
            a = accounts.users[0].id
            operation = {'action':'add','source':'user','quote':'体温38','fact':{'name':'体温','value':'38'}}
            case_memory.apply_changes(a,'chat','','request',{'operations':[operation]},'体温38','')
            CaseMemory().save(a,'session','我今天头晕','self')
            with accounts.sessions() as db:
                db.delete(db.get(User,a))
                db.commit()
                for table in ['report_cases','report_facts','report_versions','memory_cases']:
                    self.assertEqual(db.execute(text('SELECT count(*) FROM '+table)).scalar(),0,table)
