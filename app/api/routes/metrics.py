from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_company_member, get_db
from app.models.company_member import CompanyMember
from app.models.invoice import Invoice, ProcessingStatus
from app.schemas.metrics import (
    BudgetVsActualRead,
    CashFlowMetricsRead,
    InvoiceDocumentCountsRead,
)
from app.services.metrics import (
    calculate_budget_vs_actual,
    calculate_cash_flow_metrics,
    resolve_cash_flow_range,
    validate_cash_balance,
)

router = APIRouter(prefix="/companies/{company_id}/metrics", tags=["metrics"])


@router.get("/documents", response_model=InvoiceDocumentCountsRead)
async def get_invoice_document_counts(
    company_id: UUID,
    membership: CompanyMember = Depends(get_current_company_member),
    db: AsyncSession = Depends(get_db),
) -> InvoiceDocumentCountsRead:
    pending_states = (ProcessingStatus.pending, ProcessingStatus.processing)
    result = await db.execute(
        select(
            func.count(Invoice.id).label("total"),
            func.count(case((Invoice.processing_status.in_(pending_states), 1))).label(
                "processing"
            ),
            func.count(
                case(
                    (
                        (Invoice.processing_status == ProcessingStatus.complete)
                        & Invoice.confirmed_at.is_(None),
                        1,
                    )
                )
            ).label("awaiting_review"),
            func.count(case((Invoice.confirmed_at.is_not(None), 1))).label(
                "confirmed"
            ),
            func.count(
                case((Invoice.processing_status == ProcessingStatus.failed, 1))
            ).label("failed"),
        ).where(Invoice.company_id == company_id)
    )
    return InvoiceDocumentCountsRead.model_validate(result.one()._mapping)


@router.get("/cash-flow", response_model=CashFlowMetricsRead)
async def get_cash_flow_metrics(
    company_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: Literal["day", "month"] = "month",
    cash_balance: Decimal | None = Query(default=None, ge=0),
    membership: CompanyMember = Depends(get_current_company_member),
    db: AsyncSession = Depends(get_db),
) -> CashFlowMetricsRead:
    try:
        resolved_start, resolved_end = resolve_cash_flow_range(start_date, end_date)
        validate_cash_balance(cash_balance)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await calculate_cash_flow_metrics(
        db,
        company_id=company_id,
        start_date=resolved_start,
        end_date=resolved_end,
        granularity=granularity,
        cash_balance=cash_balance,
    )


@router.get("/budget-vs-actual", response_model=BudgetVsActualRead)
async def get_budget_vs_actual(
    company_id: UUID,
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    membership: CompanyMember = Depends(get_current_company_member),
    db: AsyncSession = Depends(get_db),
) -> BudgetVsActualRead:
    try:
        return await calculate_budget_vs_actual(
            db, company_id=company_id, period=period
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="period must be a valid YYYY-MM month") from error
