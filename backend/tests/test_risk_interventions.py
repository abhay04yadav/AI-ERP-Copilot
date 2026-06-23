"""Acceptance test §15.11: intervention lifecycle (suggested -> assigned ->
in_progress -> completed -> outcome recorded), each write audited with the
correct actor."""

from datetime import date
from io import BytesIO

from sqlalchemy import text


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


def _insert_student(superuser_connection, tenant_id, roll_no: str):
    sid = superuser_connection.execute(
        text("INSERT INTO students (tenant_id, canonical_roll_no, name) VALUES (:t, :r, :r) RETURNING id"),
        {"t": tenant_id, "r": roll_no},
    ).scalar_one()
    superuser_connection.commit()
    return sid


def _admin_user_id(superuser_connection, slug: str):
    return superuser_connection.execute(
        text("SELECT id FROM users WHERE email = :e"), {"e": f"admin@{slug}.edu"}
    ).scalar_one()


def test_full_intervention_lifecycle_with_audit(client, superuser_connection):
    slug = "lifecycle-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    student_id = _insert_student(superuser_connection, tenant_id, "LIFE001")
    admin_id = _admin_user_id(superuser_connection, slug)

    create_resp = client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={"student_id": str(student_id), "type": "mentor_meeting", "title": "Weekly check-in"},
    )
    assert create_resp.status_code == 200, create_resp.text
    intervention = create_resp.json()
    assert intervention["status"] == "suggested"
    intervention_id = intervention["id"]

    assign_resp = client.patch(
        f"/risk/interventions/{intervention_id}",
        headers=_auth(token),
        json={"status": "open", "assigned_to": str(admin_id)},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json()["status"] == "open"
    assert assign_resp.json()["assigned_to"] == str(admin_id)

    progress_resp = client.patch(
        f"/risk/interventions/{intervention_id}", headers=_auth(token), json={"status": "in_progress"}
    )
    assert progress_resp.status_code == 200, progress_resp.text
    assert progress_resp.json()["status"] == "in_progress"

    complete_resp = client.patch(
        f"/risk/interventions/{intervention_id}", headers=_auth(token), json={"status": "completed"}
    )
    assert complete_resp.status_code == 200, complete_resp.text
    assert complete_resp.json()["status"] == "completed"

    outcome_resp = client.post(
        f"/risk/interventions/{intervention_id}/outcome",
        headers=_auth(token),
        json={"outcome": "improved", "notes": "Attendance picked back up."},
    )
    assert outcome_resp.status_code == 200, outcome_resp.text
    assert outcome_resp.json()["outcome"] == "improved"
    assert outcome_resp.json()["recorded_by"] == str(admin_id)

    # audit: the create (insert) and each PATCH (update) carry the admin as actor.
    audit_rows = superuser_connection.execute(
        text(
            "SELECT action, actor_user_id FROM audit_log WHERE table_name = 'interventions' AND record_id = :rid "
            "ORDER BY at"
        ),
        {"rid": intervention_id},
    ).all()
    assert len(audit_rows) >= 4  # insert + 3 updates
    assert all(str(row.actor_user_id) == str(admin_id) for row in audit_rows)
    assert audit_rows[0].action == "insert"
    assert all(row.action == "update" for row in audit_rows[1:])

    outcome_audit = superuser_connection.execute(
        text("SELECT actor_user_id FROM audit_log WHERE table_name = 'intervention_outcomes'")
    ).scalar_one()
    assert str(outcome_audit) == str(admin_id)


def test_list_interventions_filters_by_student_status_and_assignee(client, superuser_connection):
    slug = "list-college"
    token = _register(client, slug)
    tenant_id = _tenant_id_for_slug(superuser_connection, slug)
    student_a = _insert_student(superuser_connection, tenant_id, "LISTA001")
    student_b = _insert_student(superuser_connection, tenant_id, "LISTB001")
    admin_id = _admin_user_id(superuser_connection, slug)

    client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={"student_id": str(student_a), "type": "counselling", "title": "A's session"},
    )
    resp_b = client.post(
        "/risk/interventions",
        headers=_auth(token),
        json={"student_id": str(student_b), "type": "remedial_class", "title": "B's class", "assigned_to": str(admin_id)},
    )
    intervention_b_id = resp_b.json()["id"]

    by_student = client.get(f"/risk/interventions?student_id={student_a}", headers=_auth(token)).json()
    assert len(by_student) == 1
    assert by_student[0]["student_id"] == str(student_a)

    by_assignee = client.get(f"/risk/interventions?assigned_to={admin_id}", headers=_auth(token)).json()
    assert len(by_assignee) == 1
    assert by_assignee[0]["id"] == intervention_b_id

    by_status = client.get("/risk/interventions?status=suggested", headers=_auth(token)).json()
    assert len(by_status) == 2


def test_outcome_for_nonexistent_intervention_returns_404(client):
    token = _register(client, "missing-intervention-college")
    resp = client.post(
        f"/risk/interventions/00000000-0000-0000-0000-000000000000/outcome",
        headers=_auth(token),
        json={"outcome": "unknown"},
    )
    assert resp.status_code == 404
