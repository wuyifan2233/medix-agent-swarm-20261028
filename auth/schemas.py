from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re
from auth.password_policy import MIN_LENGTH, MAX_LENGTH, validate_new_password


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalized_username(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff]{3,32}", value):
            raise ValueError("用户名须为 3–32 位中文、字母、数字或下划线")
        return value.lower()


from personalization.body_schema import BodyInfo

class Registration(Credentials):
    basic_profile: BodyInfo | None = None
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    display_name: str | None = Field(default=None, min_length=1, max_length=60)

    _password_policy = field_validator("password")(validate_new_password)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("请输入展示名称")
        return value


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    _password_policy = field_validator("new_password")(validate_new_password)


class StatusChange(StrictModel):
    is_active: bool = Field(strict=True)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    username: str
    display_name: str
    role: str


def public_user(user):
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "avatar_url": user.avatar_data, "has_password": user.has_password,
            "phone_masked": user.phone_number[:3] + "****" + user.phone_number[-4:] if user.phone_number else None,
            "role": user.role, "is_active": user.is_active, "created_at": user.created_at}


class PhoneCredentials(StrictModel):
    phone_number: str = Field(pattern=r"^1[3-9][0-9]{9}$")
    password: str = Field(min_length=1, max_length=128)


class NicknameChange(StrictModel):
    nickname: str = Field(min_length=1, max_length=20)

    @field_validator("nickname", mode="before")
    @classmethod
    def clean_nickname(cls, value):
        if not isinstance(value, str):
            raise ValueError("请输入昵称")
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("昵称不能为空，且不能包含换行或控制字符")
        return value
