"""Phase 1 acceptance tests (spec §9), exercised end-to-end through the API.

BackgroundTasks run synchronously within TestClient's request/response cycle
(Starlette runs them as part of finishing the same ASGI call), so by the time
client.post("/imports", ...) returns, the pipeline has already completed —
no polling/sleeping needed.
"""

from decimal import Decimal
from io import BytesIO

from sqlalchemy import text

STUDENT_MAPPING = {
    "canonical_roll_no": "Roll No",
    "name": "Full Name",
    "dob": "DOB",
    "gender": "Gender",
    "email": "Email",
    "phone": "Phone",
    "admission_year": "Admission Year",
}


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


def _create_source(client, token: str, name: str = "CSV Upload", precedence: int = 3) -> str:
    resp = client.post("/sources", headers=_auth(token), json={"name": name, "precedence": precedence})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_mapping(client, token: str, source_system_id: str, entity_type: str, mapping: dict) -> None:
    resp = client.post(
        "/mappings",
        headers=_auth(token),
        json={"source_system_id": source_system_id, "entity_type": entity_type, "mapping": mapping},
    )
    assert resp.status_code == 200, resp.text


def _upload(client, token: str, source_system_id: str, entity_type: str, filename: str, content: bytes):
    """Returns the import_batch_id. The POST response body is serialized
    before the background task (the pipeline) runs — Starlette sends the
    response, *then* awaits background tasks — so its JSON always shows the
    pre-pipeline "RECEIVED" status even though TestClient blocks until the
    background task finishes. Callers that need post-pipeline state must
    follow up with _get_batch()."""
    resp = client.post(
        "/imports",
        headers=_auth(token),
        files={"file": (filename, BytesIO(content), "text/csv")},
        data={"source_system_id": source_system_id, "entity_type": entity_type},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _get_batch(client, token: str, batch_id: str) -> dict:
    resp = client.get(f"/imports/{batch_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _setup_student_import(client, slug: str) -> tuple[str, str]:
    token = _register(client, slug)
    source_id = _create_source(client, token)
    _create_mapping(client, token, source_id, "student", STUDENT_MAPPING)
    return token, source_id


STUDENT_CSV_HEADER = "Roll No,Full Name,DOB,Gender,Email,Phone,Admission Year\n"


def test_idempotent_reimport_zero_duplicates(client, superuser_connection):
    token, source_id = _setup_student_import(client, "idem-college")
    content = (STUDENT_CSV_HEADER + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021\n").encode()

    first_id = _upload(client, token, source_id, "student", "students.csv", content)
    first_batch = _get_batch(client, token, first_id)
    assert first_batch["status"] == "COMPLETED"
    assert first_batch["row_count_loaded"] == 1

    second_id = _upload(client, token, source_id, "student", "students.csv", content)
    assert second_id == first_id  # same batch returned, not a new one

    count = superuser_connection.execute(text("SELECT count(*) FROM students")).scalar_one()
    assert count == 1


def test_entity_resolution_same_roll_no_across_files_is_one_student(client, superuser_connection):
    token, source_id = _setup_student_import(client, "resolve-a-college")
    file1 = (STUDENT_CSV_HEADER + "CS201,Aarav Sharma,15/01/2003,M,aarav@test.edu,9000000001,2021\n").encode()
    file2 = (STUDENT_CSV_HEADER + "CS201,Aarav Sharma,15/01/2003,M,aarav.new@test.edu,9000000001,2021\n").encode()

    _upload(client, token, source_id, "student", "f1.csv", file1)
    _upload(client, token, source_id, "student", "f2.csv", file2)

    rows = superuser_connection.execute(
        text("SELECT email FROM students WHERE canonical_roll_no = 'CS201'")
    ).all()
    assert len(rows) == 1
    assert rows[0].email == "aarav.new@test.edu"  # second file updated the existing student


def test_entity_resolution_same_name_different_roll_is_two_students(client, superuser_connection):
    token, source_id = _setup_student_import(client, "resolve-b-college")
    content = (
        STUDENT_CSV_HEADER
        + "CS301,Priya Verma,10/02/2002,F,priya1@test.edu,9000000002,2020\n"
        + "CS302,Priya Verma,22/07/2001,F,priya2@test.edu,9000000003,2020\n"
    ).encode()

    _upload(client, token, source_id, "student", "f.csv", content)

    count = superuser_connection.execute(
        text("SELECT count(*) FROM students WHERE name = 'Priya Verma'")
    ).scalar_one()
    assert count == 2


def test_no_data_loss_quarantine_balances_and_raw_file_retrievable(client, superuser_connection):
    token, source_id = _setup_student_import(client, "noloss-college")
    content = (
        STUDENT_CSV_HEADER
        + "CS401,Good Row,01/01/2003,M,good@test.edu,9000000004,2021\n"
        + "CS402,,01/01/2003,M,noname@test.edu,9000000005,2021\n"  # missing required name
    ).encode()

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)
    body = _get_batch(client, token, batch_id)
    assert body["row_count_raw"] == 2
    assert body["row_count_quarantined"] == 1
    assert body["row_count_loaded"] == 1
    report = body["reconciliation_report"]
    assert report["raw_count"] == report["valid_count"] + report["quarantined_count"]

    quarantine = client.get(f"/imports/{batch_id}/quarantine", headers=_auth(token)).json()
    assert len(quarantine) == 1
    assert "missing required field: name" in quarantine[0]["validation_errors"]["errors"]

    stored_content = superuser_connection.execute(
        text("SELECT content FROM raw_files WHERE import_batch_id = :id"), {"id": batch_id}
    ).scalar_one()
    assert bytes(stored_content) == content  # original file retained byte-for-byte


def test_transactional_load_no_partial_writes_on_failure(client, superuser_connection, monkeypatch):
    token, source_id = _setup_student_import(client, "txn-college")
    content = (
        STUDENT_CSV_HEADER
        + "CS501,First Student,01/01/2003,M,first@test.edu,9000000006,2021\n"
        + "CS502,Second Student,01/01/2003,F,second@test.edu,9000000007,2021\n"
    ).encode()

    from app.services.ingestion.loading import canonical_loader

    real_upsert = canonical_loader.upsert_student
    call_count = {"n": 0}

    def flaky_upsert(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("injected failure mid-load")
        return real_upsert(*args, **kwargs)

    monkeypatch.setattr(canonical_loader, "upsert_student", flaky_upsert)

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)
    body = _get_batch(client, token, batch_id)
    assert body["status"] == "FAILED"
    assert "injected failure mid-load" in body["error"]

    count = superuser_connection.execute(text("SELECT count(*) FROM students")).scalar_one()
    assert count == 0  # neither row persisted — no partial write


def test_conflict_handling_equal_precedence_keeps_existing_value(client, superuser_connection):
    token, source_a = _setup_student_import(client, "conflict-college")
    token_resp = client.post(
        "/sources", headers=_auth(token), json={"name": "Sheets Import", "precedence": 3}
    )
    source_b = token_resp.json()["id"]
    _create_mapping(client, token, source_b, "student", STUDENT_MAPPING)

    content_a = (STUDENT_CSV_HEADER + "CS601,Conflict Test,01/01/2003,M,a@test.edu,9000000008,2021\n").encode()
    content_b = (STUDENT_CSV_HEADER + "CS601,Conflict Test,01/01/2003,M,b@test.edu,9000000008,2021\n").encode()

    _upload(client, token, source_a, "student", "a.csv", content_a)
    _upload(client, token, source_b, "student", "b.csv", content_b)

    email = superuser_connection.execute(
        text("SELECT email FROM students WHERE canonical_roll_no = 'CS601'")
    ).scalar_one()
    assert email == "a@test.edu"  # existing value never silently overwritten

    conflict = superuser_connection.execute(
        text("SELECT field, existing_value, incoming_value, resolved FROM data_conflicts")
    ).one()
    assert conflict.field == "email"
    assert conflict.existing_value == "a@test.edu"
    assert conflict.incoming_value == "b@test.edu"
    assert conflict.resolved is False


def test_provenance_resolves_back_to_import_batch(client, superuser_connection):
    token, source_id = _setup_student_import(client, "provenance-college")
    content = (STUDENT_CSV_HEADER + "CS701,Provenance Test,01/01/2003,M,prov@test.edu,9000000009,2021\n").encode()

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)

    row = superuser_connection.execute(
        text(
            "SELECT source_system_id, import_batch_id, source_record_id FROM students "
            "WHERE canonical_roll_no = 'CS701'"
        )
    ).one()
    assert str(row.source_system_id) == source_id
    assert str(row.import_batch_id) == batch_id
    assert row.source_record_id is not None


def test_reconciliation_report_balances(client):
    token, source_id = _setup_student_import(client, "reconcile-college")
    content = (
        STUDENT_CSV_HEADER
        + "CS801,Aman Gupta,01/01/2003,M,v1@test.edu,9000000010,2021\n"
        + "CS802,Sunita Rao,19/06/1999,F,v2@test.edu,9000000011,2021\n"
        + "CS803,,01/01/2003,M,novalue@test.edu,9000000012,2021\n"
    ).encode()

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)
    report = _get_batch(client, token, batch_id)["reconciliation_report"]

    assert report["raw_count"] == 3
    assert report["valid_count"] == 2
    assert report["quarantined_count"] == 1
    assert report["loaded_count"] == 2
    assert report["valid_count"] == report["loaded_count"] + report["no_op_or_pending_review_count"]


def test_pipeline_loaded_row_has_correct_audit_actor(client, superuser_connection):
    slug = "audit-actor-college"
    token = _register(client, slug)
    source_id = _create_source(client, token)
    _create_mapping(client, token, source_id, "student", STUDENT_MAPPING)

    admin_user_id = superuser_connection.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": f"admin@{slug}.edu"}
    ).scalar_one()

    content = (STUDENT_CSV_HEADER + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021\n").encode()
    batch_id = _upload(client, token, source_id, "student", "students.csv", content)
    assert _get_batch(client, token, batch_id)["status"] == "COMPLETED"

    student_id = superuser_connection.execute(
        text("SELECT id FROM students WHERE canonical_roll_no = 'CS101'")
    ).scalar_one()

    actor = superuser_connection.execute(
        text(
            "SELECT actor_user_id FROM audit_log "
            "WHERE table_name = 'students' AND record_id = :rid AND action = 'insert'"
        ),
        {"rid": str(student_id)},
    ).scalar_one()
    assert str(actor) == str(admin_user_id), "pipeline-loaded canonical row must record the importing user as audit actor"


def test_reimport_different_bytes_same_rows_no_new_canonical(client, superuser_connection):
    token, source_id = _setup_student_import(client, "reimport-college")

    file1 = (STUDENT_CSV_HEADER + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021\n").encode()
    # Same logical row + an extra UNMAPPED column => different bytes (hash differs, pipeline re-runs)
    # but identical mapped/canonical data.
    file2 = (
        STUDENT_CSV_HEADER.rstrip("\n") + ",Notes\n"
        + "CS101,John Doe,12/05/2003,M,john@test.edu,9876543210,2021,ignore-me\n"
    ).encode()

    b1 = _upload(client, token, source_id, "student", "f1.csv", file1)
    assert _get_batch(client, token, b1)["status"] == "COMPLETED"

    b2 = _upload(client, token, source_id, "student", "f2.csv", file2)
    assert b2 != b1, "different bytes must NOT be hash-deduped — the pipeline must actually re-run"
    assert _get_batch(client, token, b2)["status"] == "COMPLETED"

    student_count = superuser_connection.execute(
        text("SELECT count(*) FROM students WHERE canonical_roll_no = 'CS101'")
    ).scalar_one()
    assert student_count == 1, "row-level upsert must update in place, not duplicate"

    link_count = superuser_connection.execute(
        text(
            "SELECT count(*) FROM entity_identity_map "
            "WHERE entity_type = 'student' AND source_id = 'CS101'"
        )
    ).scalar_one()
    assert link_count == 1, "identity map must be reused, not re-created"


def test_student_missing_roll_no_is_quarantined(client, superuser_connection):
    token, source_id = _setup_student_import(client, "noroll-college")
    content = (STUDENT_CSV_HEADER + ",No Roll Student,01/01/2003,M,noroll@test.edu,9000000010,2021\n").encode()

    batch_id = _upload(client, token, source_id, "student", "f.csv", content)
    body = _get_batch(client, token, batch_id)
    assert body["row_count_quarantined"] == 1
    assert body["row_count_loaded"] == 0

    count = superuser_connection.execute(text("SELECT count(*) FROM students")).scalar_one()
    assert count == 0
