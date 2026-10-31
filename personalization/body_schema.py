from typing import Literal
from pydantic import Field
from personalization.schemas import StrictModel

class BodyInfo(StrictModel):
    age: int | None = Field(default=None,ge=0,le=130,strict=True)
    sex: Literal['female','male','undisclosed'] = 'undisclosed'
    height_cm: float | None = Field(default=None,ge=30,le=250,allow_inf_nan=False,strict=True)
    weight_kg: float | None = Field(default=None,ge=1,le=400,allow_inf_nan=False,strict=True)
    acknowledged: Literal[True]

