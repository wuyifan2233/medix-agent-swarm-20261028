"""Server-injected identity for reminder tools. The model cannot set these."""
import contextvars
from contextlib import contextmanager

user_id_var = contextvars.ContextVar("medix_reminder_user_id", default="")
session_id_var = contextvars.ContextVar("medix_reminder_session_id", default="")


def current_identity():
    return user_id_var.get() or "", session_id_var.get() or ""


@contextmanager
def bind_identity(user_id, session_id):
    user_token = user_id_var.set(user_id or "")
    session_token = session_id_var.set(session_id or "")
    try:
        yield
    finally:
        user_id_var.reset(user_token)
        session_id_var.reset(session_token)
