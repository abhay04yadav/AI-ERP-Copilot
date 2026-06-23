from contextvars import ContextVar
from typing import Any
from uuid import UUID

from sqlalchemy import event, insert
from sqlalchemy.orm import Mapper, object_session
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


def _resolve_actor_user_id(target: Any) -> str | None:
    """Prefers the originating Session's own .info dict over the contextvar.

    actor_user_id_ctx alone is unreliable for writes that happen inside a
    FastAPI route handler body: get_tenant_session (a sync generator
    dependency) sets the contextvar in its pre-yield half, but FastAPI/
    Starlette dispatches the dependency's pre-yield half and the route
    handler itself as separate run_in_threadpool calls, each copying a fresh
    contextvars.Context from the *parent* async context -- so a .set() made
    inside the dependency's copied context never propagates forward to the
    handler's own copied context, even when, by coincidence, both land on
    the same OS thread (verified empirically; not just a theoretical risk).
    session.info is a plain dict on the Session *instance*, not a contextvar,
    so it survives this regardless of threading. The contextvar remains the
    fallback for callers that never attach to a request-scoped session (e.g.
    the ingestion pipeline's background task, which sets it once at the top
    of one continuous, non-threadpool-hopping call chain -- see
    services/ingestion/pipeline.py::run_pipeline)."""
    session = object_session(target)
    if session is not None:
        info_actor = session.info.get("actor_user_id")
        if info_actor is not None:
            return info_actor
    return actor_user_id_ctx.get()


def _write_audit_row(
    connection, tenant_id, table_name: str, record_id, action: str, old_value, new_value, actor_user_id: str | None
) -> None:
    connection.execute(
        insert(AuditLog.__table__).values(
            tenant_id=tenant_id,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_value=old_value or None,
            new_value=new_value or None,
            actor_user_id=actor_user_id,
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
        actor = _resolve_actor_user_id(target)
        _write_audit_row(connection, target.tenant_id, table_name, target.id, "insert", None, new_value, actor)

    @event.listens_for(mapped_class, "after_update")
    def _after_update(mapper: Mapper, connection, target) -> None:
        old_value, new_value = _changed_columns_snapshot(target, columns)
        if not old_value and not new_value:
            return
        is_soft_delete = old_value.get("is_deleted") is False and new_value.get("is_deleted") is True
        action = "soft_delete" if is_soft_delete else "update"
        actor = _resolve_actor_user_id(target)
        _write_audit_row(connection, target.tenant_id, table_name, target.id, action, old_value, new_value, actor)
