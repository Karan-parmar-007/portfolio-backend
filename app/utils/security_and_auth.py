from __future__ import annotations

from typing import Any

from jose import JWTError, jwt

from app.config import auth_settings
from app.core.errors import UnauthorizedError


def decode_sso_access_token(token: str) -> dict[str, Any]:
    """Decode an SSO access token. Raises UnauthorizedError on any problem.

    Do not pass audience= or issuer= — SSO tokens carry neither claim.
    """
    try:
        payload = jwt.decode(
            token,
            auth_settings.SSO_JWT_SECRET,
            algorithms=[auth_settings.SSO_JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired session") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")
    if not payload.get("email"):
        raise UnauthorizedError("Token missing email claim")
    return payload
