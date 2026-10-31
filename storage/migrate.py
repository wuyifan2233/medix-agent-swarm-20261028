"""Run: python -m storage.migrate (or use alembic upgrade head)."""
from pathlib import Path
from alembic import command
from alembic.config import Config


def upgrade_database(database_url=None):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    if database_url:
        config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade_database()
    print("Application database migrations completed.")
