from contextvars import ContextVar
from typing import Any
from uuid import UUID

from sqlalchemy import event, insert
from sqlalchemy.orm import Mapper
from sqlalchemy.orm.attributes import get_history

from app.models.audit import AuditLog

actor_user_id_ctx: ContextVar[str | None] = ContextVar("actor_user_id", default=None)


def _serialize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _changed_columns_snapshot(target: Any, columns: list) -> tuple[dict, dict]:
    old, new = {}, {}
    for col in columns:
        history = get_history(target, col.key)
        if history.deleted:
            old[col.key] = _serialize(history.deleted[0])
        if history.added:
            new[col.key] = _serialize(history.added[0])
    return old, new


def _write_audit_row(connection, tenant_id, table_name: str, record_id, action: str, old_value, new_value) -> None:
    connection.execute(
        insert(AuditLog.__table__).values(
            tenant_id=tenant_id,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_value=old_value or None,
            new_value=new_value or None,
            actor_user_id=actor_user_id_ctx.get(),
        )
    )


def register_audit_hooks(mapped_class: type) -> None:
    """Attach insert/update/soft-delete audit logging to a tenant-owned mapped class.

    The class must define `id` and `tenant_id`; soft-delete is detected when
    `is_deleted` flips False -> True on update. Called once per audited model
    at import time (see models/__init__.py wiring in Phase 1 for canonical tables).
    """
    table_name = mapped_class.__tablename__
    columns = [c for c in mapped_class.__table__.columns if c.key != "id"]

    @event.listens_for(mapped_class, "after_insert")
    def _after_insert(mapper: Mapper, connection, target) -> None:
        _, new_value = _changed_columns_snapshot(target, columns)
        _write_audit_row(connection, target.tenant_id, table_name, target.id, "insert", None, new_value)

    @event.listens_for(mapped_class, "after_update")
    def _after_update(mapper: Mapper, connection, target) -> None:
        old_value, new_value = _changed_columns_snapshot(target, columns)
        if not old_value and not new_value:
            return
        is_soft_delete = old_value.get("is_deleted") is False and new_value.get("is_deleted") is True
        action = "soft_delete" if is_soft_delete else "update"
        _write_audit_row(connection, target.tenant_id, table_name, target.id, action, old_value, new_value)
