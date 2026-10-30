"""Read local defaults without mutating the process environment."""
import os
from pathlib import Path


def load_setting(name, default=''):
    from dotenv import dotenv_values
    value = os.environ.get(name, '').strip()
    if value:
        return value
    values = dotenv_values(Path(__file__).resolve().parent / '.env.local', encoding='utf-8-sig')
    return (values.get(name) or default).strip()
