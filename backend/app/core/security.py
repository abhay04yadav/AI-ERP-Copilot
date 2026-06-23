from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _create_token(user_id: UUID, tenant_id: UUID, role: str, expires_delta: timedelta, token_type: str) -> str:
    expire = datetime.now(UTC) + expires_delta
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "exp": expire,
        "type": token_type,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID, tenant_id: UUID, role: str) -> str:
    delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    return _create_token(user_id, tenant_id, role, delta, "access")


def create_refresh_token(user_id: UUID, tenant_id: UUID, role: str) -> str:
    delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    return _create_token(user_id, tenant_id, role, delta, "refresh")


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError (expired/invalid) — caller maps to UnauthorizedException."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
