from typing import Literal
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    kind: Literal['manual', 'report'] = 'manual'
    label: str = Field(default='本人填写', max_length=100)
    report_date: date | None = None
    excerpt: str = Field(default='', max_length=240)


class HealthItem(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=160)
    status: Literal["reported", "historical", "unknown", "current", "stopped"] = "reported"
    source: Source | None = None


class Medication(HealthItem):
    dose: str = Field(default="", max_length=60)
    frequency: str = Field(default="", max_length=60)


class History(StrictModel):
    status: Literal["unknown", "none_reported", "reported"] = "unknown"
    items: list[HealthItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "reported") != bool(self.items):
            raise ValueError("有记录时请填写条目；未知或自述无记录时请清空条目")
        return self


class MedicationHistory(History):
    items: list[Medication] = Field(default_factory=list, max_length=20)


class ProfileData(StrictModel):
    age: int | None = Field(default=None, ge=0, le=130, strict=True)
    sex: Literal["unknown", "female", "male", "other", "undisclosed"] = "unknown"
    conditions: History = Field(default_factory=History)
    allergies: History = Field(default_factory=History)
    medications: MedicationHistory = Field(default_factory=MedicationHistory)
    field_sources: dict[Literal['age','sex'], Source] = Field(default_factory=dict)


class SaveProfile(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    data: ProfileData


class ConfirmProfile(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    acknowledged: bool = Field(strict=True)

    @model_validator(mode="after")
    def explicit_acknowledgement(self):
        if not self.acknowledged:
            raise ValueError("必须主动确认已核对档案")
        return self


class DeleteProfile(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)


class RestoreProfile(DeleteProfile):
    target_revision: int = Field(ge=1, strict=True)
