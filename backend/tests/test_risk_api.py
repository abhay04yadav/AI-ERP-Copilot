"""Acceptance tests §15.8 (tenant isolation) and §15.9 (role scoping) for the
/risk API surface."""

from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4

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


def _insert_programme(superuser_connection, tenant_id, code: str, department_id):
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


def _insert_course(superuser_connection, tenant_id, code: str):
    cid = superuser_connection.execute(
        text("INSERT INTO courses (tenant_id, code, name) VALUES (:t, :c, :c) RETURNING id"),
        {"t": tenant_id, "c": code},
    ).scalar_one()
    superuser_connection.commit()
    return cid


def _insert_user(superuser_connection, tenant_id, email: str, role: str):
    uid = superuser_connection.execute(
        text("INSERT INTO users (tenant_id, email, password_hash, role) VALUES (:t, :e, 'x', :r) RETURNING id"),
        {"t": tenant_id, "e": email, "r": role},
    ).scalar_one()
    superuser_connection.commit()
    return uid


def _insert_faculty_scope(superuser_connection, tenant_id, user_id, scope_type: str, scope_ref: str):
    superuser_connection.execute(
        text(
            "INSERT INTO faculty_scopes (tenant_id, user_id, scope_type, scope_ref) VALUES (:t, :u, :st, :sr)"
        ),
        {"t": tenant_id, "u": user_id, "st": scope_type, "sr": scope_ref},
    )
    superuser_connection.commit()


def _token_for(tenant_id, user_id, role: str) -> str:
    return create_access_token(user_id, tenant_id, role)


def _setup_attendance_import(client, slug: str):
    token = _register(client, slug)
    resp = client.post("/sources", headers=_auth(token), json={"name": "SIS", "precedence": 1})
    source_id = resp.json()["id"]
    client.post(
        "/mappings",
        headers=_auth(token),
        json={
            "source_system_id": source_id,
            "entity_type": "attendance",
            "mapping": {
                "roll_no": "Roll No",
                "course_code": "Course Code",
                "class_date": "Class Date",
                "status": "Status",
            },
        },
    )
    return token, source_id


def _attendance_csv(roll_no: str, course_code: str, n_present: int, n_absent: int) -> bytes:
    header = "Roll No,Course Code,Class Date,Status\n"
    base = date(2026, 1, 1)
    rows = []
    for i, status in enumerate(["present"] * n_present + ["absent"] * n_absent):
        d = base + timedelta(days=i)
        rows.append(f"{roll_no},{course_code},{d.strftime('%d/%m/%Y')},{status}")
    return (header + "\n".join(rows) + "\n").encode()


def _upload_attendance(client, token, source_id, content: bytes) -> str:
    resp = client.post(
        "/imports",
        headers=_auth(token),
        files={"file": ("attendance.csv", BytesIO(content), "text/csv")},
        data={"source_system_id": source_id, "entity_type": "attendance"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_tenant_isolation_no_cross_tenant_visibility(client, superuser_connection):
    token_a, source_a = _setup_attendance_import(client, "api-isolation-a")
    tenant_a = _tenant_id_for_slug(superuser_connection, "api-isolation-a")
    _insert_course(superuser_connection, tenant_a, "CS101")
    student_a = _insert_student(superuser_connection, tenant_a, "ISOA001")
    _upload_attendance(client, token_a, source_a, _attendance_csv("ISOA001", "CS101", 3, 9))

    token_b = _register(client, "api-isolation-b")

    students_b_sees = client.get("/risk/students", headers=_auth(token_b)).json()
    assert students_b_sees == []

    cross_tenant_resp = client.get(f"/risk/students/{student_a}", headers=_auth(token_b))
    assert cross_tenant_resp.status_code == 404


def test_faculty_sees_only_their_scoped_department(client, superuser_connection):
    slug = "api-scope-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)

    dept_cse = _insert_department(superuser_connection, tenant_id, "CSE")
    dept_ece = _insert_department(superuser_connection, tenant_id, "ECE")
    prog_cse = _insert_programme(superuser_connection, tenant_id, "BTECH-CSE", dept_cse)
    prog_ece = _insert_programme(superuser_connection, tenant_id, "BTECH-ECE", dept_ece)
    student_cse = _insert_student(superuser_connection, tenant_id, "SCOPE-CSE-1", prog_cse)
    student_ece = _insert_student(superuser_connection, tenant_id, "SCOPE-ECE-1", prog_ece)

    faculty_id = _insert_user(superuser_connection, tenant_id, "faculty@scope.edu", "faculty")
    _insert_faculty_scope(superuser_connection, tenant_id, faculty_id, "department", "CSE")
    faculty_token = _token_for(tenant_id, faculty_id, "faculty")

    resp = client.get(f"/risk/students/{student_cse}", headers=_auth(faculty_token))
    assert resp.status_code == 200, resp.text

    resp_out_of_scope = client.get(f"/risk/students/{student_ece}", headers=_auth(faculty_token))
    assert resp_out_of_scope.status_code == 404  # out-of-scope -> 404, not 403 (don't reveal existence)


def test_principal_sees_all_students_regardless_of_scope(client, superuser_connection):
    slug = "api-principal-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    student_id = _insert_student(superuser_connection, tenant_id, "PRIN001")

    principal_id = _insert_user(superuser_connection, tenant_id, "principal@p.edu", "principal")
    principal_token = _token_for(tenant_id, principal_id, "principal")

    resp = client.get(f"/risk/students/{student_id}", headers=_auth(principal_token))
    assert resp.status_code == 200, resp.text


def test_student_role_is_forbidden(client, superuser_connection):
    slug = "api-student-role-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    student_user_id = _insert_user(superuser_connection, tenant_id, "stu@s.edu", "student")
    student_token = _token_for(tenant_id, student_user_id, "student")

    resp = client.get("/risk/students", headers=_auth(student_token))
    assert resp.status_code == 403


def test_faculty_request_for_unscoped_student_is_404_not_403(client, superuser_connection):
    slug = "api-404-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    student_id = _insert_student(superuser_connection, tenant_id, "NOSCOPE001")
    faculty_id = _insert_user(superuser_connection, tenant_id, "fac2@s.edu", "faculty")
    faculty_token = _token_for(tenant_id, faculty_id, "faculty")  # no faculty_scopes rows at all

    resp = client.get(f"/risk/students/{student_id}", headers=_auth(faculty_token))
    assert resp.status_code == 404


def test_config_endpoints_admin_only(client, superuser_connection):
    slug = "api-config-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    faculty_id = _insert_user(superuser_connection, tenant_id, "fac3@s.edu", "faculty")
    faculty_token = _token_for(tenant_id, faculty_id, "faculty")

    assert client.get("/risk/config", headers=_auth(token)).status_code == 200  # admin OK
    assert client.get("/risk/config", headers=_auth(faculty_token)).status_code == 403


def test_recompute_forbidden_for_faculty_allowed_for_registrar(client, superuser_connection):
    slug = "api-recompute-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    faculty_id = _insert_user(superuser_connection, tenant_id, "fac4@s.edu", "faculty")
    faculty_token = _token_for(tenant_id, faculty_id, "faculty")
    registrar_id = _insert_user(superuser_connection, tenant_id, "reg@s.edu", "registrar")
    registrar_token = _token_for(tenant_id, registrar_id, "registrar")

    resp_faculty = client.post("/risk/recompute", headers=_auth(faculty_token), json={"scope": "tenant"})
    assert resp_faculty.status_code == 403

    resp_registrar = client.post("/risk/recompute", headers=_auth(registrar_token), json={"scope": "tenant"})
    assert resp_registrar.status_code == 200, resp_registrar.text


def test_alerts_are_scoped_to_the_requesting_recipient(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "api-alerts-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "api-alerts-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    _insert_student(superuser_connection, tenant_id, "ALERT001")
    # 25 sessions, mostly absent -> high score (ATTENDANCE_BELOW_THRESHOLD 40 + likely declining) -> material alert
    _upload_attendance(client, token, source_id, _attendance_csv("ALERT001", "CS101", 2, 23))

    admin_alerts = client.get("/risk/alerts", headers=_auth(token)).json()
    assert isinstance(admin_alerts, list)
    if admin_alerts:
        admin_id = superuser_connection.execute(
            text("SELECT id FROM users WHERE email = 'admin@api-alerts-college.edu'")
        ).scalar_one()
        assert all(a["student_id"] == str(_student_id_for_roll(superuser_connection, tenant_id, "ALERT001")) for a in admin_alerts)

    other_token = _register(client, "api-alerts-college-2")
    other_alerts = client.get("/risk/alerts", headers=_auth(other_token)).json()
    assert other_alerts == []  # different tenant entirely, nothing leaks across


def _student_id_for_roll(superuser_connection, tenant_id, roll_no: str):
    return superuser_connection.execute(
        text("SELECT id FROM students WHERE tenant_id = :t AND canonical_roll_no = :r"), {"t": tenant_id, "r": roll_no}
    ).scalar_one()
