"""Structured tool input and output models for v1.mcp."""

from uuid import UUID

from pydantic import BaseModel

from app.models.company_member import CompanyRole


class CompanySummary(BaseModel):
    company_id: UUID
    name: str
    currency_code: str | None
    role: CompanyRole
    permissions: list[str]


class CompanyListResult(BaseModel):
    companies: list[CompanySummary]
    truncated: bool
