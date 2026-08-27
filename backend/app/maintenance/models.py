from __future__ import annotations

from datetime import datetime
from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


ProviderKind = Literal[
    "garage",
    "dealership",
    "inspection_center",
    "body_shop",
    "tire_shop",
    "parts_supplier",
    "other",
]


class ServiceProviderInput(BaseModel):
    """Professionnel normalisé, réutilisable entre documents et véhicules."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    kind: ProviderKind = "garage"
    legal_name: str = Field(min_length=1, max_length=180)
    display_name: str | None = Field(default=None, max_length=180)
    network: str | None = Field(default=None, max_length=120)
    siren: str | None = Field(default=None, max_length=20)
    siret: str | None = Field(default=None, max_length=24)
    vat_number: str | None = Field(default=None, max_length=24)
    address_line1: str | None = Field(default=None, max_length=220)
    address_line2: str | None = Field(default=None, max_length=220)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="FR", min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    website: str | None = Field(default=None, max_length=240)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    verified_by_user: bool = False

    @field_validator("siren", "siret")
    @classmethod
    def normalize_registration_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"\D", "", value)
        return normalized or None

    @field_validator("vat_number", "country_code")
    @classmethod
    def normalize_uppercase(cls, value: str | None) -> str | None:
        return value.upper().replace(" ", "") if value else None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.casefold() if value else None

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(alias for alias in value if alias))

    @model_validator(mode="after")
    def validate_company_identifiers(self) -> "ServiceProviderInput":
        if self.siren and len(self.siren) != 9:
            raise ValueError("Le SIREN doit contenir 9 chiffres.")
        if self.siret and len(self.siret) != 14:
            raise ValueError("Le SIRET doit contenir 14 chiffres.")
        return self


class ServiceProvider(ServiceProviderInput):
    id: str
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)


class ImportedField(BaseModel):
    """Valeur brute et proposition normalisée produites par un importeur."""

    raw_value: JsonValue = None
    normalized_value: JsonValue = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str | None = Field(default=None, max_length=2_000)


class DocumentImportSnapshot(BaseModel):
    """Brouillon immuable gardé à côté des valeurs corrigées par l'utilisateur."""

    engine: str = Field(min_length=1, max_length=80)
    engine_version: str | None = Field(default=None, max_length=80)
    analyzed_at: datetime
    document_id: str | None = None
    fields: dict[str, ImportedField] = Field(default_factory=dict)
    raw_payload: dict[str, JsonValue] = Field(default_factory=dict)
    text_excerpt: str = Field(default="", max_length=20_000)
    warnings: list[str] = Field(default_factory=list, max_length=100)
