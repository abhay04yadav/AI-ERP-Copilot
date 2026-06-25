"""Acceptance tests for Phase 3 §A.5: GET /risk/summary and
GET /risk/summary/by-department. Risk assessments/findings are inserted
directly (bypassing the engine, which already has its own coverage in
test_risk_engine.py) so the seeded tier/finding mix is exact and
deterministic, matching this file's own conventions in test_risk_api.py."""

from sqlalchemy import text

from app.core.security import create_access_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, slug: str) -> str:
    resp = client.post(
        "/auth/register",
        json={
            "tenant_name": slug,
            "tenant_slug": slug,
            "admin_email": f"admin@{slug}.edu",
            "admin_password": "supersecret1",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _tenant_id_for_slug(superuser_connection, slug: str):
    return superuser_connection.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}).scalar_one()


def _insert_department(superuser_connection, tenant_id, code: str):
    did = superuser_connection.execute(
        text("INSERT INTO departments (tenant_id, code, name) VALUES (:t, :c, :c) RETURNING id"),
        {"t": tenant_id, "c": code},
    ).scalar_one()
    superuser_connection.commit()
    return did


def _insert_programme(superuser_connection, tenant_id, code: str, department_id=None):
    pid = superuser_connection.execute(
        text("INSERT INTO programmes (tenant_id, code, name, department_id) VALUES (:t, :c, :c, :d) RETURNING id"),
        {"t": tenant_id, "c": code, "d": department_id},
    ).scalar_one()
    superuser_connection.commit()
    return pid


def _insert_student(superuser_connection, tenant_id, roll_no: str, programme_id=None):
    sid = superuser_connection.execute(
        text(
            "INSERT INTO students (tenant_id, canonical_roll_no, name, programme_id) VALUES (:t, :r, :r, :p) "
            "RETURNING id"
        ),
        {"t": tenant_id, "r": roll_no, "p": programme_id},
    ).scalar_one()
    superuser_connection.commit()
    return sid


def _insert_user(superuser_connection, tenant_id, email: str, role: str):
    uid = superuser_connection.execute(
        text("INSERT INTO users (tenant_id, email, password_hash, role) VALUES (:t, :e, 'x', :r) RETURNING id"),
        {"t": tenant_id, "e": email, "r": role},
    ).scalar_one()
    superuser_connection.commit()
    return uid


def _insert_faculty_scope(superuser_connection, tenant_id, user_id, scope_type: str, scope_ref: str):
    superuser_connection.execute(
        text("INSERT INTO faculty_scopes (tenant_id, user_id, scope_type, scope_ref) VALUES (:t, :u, :st, :sr)"),
        {"t": tenant_id, "u": user_id, "st": scope_type, "sr": scope_ref},
    )
    superuser_connection.commit()


def _token_for(tenant_id, user_id, role: str) -> str:
    return create_access_token(user_id, tenant_id, role)


def _insert_assessment(superuser_connection, tenant_id, student_id, tier: str, score: float) -> str:
    aid = superuser_connection.execute(
        text(
            "INSERT INTO risk_assessments "
            "(tenant_id, student_id, is_current, model_type, model_version, config_version, overall_score, "
            "tier, subject_minor_status, signals_snapshot, triggered_by) "
            "VALUES (:t, :s, true, 'rules', '1.0', 1, :score, :tier, 'adult', '{}'::jsonb, 'manual') "
            "RETURNING id"
        ),
        {"t": tenant_id, "s": student_id, "score": score, "tier": tier},
    ).scalar_one()
    superuser_connection.commit()
    return aid


def _insert_finding(superuser_connection, tenant_id, assessment_id, risk_type: str, code: str, weight: float):
    superuser_connection.execute(
        text(
            "INSERT INTO risk_findings "
            "(tenant_id, assessment_id, risk_type, code, severity, weight_contribution, message, evidence) "
            "VALUES (:t, :a, :rt, :c, 'high', :w, 'seed', '{}'::jsonb)"
        ),
        {"t": tenant_id, "a": assessment_id, "rt": risk_type, "c": code, "w": weight},
    )
    superuser_connection.commit()


def test_summary_tier_and_type_counts(client, superuser_connection):
    slug = "summary-counts-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)

    s1 = _insert_student(superuser_connection, tenant_id, "SUM001")
    s2 = _insert_student(superuser_connection, tenant_id, "SUM002")
    s3 = _insert_student(superuser_connection, tenant_id, "SUM003")

    a1 = _insert_assessment(superuser_connection, tenant_id, s1, "high", 95)
    _insert_finding(superuser_connection, tenant_id, a1, "attendance", "ATTENDANCE_BELOW_THRESHOLD", 40)
    _insert_finding(superuser_connection, tenant_id, a1, "academic", "ACADEMIC_FAILING_INTERNALS", 35)

    a2 = _insert_assessment(superuser_connection, tenant_id, s2, "watch", 40)
    _insert_finding(superuser_connection, tenant_id, a2, "academic", "ACADEMIC_DECLINE", 20)
    _insert_finding(superuser_connection, tenant_id, a2, "fee", "FEE_OVERDUE", 15)

    _insert_assessment(superuser_connection, tenant_id, s3, "low", 0)

    resp = client.get("/risk/summary", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_assessed"] == 3
    assert body["by_tier"] == {"high": 1, "watch": 1, "low": 1}
    assert body["by_risk_type"] == {"attendance": 1, "academic": 2, "fee": 1}
    assert "generated_at" in body


def test_summary_role_scoping_faculty_vs_privileged(client, superuser_connection):
    slug = "summary-scope-college"
    _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)

    dept_cse = _insert_department(superuser_connection, tenant_id, "CSE")
    dept_ece = _insert_department(superuser_connection, tenant_id, "ECE")
    prog_cse = _insert_programme(superuser_connection, tenant_id, "BTECH-CSE", dept_cse)
    prog_ece = _insert_programme(superuser_connection, tenant_id, "BTECH-ECE", dept_ece)
    student_cse = _insert_student(superuser_connection, tenant_id, "SCOPE-CSE-1", prog_cse)
    student_ece = _insert_student(superuser_connection, tenant_id, "SCOPE-ECE-1", prog_ece)
    _insert_assessment(superuser_connection, tenant_id, student_cse, "high", 60)
    _insert_assessment(superuser_connection, tenant_id, student_ece, "watch", 30)

    faculty_id = _insert_user(superuser_connection, tenant_id, "faculty@scope.edu", "faculty")
    _insert_faculty_scope(superuser_connection, tenant_id, faculty_id, "department", "CSE")
    faculty_token = _token_for(tenant_id, faculty_id, "faculty")

    principal_id = _insert_user(superuser_connection, tenant_id, "principal@scope.edu", "principal")
    principal_token = _token_for(tenant_id, principal_id, "principal")

    faculty_summary = client.get("/risk/summary", headers=_auth(faculty_token)).json()
    assert faculty_summary["total_assessed"] == 1
    assert faculty_summary["by_tier"] == {"high": 1, "watch": 0, "low": 0}

    principal_summary = client.get("/risk/summary", headers=_auth(principal_token)).json()
    assert principal_summary["total_assessed"] == 2
    assert principal_summary["by_tier"] == {"high": 1, "watch": 1, "low": 0}

    faculty_by_dept = client.get("/risk/summary/by-department", headers=_auth(faculty_token)).json()
    assert faculty_by_dept["departments"] == [{"department": "CSE", "total": 1, "high": 1, "watch": 0, "low": 0}]


def test_summary_tenant_isolation(client, superuser_connection):
    _register(client, "summary-iso-a")
    tenant_a = _tenant_id_for_slug(superuser_connection, "summary-iso-a")
    student_a = _insert_student(superuser_connection, tenant_a, "ISOSUM001")
    _insert_assessment(superuser_connection, tenant_a, student_a, "high", 70)

    token_b = _register(client, "summary-iso-b")

    summary_b = client.get("/risk/summary", headers=_auth(token_b)).json()
    assert summary_b["total_assessed"] == 0
    assert summary_b["by_tier"] == {"high": 0, "watch": 0, "low": 0}

    by_dept_b = client.get("/risk/summary/by-department", headers=_auth(token_b)).json()
    assert by_dept_b["departments"] == []


def test_summary_by_department_groups_and_unassigned_bucket(client, superuser_connection):
    slug = "summary-dept-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)

    dept_cse = _insert_department(superuser_connection, tenant_id, "CSE")
    prog_cse = _insert_programme(superuser_connection, tenant_id, "BTECH-CSE", dept_cse)
    student_cse_high = _insert_student(superuser_connection, tenant_id, "DEPT-CSE-1", prog_cse)
    student_cse_low = _insert_student(superuser_connection, tenant_id, "DEPT-CSE-2", prog_cse)
    student_no_programme = _insert_student(superuser_connection, tenant_id, "DEPT-NONE-1")  # no programme_id at all

    _insert_assessment(superuser_connection, tenant_id, student_cse_high, "high", 60)
    _insert_assessment(superuser_connection, tenant_id, student_cse_low, "low", 0)
    _insert_assessment(superuser_connection, tenant_id, student_no_programme, "watch", 30)

    resp = client.get("/risk/summary/by-department", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    departments = {d["department"]: d for d in resp.json()["departments"]}
    assert departments["CSE"] == {"department": "CSE", "total": 2, "high": 1, "watch": 0, "low": 1}
    assert departments["Unassigned"] == {"department": "Unassigned", "total": 1, "high": 0, "watch": 1, "low": 0}


def test_summary_query_count_is_bounded_regardless_of_student_count(client, superuser_connection):
    """No-N+1 (spec §A.5.5): the number of SQL statements /risk/summary issues
    must not grow with the number of students."""
    slug = "summary-bounded-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)

    for i in range(3):
        sid = _insert_student(superuser_connection, tenant_id, f"BOUND-SMALL-{i}")
        _insert_assessment(superuser_connection, tenant_id, sid, "high", 50)

    from sqlalchemy import event

    from app.core.db import engine as app_engine

    counts: dict[str, int] = {"n": 0}

    def _count_statements(*_args, **_kwargs):
        counts["n"] += 1

    event.listen(app_engine, "before_cursor_execute", _count_statements)
    try:
        resp_small = client.get("/risk/summary", headers=_auth(token))
        assert resp_small.status_code == 200
        small_count = counts["n"]

        counts["n"] = 0
        for i in range(30):
            sid = _insert_student(superuser_connection, tenant_id, f"BOUND-LARGE-{i}")
            _insert_assessment(superuser_connection, tenant_id, sid, "high", 50)

        resp_large = client.get("/risk/summary", headers=_auth(token))
        assert resp_large.status_code == 200
        large_count = counts["n"]
    finally:
        event.remove(app_engine, "before_cursor_execute", _count_statements)

    assert small_count == large_count
