from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.api.all_dependencies.owner_required import SessionIdentityDep
from app.api.auth_cookies import CSRF_HEADER_NAME, CSRF_TOKEN_COOKIE
from app.api.routes.auth.auth_schemas import SessionResponse, TokenProxyResponse
from app.config import auth_settings
from app.core.errors import UnauthorizedError
from app.utils.sso_client import cookie_header_from_request, proxy_sso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _forward_set_cookies(upstream: object, response: Response) -> None:
    """Copy Set-Cookie headers from an httpx response onto the FastAPI response."""
    headers = getattr(upstream, "headers", None)
    if headers is None:
        return
    get_list = getattr(headers, "get_list", None)
    if callable(get_list):
        values = get_list("set-cookie")
    else:
        raw = headers.get("set-cookie")
        values = [raw] if raw else []
    for value in values:
        if value:
            response.headers.append("set-cookie", value)


@router.get("/session", response_model=SessionResponse)
async def get_session(identity: SessionIdentityDep) -> SessionResponse:
    """Always 200 — never 401, so anonymous loads do not trip refresh loops.

    Identity comes from local JWT; is_owner / role_name from live SSO /auth/me.
    """
    if identity is None:
        return SessionResponse(
            authenticated=False,
            is_owner=False,
            email=None,
            user_id=None,
            role_name=None,
            name=None,
        )
    return SessionResponse(
        authenticated=True,
        is_owner=identity.is_owner,
        email=identity.email,
        user_id=identity.user_id,
        role_name=identity.role_name,
        name=identity.name,
    )


@router.post("/refresh", response_model=TokenProxyResponse)
async def refresh_session(request: Request) -> Response:
    """Proxy SSO refresh. Browser hits this path so Path=/api/auth cookies apply."""
    cookie_header = request.headers.get("cookie") or cookie_header_from_request(
        dict(request.cookies)
    )
    csrf = request.headers.get(CSRF_HEADER_NAME) or request.cookies.get(
        CSRF_TOKEN_COOKIE
    )
    try:
        upstream = await proxy_sso(
            "POST",
            "/auth/refresh",
            cookie_header=cookie_header,
            csrf_token=csrf,
        )
    except UnauthorizedError as exc:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    body: dict
    try:
        body = upstream.json()
    except ValueError:
        body = {"message": upstream.text or "Token refresh failed"}

    if upstream.status_code >= 400:
        response = JSONResponse(
            status_code=upstream.status_code,
            content={"detail": body.get("detail") or body.get("message") or "Refresh failed"},
        )
        _forward_set_cookies(upstream, response)
        return response

    response = JSONResponse(
        status_code=200,
        content={
            "access_token_expires_in": body.get("access_token_expires_in"),
            "message": body.get("message") or "Token refreshed successfully",
        },
    )
    _forward_set_cookies(upstream, response)
    return response


@router.post("/logout", response_model=TokenProxyResponse)
async def logout_session(request: Request) -> Response:
    """Proxy SSO logout and forward Set-Cookie clears."""
    cookie_header = request.headers.get("cookie") or cookie_header_from_request(
        dict(request.cookies)
    )
    csrf = request.headers.get(CSRF_HEADER_NAME) or request.cookies.get(
        CSRF_TOKEN_COOKIE
    )
    try:
        upstream = await proxy_sso(
            "POST",
            "/auth/logout",
            cookie_header=cookie_header,
            csrf_token=csrf,
        )
    except UnauthorizedError as exc:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    body: dict
    try:
        body = upstream.json()
    except ValueError:
        body = {"message": upstream.text or "Logged out"}

    # Always clear cookies on the client even if SSO returned an error
    status_code = 200 if upstream.status_code < 500 else upstream.status_code
    response = JSONResponse(
        status_code=status_code,
        content={
            "message": body.get("message") or body.get("detail") or "Logged out successfully",
            "access_token_expires_in": None,
        },
    )
    _forward_set_cookies(upstream, response)
    if not any(k.lower() == "set-cookie" for k in response.headers.keys()):
        # Fallback clear if SSO did not return Set-Cookie (e.g. already logged out)
        is_prod = auth_settings.ENVIRONMENT == "production"
        response.delete_cookie(
            key=auth_settings.ACCESS_TOKEN_COOKIE_NAME,
            path="/",
            secure=is_prod,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            key=auth_settings.CSRF_COOKIE_NAME,
            path="/",
            secure=is_prod,
            httponly=False,
            samesite="lax",
        )
        response.delete_cookie(
            key="refresh_token",
            path="/api/auth",
            secure=is_prod,
            httponly=True,
            samesite="lax",
        )
    return response
