"""Project password policy for new registrations and password changes only."""
import re
import string

MIN_LENGTH = 8
MAX_LENGTH = 20
PASSWORD_HINT = "密码须为 8–20 位，大写字母、小写字母、数字、特殊字符中至少包含三类。"


def validate_new_password(value):
    categories = sum((bool(re.search(r"[A-Z]", value)), bool(re.search(r"[a-z]", value)),
                      bool(re.search(r"[0-9]", value)), any(c in string.punctuation for c in value)))
    if not (MIN_LENGTH <= len(value) <= MAX_LENGTH and categories >= 3):
        raise ValueError(PASSWORD_HINT)
    return value
