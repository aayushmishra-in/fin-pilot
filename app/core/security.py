import asyncio
import json
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWTError

from app.core.config import settings

@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is required to validate access tokens")
    return PyJWKClient(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
        lifespan=300,
        timeout=5,
    )


def _decode_supabase_token(token: str) -> dict[str, object]:
    issuer = f"{(settings.supabase_url or '').rstrip('/')}/auth/v1"
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")
    if algorithm == "HS256":
        if settings.supabase_jwt_secret is None:
            raise PyJWTError("SUPABASE_JWT_SECRET is required for HS256 tokens")
        key = settings.supabase_jwt_secret.get_secret_value()
    elif algorithm in {"RS256", "ES256"}:
        key = _jwks_client().get_signing_key_from_jwt(token).key
    else:
        raise PyJWTError("Unsupported Supabase JWT algorithm")

    claims = jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        audience="authenticated",
        issuer=issuer,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    try:
        UUID(claims["sub"])
    except (ValueError, TypeError, KeyError) as error:
        raise PyJWTError("Invalid subject") from error
    if claims.get("role") != "authenticated":
        raise PyJWTError("Token is not for an authenticated user")
    return claims


async def verify_supabase_access_token(token: str) -> dict[str, object]:
    return await asyncio.to_thread(_decode_supabase_token, token)


def _get_supabase_user(access_token: str) -> dict[str, object]:
    if not settings.supabase_url or settings.supabase_anon_key is None:
        return {}

    request = Request(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
        headers={
            "apikey": settings.supabase_anon_key.get_secret_value(),
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


async def get_supabase_user(access_token: str) -> dict[str, object]:
    """Fetch trusted Auth user fields that are not present in the access JWT."""
    return await asyncio.to_thread(_get_supabase_user, access_token)
