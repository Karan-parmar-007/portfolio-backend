"""Authorisation guards — thin adapters over the shared `karan_sso` SDK.

Route files keep importing `require_owner` / `OwnerDep` from here. All token
verification (JWKS / RS256, legacy HS256 during rollout), live role checks
(SSO `/auth/me` with a bearer token, cached briefly) and error mapping live in
`karan_sso`: missing/invalid token → 401, wrong role → 403, SSO outage → 503.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from fastapi import Request
from karan_sso import SsoIdentity
from karan_sso.fastapi import (
    IdentityDep,
    OptionalIdentityDep,
    OwnerDep,
    require_owner,
)
from karan_sso.fastapi import require_role as _sdk_require_role

__all__ = [
    "IdentityDep",
    "OptionalIdentityDep",
    "OwnerDep",
    "SsoIdentity",
    "require_owner",
    "require_role",
]


def require_role(
    required_roles: str | Sequence[str],
) -> Callable[[Request], Awaitable[SsoIdentity]]:
    """Dependency factory: require one of the given global SSO roles (live).

    Pass a single role (`"owner"`) or a list (`["owner", "super_admin"]`).
    """
    names = [required_roles] if isinstance(required_roles, str) else list(required_roles)
    return _sdk_require_role(*names)
