from pydantic import BaseModel, Field

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=1)
    tenant_slug: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    admin_email: str = Field(pattern=_EMAIL_PATTERN)
    admin_password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    tenant_slug: str
    email: str = Field(pattern=_EMAIL_PATTERN)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
