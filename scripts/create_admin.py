"""Create an initial admin without putting passwords in arguments or source."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth.schemas import Registration
from auth.service import AuthService
from auth.settings import AuthSettings
from storage.database import make_database
from storage.migrate import upgrade_database


def main():
    settings = AuthSettings.from_env()
    upgrade_database(settings.database_url)
    username = input("Admin username (3-32 letters/digits/underscore): ")
    display_name = input("Display name: ")
    password = getpass.getpass("Password (8-20 chars; uppercase, lowercase, digit and symbol): ")
    if password != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords do not match")
    data = Registration(username=username, display_name=display_name, password=password)
    engine, sessions = make_database(settings.database_url)
    try:
        user = AuthService(sessions, settings).register(data, role="admin")
        print("Admin created:", user.username)
    finally:
        engine.dispose()


if __name__ == "__main__":
    from pydantic import ValidationError
    from fastapi import HTTPException
    try:
        main()
    except ValidationError:
        print("Invalid input: username 3-32 ASCII letters/digits/underscore, nonempty name, password 8-20 characters including uppercase, lowercase, digit and symbol.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, HTTPException) as exc:
        print(exc.detail if isinstance(exc, HTTPException) else str(exc), file=sys.stderr)
        sys.exit(1)
