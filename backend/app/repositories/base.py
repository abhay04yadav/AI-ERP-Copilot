from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session


class TenantRepository:
    """Defense-in-depth: explicitly filters by tenant_id on every query, on top
    of (not instead of) Postgres RLS (spec §4.3)."""

    model: type

    def __init__(self, session: Session, tenant_id: UUID):
        self.session = session
        self.tenant_id = tenant_id

    def _scoped(self) -> Select:
        return select(self.model).where(self.model.tenant_id == self.tenant_id)

    def get(self, id_: UUID):
        return self.session.execute(self._scoped().where(self.model.id == id_)).scalar_one_or_none()

    def list(self):
        return self.session.execute(self._scoped()).scalars().all()

    def add(self, entity):
        self.session.add(entity)
        return entity
