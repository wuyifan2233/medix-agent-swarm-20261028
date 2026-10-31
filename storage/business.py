"""SQLite adapters over the account database, shared by imported business modules."""
from functools import lru_cache
import re
import sqlite3
import sys
from threading import RLock

from auth.settings import AuthSettings
from storage.database import make_database

_lock = RLock()


def database_url():
    # Runtime tests may replace the application service with an isolated database.
    app_module = sys.modules.get('web.app')
    app = getattr(app_module, 'app', None)
    service = getattr(getattr(app, 'state', None), 'auth_service', None)
    return service.settings.database_url if service else AuthSettings.from_env().database_url


@lru_cache(maxsize=16)
def engine_for(url):
    if not url.startswith('sqlite:'):
        raise ValueError('The integrated local demo requires a SQLite business database')
    from storage.migrate import upgrade_database
    with _lock:
        upgrade_database(url)
    return make_database(url)[0]


class Connection:
    def __init__(self, connection, tables=None):
        self.raw = connection
        self.driver = getattr(connection, 'driver_connection', connection)
        self.driver.row_factory = sqlite3.Row
        self.tables = tables or {}

    @property
    def total_changes(self):
        return self.driver.total_changes

    def sql(self, sql):
        if not self.tables:
            return sql
        return re.sub(r'\b(' + '|'.join(map(re.escape, self.tables)) + r')\b',
                      lambda match: self.tables[match[0]], sql)

    def execute(self, sql, parameters=()):
        return self.driver.execute(self.sql(sql), parameters)

    def executemany(self, sql, parameters):
        return self.driver.executemany(self.sql(sql), parameters)

    def executescript(self, sql):
        return self.driver.executescript(self.sql(sql))

    def commit(self):
        self.driver.commit()

    def rollback(self):
        self.driver.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.rollback() if error else self.commit()
        finally:
            self.close()


def connect(*, tables=None, test_path=None):
    # An explicit path is reserved for standalone module fixtures/legacy tools.
    # Production callers omit it and always use MEDIX_DATABASE_URL.
    if test_path is not None:
        from pathlib import Path
        Path(test_path).parent.mkdir(parents=True, exist_ok=True)
        return Connection(sqlite3.connect(str(test_path), timeout=15, check_same_thread=False), tables)
    return Connection(engine_for(database_url()).raw_connection(), tables)
