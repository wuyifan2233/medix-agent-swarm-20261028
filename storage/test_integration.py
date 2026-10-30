"""Cross-module ownership and single-database checks with synthetic records only."""
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, text
from auth.models import User
from storage.test_support import account_clients
from storage.migrate import upgrade_database


class SharedDatabaseTests(unittest.TestCase):
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
            with TestClient(app) as anonymous:
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
