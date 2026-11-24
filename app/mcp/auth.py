"""Supabase JWT validation for tokens issued specifically to the MCP resource."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)


class SupabaseMCPTokenVerifier(TokenVerifier):
    """Verify signed Supabase access tokens with an MCP audience and read claim.

    This verifier intentionally does not accept the ordinary ``authenticated``
    audience. A Custom Access Token Hook must add the exact MCP resource URL to
    ``aud`` and ``finpilot_permissions: ["read"]`` for an approved OAuth client.
    """

    def __init__(
        self,
        *,
        issuer: str,
        resource_url: str,
        jwks_url: str,
        hs256_secret: str | None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.resource_url = resource_url.rstrip("/")
        self.hs256_secret = hs256_secret
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(self._decode_token, token)
        except (PyJWTError, ValueError, TypeError, KeyError) as error:
            logger.info(
                "MCP bearer token rejected",
                extra={"error_type": type(error).__name__},
            )
            return None
        except Exception as error:
            # JWKS/network failures fail closed without exposing token material.
            logger.warning(
                "MCP bearer verification temporarily unavailable",
                extra={"error_type": type(error).__name__},
            )
            return None

        subject = claims["sub"]
        aud = claims["aud"]
        resource = self.resource_url
        if isinstance(aud, list) and aud != [resource]:
            return None
        if isinstance(aud, str) and aud != resource:
            return None

        raw_scopes = claims.get("scope", "")
        scopes = raw_scopes.split() if isinstance(raw_scopes, str) else []
        client_id = claims.get("client_id") or claims.get("azp") or "supabase-oauth"
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=resource,
            subject=str(subject),
            claims={"iss": self.issuer, "finpilot_permissions": ["read"]},
        )

    def _decode_token(self, token: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm == "HS256":
            if not self.hs256_secret:
                raise PyJWTError("HS256 verification is not configured")
            key: Any = self.hs256_secret
        elif algorithm in {"RS256", "ES256"}:
            key = self._jwks_client.get_signing_key_from_jwt(token).key
        else:
            raise PyJWTError("Unsupported token algorithm")

        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=self.resource_url,
            issuer=self.issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        try:
            UUID(claims["sub"])
        except (ValueError, TypeError, KeyError) as error:
            raise PyJWTError("Invalid subject") from error
        if claims.get("role") != "authenticated":
            raise PyJWTError("Token is not for an authenticated user")
        permissions = claims.get("finpilot_permissions")
        if not isinstance(permissions, list) or "read" not in permissions:
            raise PyJWTError("Read permission is missing")
        return claims
