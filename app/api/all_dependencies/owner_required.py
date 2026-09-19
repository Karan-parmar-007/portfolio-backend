from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.auth_cookies import ACCESS_TOKEN_COOKIE
from app.core.errors import ForbiddenError, UnauthorizedError
from app.utils.security_and_auth import decode_sso_access_token
from app.utils.sso_client import cookie_header_from_request, fetch_sso_me, is_owner_role

logger = logging.getLogger(__name__)


class SsoIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    email: str
    is_owner: bool
    role_name: str | None = None
    name: str | None = None


def _extract_token(request: Request) -> str | None:
    """Cookie wins; Authorization Bearer is a fallback for curl/tests."""
    raw = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if raw:
        return raw
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _identity_from_jwt(payload: dict) -> SsoIdentity:
    """Identity from local JWT only — role is never trusted from the token."""
    email = str(payload["email"])
    user_id = str(payload.get("user_id") or payload.get("sub") or "")
    return SsoIdentity(
        user_id=user_id,
        email=email,
        is_owner=False,
        role_name=None,
        name=None,
    )


async def _live_role_identity(request: Request, base: SsoIdentity) -> SsoIdentity:
    """Attach live role_name from SSO Mongo via GET /auth/me."""
    cookie_header = request.headers.get("cookie") or cookie_header_from_request(
        dict(request.cookies)
    )
    me = await fetch_sso_me(cookie_header=cookie_header)
    if me is None:
        return base
    role_name = me.get("role_name")
    role_str = str(role_name).strip() if role_name is not None else None
    raw_name = me.get("name")
    name_str = str(raw_name).strip() if raw_name else None
    return SsoIdentity(
        user_id=base.user_id,
        email=base.email,
        is_owner=is_owner_role(role_str),
        role_name=role_str or None,
        name=name_str or None,
    )


async def get_optional_identity(request: Request) -> SsoIdentity | None:
    """Local JWT decode only. Does not call SSO (session route does that)."""
    raw = _extract_token(request)
    if not raw:
        return None
    try:
        payload = decode_sso_access_token(raw)
    except UnauthorizedError:
        return None
    return _identity_from_jwt(payload)


async def get_session_identity(request: Request) -> SsoIdentity | None:
    """JWT identity + live SSO role for GET /auth/session."""
    base = await get_optional_identity(request)
    if base is None:
        return None
    return await _live_role_identity(request, base)


async def require_owner(request: Request) -> SsoIdentity:
    raw = _extract_token(request)
    if not raw:
        raise UnauthorizedError("Not authenticated")
    payload = decode_sso_access_token(raw)
    base = _identity_from_jwt(payload)
    identity = await _live_role_identity(request, base)
    if not identity.is_owner:
        logger.warning(
            "Non-owner admin attempt by %s role=%s",
            identity.email,
            identity.role_name,
        )
        raise ForbiddenError("Owner access required")
    return identity


def _normalize_roles(required_roles: str | Sequence[str]) -> list[str]:
    names = [required_roles] if isinstance(required_roles, str) else list(required_roles)
    allowed = [n.strip().lower() for n in names if n and str(n).strip()]
    if not allowed:
        raise ValueError("require_role needs at least one role name")
    return allowed


def require_role(required_roles: str | Sequence[str]):
    """Dependency factory: require one of the given SSO roles.

    Pass a single role (`"owner"`) or a list (`["owner", "super_admin"]`).
    """
    allowed = _normalize_roles(required_roles)

    async def _dependency(request: Request) -> SsoIdentity:
        raw = _extract_token(request)
        if not raw:
            raise UnauthorizedError("Not authenticated")
        payload = decode_sso_access_token(raw)
        base = _identity_from_jwt(payload)
        identity = await _live_role_identity(request, base)
        current = (identity.role_name or "").strip().lower()
        if current in allowed:
            return identity
        logger.warning(
            "Role-gated admin attempt by %s role=%s allowed=%s",
            identity.email,
            identity.role_name,
            allowed,
        )
        needed = "', '".join(allowed)
        raise ForbiddenError(f"One of these roles required: '{needed}'")

    return _dependency


type OptionalIdentityDep = Annotated[
    SsoIdentity | None, Depends(get_optional_identity)
]
type SessionIdentityDep = Annotated[
    SsoIdentity | None, Depends(get_session_identity)
]
type OwnerDep = Annotated[SsoIdentity, Depends(require_owner)]
