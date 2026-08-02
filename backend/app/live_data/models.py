from typing import Literal

from pydantic import BaseModel, Field


class LiveSensorCreate(BaseModel):
    source_key: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
    vin: str | None = Field(default=None, min_length=17, max_length=17, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="Personnalisés", min_length=1, max_length=80)
    unit: str | None = Field(default=None, max_length=24)
    factor: float = Field(default=1.0, ge=-1_000_000, le=1_000_000)
    offset: float = Field(default=0.0, ge=-1_000_000_000, le=1_000_000_000)


class LiveSensorUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="Personnalisés", min_length=1, max_length=80)
    unit: str | None = Field(default=None, max_length=24)
    factor: float = Field(default=1.0, ge=-1_000_000, le=1_000_000)
    offset: float = Field(default=0.0, ge=-1_000_000_000, le=1_000_000_000)
    archived: bool = False


class LiveSensorDefinition(LiveSensorCreate):
    key: str
    state: Literal["discovered", "observed", "validated", "documented", "published"] = "observed"
    archived: bool = False
    created_at: str
    updated_at: str
