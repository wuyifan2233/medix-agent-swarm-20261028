"""Project password policy for new registrations and password changes only."""
import re
import string

MIN_LENGTH = 8
MAX_LENGTH = 20
PASSWORD_HINT = "密码须为 8–20 位，包含大写字母、小写字母、数字和特殊字符。"


def validate_new_password(value):
    if not (MIN_LENGTH <= len(value) <= MAX_LENGTH
            and re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)
            and re.search(r"[0-9]", value) and any(c in string.punctuation for c in value)):
        raise ValueError(PASSWORD_HINT)
    return value
