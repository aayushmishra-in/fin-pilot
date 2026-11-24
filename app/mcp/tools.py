"""Read-only MCP tools backed by FinPilot's company-scoped services."""

from __future__ import annotations

import logging
import time
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.permissions import permissions_for_role
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.user import User
from app.mcp.runtime import MCPRuntime
from app.mcp.schemas import CompanyListResult, CompanySummary
from app.mcp.settings import MCPSettings
from app.schemas.metrics import BudgetVsActualRead, CashFlowMetricsRead
from app.services.metrics import (
    calculate_budget_vs_actual,
    calculate_cash_flow_metrics,
    resolve_cash_flow_range,
    validate_cash_balance,
)

logger = logging.getLogger(__name__)
MAX_COMPANIES_RETURNED = 100


def _error_code(error: ToolError) -> str:
    message = str(error)
    if message.startswith("[") and "]" in message:
        return message[1 : message.index("]")]
    return "tool_error"


async def _load_user(db: AsyncSession) -> User:
    access_token = get_access_token()
    if access_token is None or not access_token.subject:
        raise ToolError(
            "[authentication_required] Authentication is required to use FinPilot."
        )
    try:
        auth_user_id = UUID(access_token.subject)
    except ValueError as error:
        raise ToolError(
            "[identity_not_linked] The authenticated identity is not linked to FinPilot."
        ) from error
    user = await db.scalar(select(User).where(User.auth_user_id == auth_user_id))
    if user is None:
        raise ToolError(
            "[identity_not_linked] The authenticated identity is not linked to FinPilot."
        )
    return user


async def _require_company_membership(
    db: AsyncSession, *, user_id: UUID, company_id: UUID
) -> CompanyMember:
    membership = await db.scalar(
        select(CompanyMember).where(
            CompanyMember.user_id == user_id,
            CompanyMember.company_id == company_id,
        )
    )
    if membership is None:
        # Do not distinguish an unknown company from a company owned by someone else.
        raise ToolError("[company_access_denied] Company access is denied.")
    return membership


async def _enforce_rate_limit(
    runtime: MCPRuntime,
    config: MCPSettings,
    *,
    user_id: UUID,
    company_id: UUID | None,
    tool_name: str,
) -> int:
    redis = runtime.redis
    if redis is None:
        raise ToolError(
            "[temporary_failure] FinPilot is temporarily unavailable; retry shortly."
        )

    now = time.time()
    bucket = int(now // 60)
    company_key = str(company_id) if company_id is not None else "all"
    key = f"mcp:v1:{user_id}:{company_key}:{tool_name}:{bucket}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 120)
    except Exception as error:
        logger.warning(
            "MCP rate limiter unavailable",
            extra={
                "user_id": str(user_id),
                "company_id": str(company_id) if company_id else None,
                "tool_name": tool_name,
                "error_code": "temporary_failure",
                "error_type": type(error).__name__,
            },
        )
        raise ToolError(
            "[temporary_failure] FinPilot is temporarily unavailable; retry shortly."
        ) from None

    if count > config.read_calls_per_minute:
        retry_after = max(1, 60 - int(now % 60))
        raise ToolError(
            f"[rate_limited] Rate limit reached. Retry in about {retry_after} seconds."
        )
    return count


def register_tools(
    server: MCPServer,
    *,
    runtime: MCPRuntime,
    config: MCPSettings,
) -> None:
    @server.tool(
        name="list_my_companies",
        description=(
            "List the companies the authenticated FinPilot user belongs to, including "
            "their role, accounting currency, and available permissions."
        ),
        structured_output=True,
    )
    async def list_my_companies(ctx: Context) -> CompanyListResult:
        started = time.perf_counter()
        user_id: UUID | None = None
        try:
            async with AsyncSessionLocal() as db:
                user = await _load_user(db)
                user_id = user.id
                await _enforce_rate_limit(
                    runtime,
                    config,
                    user_id=user.id,
                    company_id=None,
                    tool_name="list_my_companies",
                )
                result = await db.execute(
                    select(
                        Company.id,
                        Company.name,
                        Company.currency_code,
                        CompanyMember.role,
                    )
                    .join(CompanyMember, CompanyMember.company_id == Company.id)
                    .where(CompanyMember.user_id == user.id)
                    .order_by(Company.name, Company.id)
                    .limit(MAX_COMPANIES_RETURNED + 1)
                )
                company_rows = list(result)
                truncated = len(company_rows) > MAX_COMPANIES_RETURNED
                companies = [
                    CompanySummary(
                        company_id=row.id,
                        name=row.name,
                        currency_code=row.currency_code,
                        role=row.role,
                        permissions=permissions_for_role(row.role),
                    )
                    for row in company_rows[:MAX_COMPANIES_RETURNED]
                ]
            logger.info(
                "MCP tool completed",
                extra={
                    "mcp_tool": "list_my_companies",
                    "mcp_request_id": str(ctx.request_context.request_id),
                    "user_id": str(user_id),
                    "outcome": "success",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return CompanyListResult(companies=companies, truncated=truncated)
        except ToolError as error:
            logger.info(
                "MCP tool rejected",
                extra={
                    "mcp_tool": "list_my_companies",
                    "mcp_request_id": str(ctx.request_context.request_id),
                    "user_id": str(user_id) if user_id else None,
                    "outcome": "error",
                    "error_code": _error_code(error),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        except Exception as error:
            logger.error(
                "MCP tool failed",
                extra={
                    "mcp_tool": "list_my_companies",
                    "user_id": str(user_id) if user_id else None,
                    "outcome": "error",
                    "error_code": "temporary_failure",
                    "error_type": type(error).__name__,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise ToolError(
                "[temporary_failure] FinPilot could not load your companies; retry shortly."
            ) from None

    @server.tool(
        name="get_cash_flow",
        description=(
            "Read FinPilot's deterministic cash-flow report for one company you belong to. "
            "Dates are inclusive, at most 366 days, and cash_balance is used only to estimate "
            "runway for this request; it is not saved."
        ),
        structured_output=True,
    )
    async def get_cash_flow(
        company_id: UUID,
        ctx: Context,
        start_date: date | None = None,
        end_date: date | None = None,
        granularity: Literal["day", "month"] = "month",
        cash_balance: Annotated[
            Decimal | None, Field(default=None, ge=0, max_digits=12, decimal_places=2)
        ] = None,
    ) -> CashFlowMetricsRead:
        return await _company_metric_tool(
            ctx,
            runtime=runtime,
            config=config,
            tool_name="get_cash_flow",
            company_id=company_id,
            operation=lambda db: _cash_flow_operation(
                db,
                company_id=company_id,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                cash_balance=cash_balance,
            ),
        )

    @server.tool(
        name="get_budget_vs_actual",
        description=(
            "Read FinPilot's deterministic monthly budget-versus-actual report for one "
            "company you belong to. Period must be a calendar month in YYYY-MM format."
        ),
        structured_output=True,
    )
    async def get_budget_vs_actual(
        company_id: UUID,
        period: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
        ctx: Context,
    ) -> BudgetVsActualRead:
        return await _company_metric_tool(
            ctx,
            runtime=runtime,
            config=config,
            tool_name="get_budget_vs_actual",
            company_id=company_id,
            operation=lambda db: calculate_budget_vs_actual(
                db, company_id=company_id, period=period
            ),
        )


async def _cash_flow_operation(
    db: AsyncSession,
    *,
    company_id: UUID,
    start_date: date | None,
    end_date: date | None,
    granularity: Literal["day", "month"],
    cash_balance: Decimal | None,
) -> CashFlowMetricsRead:
    try:
        resolved_start, resolved_end = resolve_cash_flow_range(start_date, end_date)
        validate_cash_balance(cash_balance)
    except ValueError as error:
        raise ToolError(f"[invalid_arguments] {error}") from error
    return await calculate_cash_flow_metrics(
        db,
        company_id=company_id,
        start_date=resolved_start,
        end_date=resolved_end,
        granularity=granularity,
        cash_balance=cash_balance,
    )


async def _company_metric_tool(
    ctx: Context,
    *,
    runtime: MCPRuntime,
    config: MCPSettings,
    tool_name: str,
    company_id: UUID,
    operation,
):
    started = time.perf_counter()
    user_id: UUID | None = None
    try:
        async with AsyncSessionLocal() as db:
            user = await _load_user(db)
            user_id = user.id
            await _require_company_membership(
                db, user_id=user.id, company_id=company_id
            )
            await _enforce_rate_limit(
                runtime,
                config,
                user_id=user.id,
                company_id=company_id,
                tool_name=tool_name,
            )
            result = await operation(db)
        logger.info(
            "MCP tool completed",
            extra={
                "mcp_tool": tool_name,
                "mcp_request_id": str(ctx.request_context.request_id),
                "user_id": str(user_id),
                "company_id": str(company_id),
                "outcome": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return result
    except ToolError as error:
        logger.info(
            "MCP tool rejected",
            extra={
                "mcp_tool": tool_name,
                "mcp_request_id": str(ctx.request_context.request_id),
                "user_id": str(user_id) if user_id else None,
                "company_id": str(company_id),
                "outcome": "error",
                "error_code": _error_code(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        raise
    except ValueError as error:
        logger.info(
            "MCP tool rejected",
            extra={
                "mcp_tool": tool_name,
                "mcp_request_id": str(ctx.request_context.request_id),
                "user_id": str(user_id) if user_id else None,
                "company_id": str(company_id),
                "outcome": "error",
                "error_code": "invalid_arguments",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        raise ToolError(f"[invalid_arguments] {error}") from None
    except Exception as error:
        logger.error(
            "MCP tool failed",
            extra={
                "mcp_tool": tool_name,
                "user_id": str(user_id) if user_id else None,
                "company_id": str(company_id),
                "outcome": "error",
                "error_code": "temporary_failure",
                "error_type": type(error).__name__,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        raise ToolError(
            "[temporary_failure] FinPilot could not load this financial report; retry shortly."
        ) from None
