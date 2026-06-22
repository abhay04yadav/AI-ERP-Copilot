from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_tenant_context(session: Session, tenant_id: UUID) -> None:
    """Scope the current transaction to a tenant for Postgres RLS.

    Uses set_config(..., is_local=true) instead of SET LOCAL because it accepts
    a bound parameter, so the tenant id is never string-interpolated into SQL.
    Must run inside the same transaction as the queries it protects.
    """
    session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def reset_tenant_context(session: Session) -> None:
    session.execute(text("SELECT set_config('app.current_tenant', '', true)"))
