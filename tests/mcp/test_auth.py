from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.mcp.auth import SupabaseMCPTokenVerifier

pytestmark = pytest.mark.asyncio(loop_scope="session")

ISSUER = "https://auth.example.test/auth/v1"
RESOURCE = "https://api.example.test/mcp"
SIGNING_KEY = "mcp-test-signing-key-that-is-not-a-secret"


def _token(**claim_changes: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": str(uuid4()),
        "role": "authenticated",
        "client_id": "test-client",
        "finpilot_permissions": ["read"],
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(claim_changes)
    return jwt.encode(claims, SIGNING_KEY, algorithm="HS256")


def _verifier() -> SupabaseMCPTokenVerifier:
    return SupabaseMCPTokenVerifier(
        issuer=ISSUER,
        resource_url=RESOURCE,
        jwks_url="https://auth.example.test/auth/v1/.well-known/jwks.json",
        hs256_secret=SIGNING_KEY,
    )


async def test_accepts_only_signed_mcp_read_tokens() -> None:
    access_token = await _verifier().verify_token(_token())

    assert access_token is not None
    assert access_token.subject is not None
    assert access_token.resource == RESOURCE
    assert access_token.client_id == "test-client"
    assert access_token.claims == {
        "iss": ISSUER,
        "finpilot_permissions": ["read"],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "authenticated"},
        {"aud": [RESOURCE, "authenticated"]},
        {"iss": "https://attacker.example.test/auth/v1"},
        {"role": "anon"},
        {"finpilot_permissions": []},
        {"finpilot_permissions": "read"},
        {"sub": "not-a-uuid"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
async def test_rejects_tokens_outside_the_mcp_boundary(
    changes: dict[str, object],
) -> None:
    assert await _verifier().verify_token(_token(**changes)) is None
