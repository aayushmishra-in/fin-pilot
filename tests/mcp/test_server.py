from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import jwt
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import TokenVerifier

from app.core.config import settings as finpilot_settings
from app.mcp.auth import SupabaseMCPTokenVerifier
from app.mcp.runtime import MCPRuntime
from app.mcp.server import build_mcp_bundle
from app.mcp.settings import MCPSettings
from app.models.category import CategoryKind
from app.models.company_member import CompanyRole

RESOURCE = "http://localhost:8000/mcp"
SIGNING_KEY = "mcp-test-signing-key-that-is-not-a-secret"


def _bundle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(finpilot_settings, "supabase_url", "https://auth.example.test")
    issuer = "https://auth.example.test/auth/v1"
    verifier: TokenVerifier = SupabaseMCPTokenVerifier(
        issuer=issuer,
        resource_url=RESOURCE,
        jwks_url="https://auth.example.test/auth/v1/.well-known/jwks.json",
        hs256_secret=SIGNING_KEY,
    )
    return build_mcp_bundle(
        MCPSettings(enabled=True, public_url=RESOURCE),
        token_verifier=verifier,
    )


def _bearer() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://auth.example.test/auth/v1",
            "aud": RESOURCE,
            "sub": str(uuid4()),
            "role": "authenticated",
            "client_id": "test-client",
            "finpilot_permissions": ["read"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class _FakeSession:
    def __init__(self, auth_user_id, user_id, company_id) -> None:
        self.auth_user_id = auth_user_id
        self.user_id = user_id
        self.company_id = company_id
        self.scalar_calls = 0
        self.execute_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False

    async def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return SimpleNamespace(id=self.user_id, auth_user_id=self.auth_user_id)
        return SimpleNamespace(user_id=self.user_id, company_id=self.company_id)

    async def execute(self, statement):
        self.execute_calls += 1
        if self.scalar_calls == 1:
            return [
                SimpleNamespace(
                    id=self.company_id,
                    name="Demo Company",
                    currency_code="USD",
                    role=CompanyRole.owner,
                )
            ]
        if "budgets" in str(statement).lower():
            category_id = uuid4()
            self.category_id = category_id
            return [
                SimpleNamespace(
                    category_id=category_id,
                    category_name="Office",
                    category_kind=CategoryKind.expense,
                    budgeted_amount=Decimal("80.00"),
                )
            ]
        if self.execute_calls == 2:
            return [
                (
                    self.category_id,
                    Decimal("0.00"),
                    Decimal("40.00"),
                    1,
                )
            ]
        return [
            SimpleNamespace(
                period_start=date(2026, 1, 1),
                inflows=Decimal("100.00"),
                outflows=Decimal("50.00"),
                transaction_count=2,
            )
        ]


async def test_authenticated_tools_call_shared_finpilot_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_user_id = uuid4()
    user_id = uuid4()
    company_id = uuid4()

    import app.mcp.tools as mcp_tools

    monkeypatch.setattr(
        mcp_tools,
        "AsyncSessionLocal",
        lambda: _FakeSession(auth_user_id, user_id, company_id),
    )
    bundle = _bundle(monkeypatch)
    bundle.runtime.redis = _FakeRedis()
    transport = httpx2.ASGITransport(
        app=bundle.http_app,
        client=("127.0.0.1", 12345),
    )
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {_bearer_with_subject(auth_user_id)}"},
        trust_env=False,
    ) as http_client:
        async with bundle.server.session_manager.run():
            async with streamable_http_client(
                RESOURCE, http_client=http_client
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    companies = await client.call_tool("list_my_companies")
                    cash_flow = await client.call_tool(
                        "get_cash_flow",
                        arguments={
                            "company_id": str(company_id),
                            "start_date": "2026-01-01",
                            "end_date": "2026-01-01",
                        },
                    )
                    budget = await client.call_tool(
                        "get_budget_vs_actual",
                        arguments={
                            "company_id": str(company_id),
                            "period": "2026-01",
                        },
                    )

    assert companies.is_error is False
    assert companies.structured_content["companies"][0]["name"] == "Demo Company"
    assert companies.structured_content["truncated"] is False
    assert cash_flow.is_error is False
    assert cash_flow.structured_content["net_cash_flow"] == "50.00"
    assert cash_flow.structured_content["transaction_count"] == 2
    assert budget.is_error is False
    assert budget.structured_content["total_budgeted"] == "80.00"
    assert budget.structured_content["total_actual"] == "40.00"
    assert budget.structured_content["items"][0]["category_name"] == "Office"


def _bearer_with_subject(auth_user_id) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "https://auth.example.test/auth/v1",
            "aud": RESOURCE,
            "sub": str(auth_user_id),
            "role": "authenticated",
            "client_id": "test-client",
            "finpilot_permissions": ["read"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SIGNING_KEY,
        algorithm="HS256",
    )


async def test_streamable_http_auth_metadata_and_tool_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(monkeypatch)
    transport = httpx2.ASGITransport(
        app=bundle.http_app,
        client=("127.0.0.1", 12345),
    )
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://localhost:8000",
        trust_env=False,
    ) as http_client:
        async with bundle.server.session_manager.run():
            preflight = await http_client.options(
                "/mcp",
                headers={
                    "Origin": "http://localhost:6274",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,mcp-protocol-version",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "http://localhost:6274"

            challenge = await http_client.get("/mcp")
            assert challenge.status_code == 401
            assert "oauth-protected-resource" in challenge.headers["www-authenticate"]

            metadata = await http_client.get(
                "/.well-known/oauth-protected-resource/mcp"
            )
            assert metadata.status_code == 200
            assert metadata.json() == {
                "resource": RESOURCE,
                "authorization_servers": ["https://auth.example.test/auth/v1"],
                "bearer_methods_supported": ["header"],
            }

            http_client.headers["Authorization"] = f"Bearer {_bearer()}"
            async with streamable_http_client(
                RESOURCE, http_client=http_client
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    tools = await client.list_tools()

            assert {tool.name for tool in tools.tools} == {
                "list_my_companies",
                "get_cash_flow",
                "get_budget_vs_actual",
            }
            cash_flow = next(tool for tool in tools.tools if tool.name == "get_cash_flow")
            assert cash_flow.input_schema["required"] == ["company_id"]
            assert "ctx" not in cash_flow.input_schema["properties"]


