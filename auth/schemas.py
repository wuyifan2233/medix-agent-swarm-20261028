from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalized_username(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", value):
            raise ValueError("用户名须为 3–32 位字母、数字或下划线")
        return value.lower()


class Registration(Credentials):
    password: str = Field(min_length=15, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入展示名称")
        return value


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


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
            "role": user.role, "is_active": user.is_active, "created_at": user.created_at}
