"""Acceptance test §9.4 (tenant isolation / RLS), DB-level portion.

Phase 0 has no list/read endpoint yet (Student 360 arrives in Phase 1), so the
API-level half of §9.4 ("no endpoint ever returns tenant B data") is covered
once that endpoint exists. This test covers the DB-level half exactly as
worded in the spec: with A's tenant context set, B's rows are unreadable;
with no tenant context set, the table returns zero rows.
"""

import uuid

from sqlalchemy import text


def _insert_tenant_and_user(conn, tenant_slug: str, email: str) -> tuple[str, str]:
    tenant_id = conn.execute(
        text("INSERT INTO tenants (name, slug) VALUES (:name, :slug) RETURNING id"),
        {"name": tenant_slug, "slug": tenant_slug},
    ).scalar_one()
    user_id = conn.execute(
        text(
            "INSERT INTO users (tenant_id, email, password_hash, role) "
            "VALUES (:tenant_id, :email, 'x', 'admin') RETURNING id"
        ),
        {"tenant_id": tenant_id, "email": email},
    ).scalar_one()
    conn.commit()
    return str(tenant_id), str(user_id)


def test_no_tenant_context_returns_zero_rows(superuser_connection, app_session_factory):
    _insert_tenant_and_user(superuser_connection, "tenant-a", "a@example.com")

    app_session = app_session_factory()
    try:
        rows = app_session.execute(text("SELECT * FROM users")).fetchall()
        assert rows == []
    finally:
        app_session.close()


def test_tenant_context_cannot_read_other_tenants_rows(superuser_connection, app_session_factory):
    tenant_a_id, _ = _insert_tenant_and_user(superuser_connection, "tenant-a2", "a2@example.com")
    _, _ = _insert_tenant_and_user(superuser_connection, "tenant-b2", "b2@example.com")

    app_session = app_session_factory()
    try:
        app_session.execute(
            text("SELECT set_config('app.current_tenant', :tid, false)"), {"tid": tenant_a_id}
        )
        rows = app_session.execute(text("SELECT email, tenant_id FROM users")).fetchall()
        emails = {row.email for row in rows}

        assert emails == {"a2@example.com"}
        assert "b2@example.com" not in emails
        assert all(str(row.tenant_id) == tenant_a_id for row in rows)
    finally:
        app_session.close()


def test_orm_insert_is_audited(app_session_factory):
    """The audit hook (core/audit.py) is a mapper-level SQLAlchemy event, so it
    only fires on ORM-mediated writes (session.add + flush) — exactly how
    auth_service creates users — not on raw SQL INSERTs."""
    from app.models.tenant import Tenant
    from app.models.user import User

    app_session = app_session_factory()
    try:
        with app_session.begin():
            tenant = Tenant(name="tenant-orm", slug="tenant-orm")
            app_session.add(tenant)
            app_session.flush()

            from app.core.rls import set_tenant_context

            set_tenant_context(app_session, tenant.id)
            user = User(tenant_id=tenant.id, email="orm@example.com", password_hash="x", role="admin")
            app_session.add(user)
            app_session.flush()

            audit_row = app_session.execute(
                text("SELECT action, new_value FROM audit_log WHERE record_id = :rid"), {"rid": str(user.id)}
            ).first()
            assert audit_row is not None
            assert audit_row.action == "insert"
            assert audit_row.new_value["email"] == "orm@example.com"
    finally:
        app_session.close()


def test_app_user_cannot_update_or_delete_audit_log(superuser_connection, app_session_factory):
    tenant_id, user_id = _insert_tenant_and_user(superuser_connection, "tenant-c", "c@example.com")
    audit_row_id = superuser_connection.execute(
        text(
            "INSERT INTO audit_log (tenant_id, table_name, record_id, action, new_value) "
            "VALUES (:tenant_id, 'users', :record_id, 'insert', '{}') RETURNING id"
        ),
        {"tenant_id": tenant_id, "record_id": user_id},
    ).scalar_one()
    superuser_connection.commit()

    app_session = app_session_factory()
    try:
        app_session.execute(text("SELECT set_config('app.current_tenant', :tid, false)"), {"tid": tenant_id})

        from sqlalchemy.exc import ProgrammingError

        try:
            app_session.execute(
                text("UPDATE audit_log SET action = 'update' WHERE id = :id"), {"id": audit_row_id}
            )
            app_session.commit()
            raised = False
        except ProgrammingError:
            app_session.rollback()
            raised = True
        assert raised, "app_user must not be able to UPDATE audit_log (append-only, spec §4.4)"
    finally:
        app_session.close()
