from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.core.db import AsyncSessionLocal
from app.mcp.tools import _require_company_membership

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_membership_helper_denies_cross_company_access(actor_factory) -> None:
    first = await actor_factory("owner")
    second = await actor_factory("owner")
    async with AsyncSessionLocal() as db:
        membership = await _require_company_membership(
            db, user_id=first.user_id, company_id=first.company_id
        )
        assert str(membership.company_id) == str(first.company_id)

        with pytest.raises(ToolError, match="company_access_denied"):
            await _require_company_membership(
                db, user_id=second.user_id, company_id=first.company_id
            )
