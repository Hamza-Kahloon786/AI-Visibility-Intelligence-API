from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def normalize_domain(raw: str) -> str:
    domain = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip("/")


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=3, max_length=255)
    industry: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    competitors: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v: str) -> str:
        return normalize_domain(v)

    @field_validator("competitors")
    @classmethod
    def _normalize_competitors(cls, v: list[str]) -> list[str]:
        return [normalize_domain(c) for c in v if c and c.strip()]
