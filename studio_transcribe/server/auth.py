"""Simple shared-password auth.

If the password env var (``config.server.password_env``) is set, every ``/api``
call must carry it as an ``X-Auth-Token`` header (or ``?token=`` for the
WebSocket). If the env var is empty, auth is disabled — the intended mode when
the server is bound to localhost only.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, status


def expected_password(config) -> str:
    return os.environ.get(config.server.password_env, "")


def make_auth_dependency(config):
    password = expected_password(config)

    async def require_auth(x_auth_token: str = Header(default="")) -> None:
        if not password:
            return
        if x_auth_token != password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="bad or missing token"
            )

    return require_auth


def token_ok(config, token: str) -> bool:
    password = expected_password(config)
    return (not password) or (token == password)
