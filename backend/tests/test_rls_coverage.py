from sqlalchemy import text

# Tables intentionally exempt from RLS, each with a written justification.
# Empty by default. Do NOT add to this to silence a failure without a real reason —
# a failure here usually means a table is missing its RLS block (spec §4.3).
EXEMPT_TABLES: dict[str, str] = {
    # "some_table": "reason it legitimately has no tenant scoping",
}


def test_every_tenant_table_has_rls_enabled_forced_and_policy(superuser_connection):
    tenant_tables = [
        r[0]
        for r in superuser_connection.execute(
            text(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relkind = 'r'
                  AND n.nspname = 'public'
                  AND a.attname = 'tenant_id'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        ).all()
    ]
    assert tenant_tables, "expected at least one tenant-scoped table — schema not migrated?"

    failures = []
    for table in tenant_tables:
        if table in EXEMPT_TABLES:
            continue
        sec = superuser_connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table},
        ).one()
        policy_count = superuser_connection.execute(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"),
            {"t": table},
        ).scalar_one()
        if not sec.relrowsecurity:
            failures.append(f"{table}: RLS not ENABLED")
        if not sec.relforcerowsecurity:
            failures.append(f"{table}: RLS not FORCED")
        if policy_count == 0:
            failures.append(f"{table}: no RLS policy present")

    assert not failures, "RLS coverage gaps (spec §4.3):\n" + "\n".join(failures)
