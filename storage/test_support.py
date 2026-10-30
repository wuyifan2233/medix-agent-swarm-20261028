"""Real cookie/CSRF clients backed by an isolated database for integration tests."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient
from auth.schemas import Registration
from auth.service import AuthService
from auth.settings import AuthSettings
from storage.database import make_database
from storage.migrate import upgrade_database


@contextmanager
def account_clients():
    from web.app import app, contexts, jobs
    old = app.state.auth_service
    clients = []
    with TemporaryDirectory() as directory:
        url = 'sqlite:///' + (Path(directory) / 'app.db').as_posix()
        upgrade_database(url)
        engine, sessions = make_database(url)
        service = AuthService(sessions, AuthSettings(url, False, frozenset({'http://testserver'}),
                            True, namespace='integration-test', password_registration_enabled=True))
        app.state.auth_service = service
        users = []
        try:
            for name in ('alice', 'bobby'):
                users.append(service.register(Registration(username=name, password='Test-Password2026!')))
                client = TestClient(app, headers={'Origin':'http://testserver','X-Medix-Request':'1'})
                response = client.post('/api/auth/login', json={'username':name,'password':'Test-Password2026!'})
                response.raise_for_status()
                client.headers['X-CSRF-Token'] = response.json()['csrf_token']
                clients.append(client)
            yield SimpleNamespace(clients=clients, users=users, service=service, url=url, sessions=sessions)
        finally:
            for client in clients:
                client.close()
            contexts.clear()
            jobs.clear()
            from storage.business import engine_for
            for cached_url in (url,):
                # Return pooled SQLite connections before removing the temporary directory.
                engine_for(cached_url).dispose()
            engine.dispose()
            app.state.auth_service = old
