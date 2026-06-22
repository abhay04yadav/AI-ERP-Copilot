from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant


class TenantRepository:
    """Not tenant-scoped itself — the `tenants` table has no tenant_id column
    and carries no RLS policy (spec §4.3 only applies RLS to tables that have
    one), so resolving a tenant by slug during login/registration never hits
    the RLS bootstrap problem."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.session.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()

    def add(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        return tenant
