"""Acceptance test §15.10 (DPDP / minor handling, spec §9): age<18 =>
subject_minor_status='minor'; a manual parent_contact for a minor without
guardian_consent_confirmed=true is rejected; with it, accepted and the
confirmer recorded. The engine/alerts never auto-create a parent_contact
intervention or parent-directed alert for anyone, minor or not (spec §9) --
there is no parent-contact auto-creation code path anywhere in the engine to
begin with, which this file also confirms by construction.
"""

from datetime import date, timedelta
from io import BytesIO

from sqlalchemy import text

from app.services.risk.engine import compute_subject_minor_status


def test_compute_subject_minor_status_minor_adult_unknown():
    today = date(2026, 6, 23)
    assert compute_subject_minor_status(date(2009, 6, 24), today) == "minor"  # turns 17 tomorrow
    assert compute_subject_minor_status(date(2008, 6, 23), today) == "adult"  # turns 18 today
    assert compute_subject_minor_status(None, today) == "unknown"


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


def _insert_course(superuser_connection, tenant_id, code: str):
    cid = superuser_connection.execute(
        text("INSERT INTO courses (tenant_id, code, name) VALUES (:t, :c, :c) RETURNING id"),
        {"t": tenant_id, "c": code},
    ).scalar_one()
    superuser_connection.commit()
    return cid


def _insert_student(superuser_connection, tenant_id, roll_no: str, dob: date | None):
    sid = superuser_connection.execute(
        text("INSERT INTO students (tenant_id, canonical_roll_no, name, dob) VALUES (:t, :r, :r, :d) RETURNING id"),
        {"t": tenant_id, "r": roll_no, "d": dob},
    ).scalar_one()
    superuser_connection.commit()
    return sid


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
    statuses = ["present"] * n_present + ["absent"] * n_absent
    for i, status in enumerate(statuses):
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


def test_assessment_stamps_minor_status_for_under_18_student(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "minor-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "minor-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    minor_dob = date.today().replace(year=date.today().year - 17)
    student_id = _insert_student(superuser_connection, tenant_id, "MINOR001", minor_dob)

    content = _attendance_csv("MINOR001", "CS101", n_present=3, n_absent=9)
    _upload_attendance(client, token, source_id, content)

    detail = client.get(f"/risk/students/{student_id}", headers=_auth(token)).json()
    assert detail["current"]["subject_minor_status"] == "minor"


def test_assessment_stamps_adult_status_for_over_18_student(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "adult-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "adult-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    adult_dob = date.today().replace(year=date.today().year - 25)
    student_id = _insert_student(superuser_connection, tenant_id, "ADULT001", adult_dob)

    content = _attendance_csv("ADULT001", "CS101", n_present=3, n_absent=9)
    _upload_attendance(client, token, source_id, content)

    detail = client.get(f"/risk/students/{student_id}", headers=_auth(token)).json()
    assert detail["current"]["subject_minor_status"] == "adult"


def test_assessment_stamps_unknown_status_for_missing_dob(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "unknown-dob-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "unknown-dob-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    student_id = _insert_student(superuser_connection, tenant_id, "NODOB001", None)

    content = _attendance_csv("NODOB001", "CS101", n_present=3, n_absent=9)
    _upload_attendance(client, token, source_id, content)

    detail = client.get(f"/risk/students/{student_id}", headers=_auth(token)).json()
    assert detail["current"]["subject_minor_status"] == "unknown"


def test_parent_contact_for_minor_rejected_without_consent(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "consent-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "consent-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    minor_dob = date.today().replace(year=date.today().year - 16)
    student_id = _insert_student(superuser_connection, tenant_id, "CONSENT001", minor_dob)
    _upload_attendance(client, token, source_id, _attendance_csv("CONSENT001", "CS101", n_present=3, n_absent=9))

    resp = client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={"student_id": str(student_id), "type": "parent_contact", "title": "Call parent"},
    )
    assert resp.status_code == 403, resp.text

    count = superuser_connection.execute(text("SELECT count(*) FROM interventions")).scalar_one()
    assert count == 0


def test_parent_contact_for_minor_accepted_with_consent_and_confirmer_recorded(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "consent-ok-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "consent-ok-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    minor_dob = date.today().replace(year=date.today().year - 16)
    student_id = _insert_student(superuser_connection, tenant_id, "CONSENT002", minor_dob)
    _upload_attendance(client, token, source_id, _attendance_csv("CONSENT002", "CS101", n_present=3, n_absent=9))

    admin_id = superuser_connection.execute(
        text("SELECT id FROM users WHERE email = 'admin@consent-ok-college.edu'")
    ).scalar_one()

    resp = client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={
            "student_id": str(student_id),
            "type": "parent_contact",
            "title": "Call parent",
            "guardian_consent_confirmed": True,
        },
    )
    assert resp.status_code == 200, resp.text
    intervention_id = resp.json()["id"]

    confirmer = superuser_connection.execute(
        text("SELECT guardian_consent_confirmed_by FROM interventions WHERE id = :id"), {"id": intervention_id}
    ).scalar_one()
    assert str(confirmer) == str(admin_id)


def test_non_parent_intervention_for_minor_unrestricted(client, superuser_connection):
    token, source_id = _setup_attendance_import(client, "minor-mentor-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "minor-mentor-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    minor_dob = date.today().replace(year=date.today().year - 16)
    student_id = _insert_student(superuser_connection, tenant_id, "MENTOR001", minor_dob)
    _upload_attendance(client, token, source_id, _attendance_csv("MENTOR001", "CS101", n_present=3, n_absent=9))

    resp = client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={"student_id": str(student_id), "type": "mentor_meeting", "title": "Meet mentor"},
    )
    assert resp.status_code == 200, resp.text
