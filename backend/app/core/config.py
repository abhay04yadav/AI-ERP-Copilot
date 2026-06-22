from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str
    """Postgres URL for the app's non-superuser role (app_user). RLS applies to this role."""

    migrations_database_url: str | None = None
    """Postgres URL used only by Alembic, as a privileged/owner role that can run DDL
    (CREATE ROLE app_user, GRANT, ENABLE/FORCE ROW LEVEL SECURITY, CREATE POLICY).
    Falls back to database_url for local dev against a superuser Postgres container."""

    app_db_password: str | None = None
    """Password the bootstrap migration assigns to the app_user role. Only read by
    migrations/versions/*; the running app never needs it (it connects via database_url)."""

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7


settings = Settings()
