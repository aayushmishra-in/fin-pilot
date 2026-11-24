"""Shared deterministic company metrics queries used by API and MCP entry points."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from sqlalchemy import Date, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget
from app.models.category import Category, CategoryKind
from app.models.transaction import Transaction
from app.schemas.metrics import BudgetVsActualRead, CashFlowMetricsRead
from app.services.cash_flow import build_cash_flow_report

MAX_RANGE_DAYS = 366
MAX_FINANCIAL_AMOUNT = Decimal("9999999999.99")
CENT = Decimal("0.01")


def resolve_cash_flow_range(
    start_date: date | None, end_date: date | None
) -> tuple[date, date]:
    """Resolve and bound an inclusive UTC date range for cash-flow metrics."""
    today_utc = datetime.now(UTC).date()
    resolved_end = end_date or today_utc
    default_start_ordinal = max(1, resolved_end.toordinal() - 364)
    resolved_start = start_date or date.fromordinal(default_start_ordinal)
    if resolved_end < resolved_start:
        raise ValueError("end_date must be on or after start_date")
    if (resolved_end - resolved_start).days >= MAX_RANGE_DAYS:
        raise ValueError("Date range cannot exceed 366 calendar days")
    return resolved_start, resolved_end


def validate_cash_balance(cash_balance: Decimal | None) -> None:
    """Enforce FinPilot's non-negative, finite, two-decimal amount contract."""
    if cash_balance is None:
        return
    if (
        not cash_balance.is_finite()
        or cash_balance < 0
        or cash_balance.as_tuple().exponent < -2
        or cash_balance > MAX_FINANCIAL_AMOUNT
    ):
        raise ValueError(
            "cash_balance must fit the supported two-decimal currency precision"
        )


async def calculate_cash_flow_metrics(
    db: AsyncSession,
    *,
    company_id: UUID,
    start_date: date,
    end_date: date,
    granularity: Literal["day", "month"],
    cash_balance: Decimal | None,
) -> CashFlowMetricsRead:
    """Query company-scoped aggregates and format them with the existing math."""
    period_start = (
        Transaction.date
        if granularity == "day"
        else func.date_trunc("month", Transaction.date).cast(Date)
    )
    inflows = func.sum(
        case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0.00"))
    ).label("inflows")
    outflows = func.sum(
        case((Transaction.amount < 0, -Transaction.amount), else_=Decimal("0.00"))
    ).label("outflows")
    result = await db.execute(
        select(
            period_start.label("period_start"),
            inflows,
            outflows,
            func.count(Transaction.id).label("transaction_count"),
        )
        .where(
            Transaction.company_id == company_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        .group_by(period_start)
        .order_by(period_start)
    )
    report = build_cash_flow_report(
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        grouped_rows=[
            (row.period_start, row.inflows, row.outflows, row.transaction_count)
            for row in result
        ],
        cash_balance=cash_balance,
    )
    return CashFlowMetricsRead.model_validate(report)


def _resolve_month(period: str) -> tuple[date, date]:
    if (
        len(period) != 7
        or period[4] != "-"
        or not period[:4].isdigit()
        or not period[5:].isdigit()
        or int(period[:4]) < 1
        or not 1 <= int(period[5:]) <= 12
    ):
        raise ValueError("period must be a valid YYYY-MM month")
    try:
        period_start = date(int(period[:4]), int(period[5:]), 1)
    except ValueError as error:
        raise ValueError("period must be a valid YYYY-MM month") from error
    period_end = date(
        period_start.year,
        period_start.month,
        calendar.monthrange(period_start.year, period_start.month)[1],
    )
    return period_start, period_end


async def calculate_budget_vs_actual(
    db: AsyncSession, *, company_id: UUID, period: str
) -> BudgetVsActualRead:
    """Query company-scoped budget and actual totals for one calendar month."""
    period_start, period_end = _resolve_month(period)
    budget_result = await db.execute(
        select(
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.kind.label("category_kind"),
            func.sum(Budget.limit_amount).label("budgeted_amount"),
        )
        .join(Category, Category.id == Budget.category_id)
        .where(
            Budget.company_id == company_id,
            Budget.period == period,
            (Category.company_id == company_id) | Category.company_id.is_(None),
        )
        .group_by(Category.id, Category.name, Category.kind)
        .order_by(Category.name, Category.id)
    )
    budget_rows = list(budget_result)
    category_ids = [row.category_id for row in budget_rows]
    actual_by_category: dict[UUID, tuple[Decimal, Decimal, int]] = {}
    if category_ids:
        actual_result = await db.execute(
            select(
                Transaction.category_id,
                func.sum(
                    case(
                        (Transaction.amount > 0, Transaction.amount),
                        else_=Decimal("0.00"),
                    )
                ).label("inflows"),
                func.sum(
                    case(
                        (Transaction.amount < 0, -Transaction.amount),
                        else_=Decimal("0.00"),
                    )
                ).label("outflows"),
                func.count(Transaction.id).label("transaction_count"),
            )
            .where(
                Transaction.company_id == company_id,
                Transaction.category_id.in_(category_ids),
                Transaction.date >= period_start,
                Transaction.date <= period_end,
            )
            .group_by(Transaction.category_id)
        )
        actual_by_category = {
            category_id: (inflows, outflows, count)
            for category_id, inflows, outflows, count in actual_result
        }

    items = []
    for row in budget_rows:
        inflows, outflows, transaction_count = actual_by_category.get(
            row.category_id, (Decimal("0.00"), Decimal("0.00"), 0)
        )
        actual_amount = (
            inflows if row.category_kind == CategoryKind.income else outflows
        )
        budgeted_amount = Decimal(row.budgeted_amount)
        utilization = (
            (actual_amount * Decimal("100") / budgeted_amount).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            if budgeted_amount > 0
            else None
        )
        items.append(
            {
                "category_id": row.category_id,
                "category_name": row.category_name,
                "category_kind": row.category_kind,
                "budgeted_amount": budgeted_amount,
                "actual_amount": actual_amount,
                "remaining_amount": budgeted_amount - actual_amount,
                "utilization_percent": utilization,
                "over_budget": actual_amount > budgeted_amount,
                "transaction_count": transaction_count,
            }
        )

    total_budgeted = sum(
        (item["budgeted_amount"] for item in items), Decimal("0.00")
    )
    total_actual = sum((item["actual_amount"] for item in items), Decimal("0.00"))
    return BudgetVsActualRead(
        period=period,
        total_budgeted=total_budgeted,
        total_actual=total_actual,
        total_remaining=total_budgeted - total_actual,
        items=items,
    )
