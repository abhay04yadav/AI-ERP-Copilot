from collections.abc import Generator
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.audit import actor_user_id_ctx
from app.core.db import SessionLocal
from app.core.exceptions import UnauthorizedException
from app.core.logging import tenant_id_ctx
from app.core.rls import set_tenant_context
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class CurrentUser:
    def __init__(self, user_id: UUID, tenant_id: UUID, role: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> CurrentUser:
    if token is None:
        raise UnauthorizedException()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise UnauthorizedException("Invalid or expired token.")
    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type.")
    return CurrentUser(
        user_id=UUID(payload["sub"]),
        tenant_id=UUID(payload["tenant_id"]),
        role=payload["role"],
    )


def get_tenant_session(current_user: CurrentUser = Depends(get_current_user)) -> Generator[Session, None, None]:
    """Opens a session and, inside its transaction, sets the RLS tenant context
    from the verified JWT — never from a header, query param, or file (spec §4.3).

    Deliberately doesn't reset actor_user_id_ctx/tenant_id_ctx via a saved
    Token: sync generator dependencies can run their pre- and post-yield
    halves in different worker threads (FastAPI/anyio thread-pool offloading),
    so a Token minted in one thread can't be used to reset a ContextVar in
    another ("was created in a different Context"). Each request sets fresh
    values before using them, so not resetting only risks a stale value
    leaking into logs/audit between requests on a reused thread — a cosmetic
    issue for these log/audit-only contextvars, not a correctness one.
    """
    session = SessionLocal()
    actor_user_id_ctx.set(str(current_user.user_id))
    tenant_id_ctx.set(str(current_user.tenant_id))
    try:
        with session.begin():
            set_tenant_context(session, current_user.tenant_id)
            yield session
    finally:
        session.close()
