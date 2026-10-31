from typing import Literal
from datetime import date
import re
from pydantic import Field,field_validator
from personalization.schemas import StrictModel

class BodyInfo(StrictModel):
    name: str | None = Field(default=None,max_length=50,strict=True)

    @field_validator('name')
    @classmethod
    def valid_name(cls,value):
        if value is None:return None
        if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('姓名不能包含控制字符')
        return value.strip() or None

    birth_month: str | None = Field(default=None,strict=True)
    sex: Literal['female','male','undisclosed'] = 'undisclosed'

    @field_validator('birth_month')
    @classmethod
    def valid_birth_month(cls,value):
        if value is None:return value
        if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',value):raise ValueError('出生年月格式应为YYYY-MM')
        year,month=map(int,value.split('-'));today=date.today()
        months=(today.year-year)*12+today.month-month
        if months<0 or months>130*12:raise ValueError('出生年月不能晚于当前月份或超出130年')
        return value
