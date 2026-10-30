import hashlib
import secrets
from pwdlib import PasswordHash

passwords = PasswordHash.recommended()
# An equal-cost verification for unknown usernames avoids a cheap timing oracle.
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_token():
    return secrets.token_urlsafe(32)
