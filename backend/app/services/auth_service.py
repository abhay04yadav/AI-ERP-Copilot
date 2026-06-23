import jwt
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.rls import set_tenant_context
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse


def register_tenant_and_admin(session: Session, payload: RegisterRequest) -> TokenResponse:
    tenant_repo = TenantRepository(session)
    if tenant_repo.get_by_slug(payload.tenant_slug) is not None:
        raise ConflictException("A tenant with this slug already exists.")

    tenant = tenant_repo.add(Tenant(name=payload.tenant_name, slug=payload.tenant_slug))
    session.flush()  # assign tenant.id

    set_tenant_context(session, tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=payload.admin_email,
        password_hash=hash_password(payload.admin_password),
        role="admin",
    )
    session.add(user)
    session.flush()  # assign user.id

    return TokenResponse(
        access_token=create_access_token(user.id, tenant.id, user.role),
        refresh_token=create_refresh_token(user.id, tenant.id, user.role),
    )


def login(session: Session, tenant_slug: str, email: str, password: str) -> TokenResponse:
    tenant = TenantRepository(session).get_by_slug(tenant_slug)
    if tenant is None or not tenant.is_active:
        raise UnauthorizedException("Invalid credentials.")

    set_tenant_context(session, tenant.id)
    user = UserRepository(session, tenant.id).get_by_email(email)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise UnauthorizedException("Invalid credentials.")

    return TokenResponse(
        access_token=create_access_token(user.id, tenant.id, user.role),
        refresh_token=create_refresh_token(user.id, tenant.id, user.role),
    )


def refresh(session: Session, refresh_token: str) -> TokenResponse:
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError as exc:
        raise UnauthorizedException("Invalid or expired refresh token.") from exc
    if payload.get("type") != "refresh":
        raise UnauthorizedException("Invalid token type.")

    tenant_id = payload["tenant_id"]
    set_tenant_context(session, tenant_id)
    user = UserRepository(session, tenant_id).get(payload["sub"])
    if user is None or not user.is_active:
        raise UnauthorizedException("User no longer active.")

    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, user.role),
        refresh_token=create_refresh_token(user.id, user.tenant_id, user.role),
    )
