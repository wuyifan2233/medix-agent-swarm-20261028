from alembic import context
from auth.settings import AuthSettings
from auth import models  # noqa: F401 - register model metadata
from storage.database import Base, make_database

target_metadata = Base.metadata
url = context.config.attributes.get("database_url") or AuthSettings.from_env().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()
else:
    engine, _ = make_database(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=engine.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
