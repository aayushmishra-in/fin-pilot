from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.runtime import MCPRuntime
from app.mcp.settings import MCPSettings
from app.mcp.tools import _enforce_rate_limit
from app.services.metrics import (
    _resolve_month,
    resolve_cash_flow_range,
    validate_cash_balance,
)

class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True


async def test_mcp_rate_limit_is_separate_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.mcp.tools.time.time", lambda: 120.0)
    config = MCPSettings(read_calls_per_minute=1)
    fake_redis = FakeRedis()
    runtime = MCPRuntime(redis=fake_redis)
    user_id = uuid4()
    company_id = uuid4()

    assert await _enforce_rate_limit(
        runtime,
        config,
        user_id=user_id,
        company_id=company_id,
        tool_name="get_cash_flow",
    ) == 1
    assert any(key.startswith("mcp:v1:") for key in fake_redis.counters)

    with pytest.raises(ToolError, match="rate_limited"):
        await _enforce_rate_limit(
            runtime,
            config,
            user_id=user_id,
            company_id=company_id,
            tool_name="get_cash_flow",
        )

    with pytest.raises(ToolError, match="temporary_failure"):
        await _enforce_rate_limit(
            MCPRuntime(),
            config,
            user_id=user_id,
            company_id=company_id,
            tool_name="get_cash_flow",
        )


def test_shared_metrics_validation_preserves_finpilot_bounds() -> None:
    start, end = resolve_cash_flow_range(date(2026, 1, 1), date(2027, 1, 1))
    assert (end - start).days == 365

    with pytest.raises(ValueError, match="366 calendar days"):
        resolve_cash_flow_range(date(2025, 12, 31), date(2027, 1, 1))

    validate_cash_balance(Decimal("0.00"))
    with pytest.raises(ValueError, match="two-decimal"):
        validate_cash_balance(Decimal("0.001"))

    assert _resolve_month("9999-12") == (date(9999, 12, 1), date(9999, 12, 31))
    with pytest.raises(ValueError, match="valid YYYY-MM"):
        _resolve_month("0000-01")
