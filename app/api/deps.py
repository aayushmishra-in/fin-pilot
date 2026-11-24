import logging
import uuid
from collections.abc import AsyncGenerator

from arq import ArqRedis
from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.permissions import Permission, ROLE_PERMISSIONS
from app.core.security import get_supabase_user, verify_supabase_access_token
from app.models import CompanyMember, User

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_arq_redis(request: Request) -> ArqRedis:
    return request.app.state.redis


async def get_verified_token_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, object]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception
    try:
        return await verify_supabase_access_token(credentials.credentials)
    except Exception as error:
        logger.warning(
            "Supabase access token verification rejected",
            extra={
                "error_type": type(error).__name__,
                "error_message": str(error)[:500],
            },
        )
        raise credentials_exception from None


async def get_current_user(
    claims: dict[str, object] = Depends(get_verified_token_claims),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    auth_user_id = claims.get("sub")
    email = claims.get("email")
    if not isinstance(auth_user_id, str) or not isinstance(email, str) or not email:
        logger.warning("Supabase access token is missing required identity claims")
        raise credentials_exception

    try:
        auth_uuid = uuid.UUID(auth_user_id)
    except ValueError:
        logger.warning("Supabase access token has an invalid subject claim")
        raise credentials_exception from None

    result = await db.execute(select(User).where(User.auth_user_id == auth_uuid))
    user = result.scalar_one_or_none()
    if user is not None:
        user_metadata = claims.get("user_metadata")
        user_metadata = user_metadata if isinstance(user_metadata, dict) else {}
        full_name = user_metadata.get("full_name") or user_metadata.get("name")
        avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
        if isinstance(full_name, str) and full_name.strip():
            user.full_name = full_name.strip()[:255]
        if isinstance(avatar_url, str):
            user.avatar_url = avatar_url[:2048]
        normalized_email = email.strip().casefold()
        if user.email != normalized_email:
            collision = await db.scalar(
                select(User.id).where(
                    User.email == normalized_email,
                    User.id != user.id,
                )
            )
            if collision is None:
                user.email = normalized_email
        await db.commit()
        await db.refresh(user)
        return user

    user_metadata = claims.get("user_metadata")
    user_metadata = user_metadata if isinstance(user_metadata, dict) else {}
    full_name = user_metadata.get("full_name") or user_metadata.get("name")
    avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
    if not isinstance(full_name, str):
        full_name = None
    if not full_name or not full_name.strip():
        full_name = email.split("@", 1)[0].strip() or "FinPilot user"
    full_name = full_name.strip()[:255]
    if not isinstance(avatar_url, str):
        avatar_url = None
    if avatar_url is not None:
        avatar_url = avatar_url[:2048]

    try:
        user = User(
            auth_user_id=auth_uuid,
            email=email.strip().casefold(),
            full_name=full_name,
            avatar_url=avatar_url,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(User).where(User.auth_user_id == auth_uuid))
        user = result.scalar_one_or_none()
        if user is None:
            normalized_email = email.strip().casefold()
            legacy_user = await db.scalar(
                select(User).where(
                    User.email == normalized_email,
                    User.auth_user_id.is_(None),
                )
            )
            if (
                legacy_user is not None
                and credentials is not None
                and _supabase_email_is_confirmed(
                    await get_supabase_user(credentials.credentials),
                    expected_id=auth_uuid,
                    expected_email=normalized_email,
                )
            ):
                legacy_user.auth_user_id = auth_uuid
                await db.commit()
                await db.refresh(legacy_user)
                return legacy_user
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A local account already uses this email. Automatic linking requires a confirmed Supabase email.",
            ) from None

    return user


def _supabase_email_is_confirmed(
    auth_user: dict[str, object], *, expected_id: uuid.UUID, expected_email: str
) -> bool:
    confirmed_at = auth_user.get("email_confirmed_at") or auth_user.get("confirmed_at")
    auth_email = auth_user.get("email")
    try:
        returned_id = uuid.UUID(str(auth_user.get("id")))
    except ValueError:
        return False
    return (
        returned_id == expected_id
        and isinstance(auth_email, str)
        and auth_email.strip().casefold() == expected_email
        and isinstance(confirmed_at, str)
        and bool(confirmed_at.strip())
    )


async def get_current_company_member(
    company_id: uuid.UUID = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyMember:
    result = await db.execute(
        select(CompanyMember).where(
            CompanyMember.company_id == company_id,
            CompanyMember.user_id == current_user.id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this company",
        )

    return membership


def require_permission(permission: Permission | str):
    required_permission = Permission(permission)

    async def role_checker(
        member: CompanyMember = Depends(get_current_company_member),
    ) -> CompanyMember:
        if required_permission not in ROLE_PERMISSIONS[member.role]:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to perform this action",
            )
        return member

    return role_checker


def require_any_permission(*permissions: Permission | str):
    required = frozenset(Permission(permission) for permission in permissions)

    async def permission_checker(
        member: CompanyMember = Depends(get_current_company_member),
    ) -> CompanyMember:
        if not (required & ROLE_PERMISSIONS[member.role]):
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to perform this action",
            )
        return member

    return permission_checker
