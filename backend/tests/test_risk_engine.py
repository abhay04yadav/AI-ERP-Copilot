"""Acceptance tests §15.4 (determinism), §15.5 (idempotent recompute),
§15.6 (recompute on import), §15.7 (error isolation), §15.12 (config
effect), §15.13 (no N+1 in bulk signal computation).
"""

from datetime import date, timedelta
from io import BytesIO

from sqlalchemy import event, text

from app.core.rls import set_tenant_context
from app.services.risk.config import DEFAULT_RISK_CONFIG
from app.services.risk.evaluator.rules_evaluator import RulesRiskEvaluator
from app.services.risk.signals.academic import compute_academic_signals
from app.services.risk.signals.attendance import compute_attendance_signals
from app.services.risk.signals.base import StudentSignals
from app.services.risk.signals.fees import compute_fee_signals


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


def _insert_student(superuser_connection, tenant_id, roll_no: str):
    sid = superuser_connection.execute(
        text("INSERT INTO students (tenant_id, canonical_roll_no, name) VALUES (:t, :r, :r) RETURNING id"),
        {"t": tenant_id, "r": roll_no},
    ).scalar_one()
    superuser_connection.commit()
    return sid


def _attendance_csv(roll_no: str, course_code: str, n_present: int, n_absent: int) -> bytes:
    header = "Roll No,Course Code,Class Date,Status\n"
    base = date(2026, 1, 1)
    rows = []
    statuses = ["present"] * n_present + ["absent"] * n_absent
    for i, status in enumerate(statuses):
        d = base + timedelta(days=i)
        rows.append(f"{roll_no},{course_code},{d.strftime('%d/%m/%Y')},{status}")
    return (header + "\n".join(rows) + "\n").encode()


def _setup_attendance_import(client, slug: str):
    token = _register(client, slug)
    resp = client.post("/sources", headers=_auth(token), json={"name": "SIS", "precedence": 1})
    assert resp.status_code == 200, resp.text
    source_id = resp.json()["id"]
    resp = client.post(
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
    assert resp.status_code == 200, resp.text
    return token, source_id


def _upload_attendance(client, token, source_id, content: bytes) -> str:
    resp = client.post(
        "/imports",
        headers=_auth(token),
        files={"file": ("attendance.csv", BytesIO(content), "text/csv")},
        data={"source_system_id": source_id, "entity_type": "attendance"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_determinism_same_signals_and_config_yield_identical_result():
    """Acceptance test §15.4."""
    from uuid import uuid4

    signals = StudentSignals(
        student_id=uuid4(),
        dob=None,
        overall_attendance_pct=60.0,
        overall_sessions=20,
        attendance_by_course=(),
        attendance_recent_pct=None,
        attendance_prior_pct=None,
        latest_internal_pct_by_course=(),
        failing_internal_count=1,
        academic_latest_pct=None,
        academic_baseline_pct=None,
        max_fee_overdue_days=0,
    )
    evaluator = RulesRiskEvaluator()
    result1 = evaluator.evaluate(signals, DEFAULT_RISK_CONFIG)
    result2 = evaluator.evaluate(signals, DEFAULT_RISK_CONFIG)
    assert result1 == result2


def test_recompute_on_import_flags_student_and_import_stays_completed(client, superuser_connection):
    """Acceptance test §15.6."""
    token, source_id = _setup_attendance_import(client, "engine-import-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "engine-import-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    _insert_student(superuser_connection, tenant_id, "ENG001")

    content = _attendance_csv("ENG001", "CS101", n_present=3, n_absent=9)  # 12 sessions, 25% attendance
    batch_id = _upload_attendance(client, token, source_id, content)

    batch = client.get(f"/imports/{batch_id}", headers=_auth(token)).json()
    assert batch["status"] == "COMPLETED"

    resp = client.get("/risk/students", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    students = resp.json()
    assert len(students) == 1
    assert students[0]["tier"] == "watch"  # ATTENDANCE_BELOW_THRESHOLD alone scores 40 (watch cutoff 25, high 50)

    detail = client.get(f"/risk/students/{students[0]['student_id']}", headers=_auth(token)).json()
    codes = {f["code"] for f in detail["current"]["findings"]}
    assert "ATTENDANCE_BELOW_THRESHOLD" in codes


def test_idempotent_recompute_no_new_row_when_unchanged(client, superuser_connection):
    """Acceptance test §15.5 (unchanged half)."""
    token, source_id = _setup_attendance_import(client, "engine-idem-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "engine-idem-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    _insert_student(superuser_connection, tenant_id, "IDEM001")

    content = _attendance_csv("IDEM001", "CS101", n_present=3, n_absent=9)
    _upload_attendance(client, token, source_id, content)

    count_after_import = superuser_connection.execute(text("SELECT count(*) FROM risk_assessments")).scalar_one()
    assert count_after_import == 1

    resp = client.post("/risk/recompute", headers=_auth(token), json={"scope": "tenant"})
    summary = resp.json()
    assert summary["unchanged"] == 1
    assert summary["changed"] == 0

    count_after_recompute = superuser_connection.execute(text("SELECT count(*) FROM risk_assessments")).scalar_one()
    assert count_after_recompute == 1  # no new row -- idempotent


def test_changed_data_supersedes_and_retains_history(client, superuser_connection):
    """Acceptance test §15.5 (changed half)."""
    token, source_id = _setup_attendance_import(client, "engine-history-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "engine-history-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    _insert_student(superuser_connection, tenant_id, "HIST001")

    good_content = _attendance_csv("HIST001", "CS101", n_present=11, n_absent=1)  # 91.7%, fine
    _upload_attendance(client, token, source_id, good_content)

    first_assessment = superuser_connection.execute(
        text("SELECT id, tier, is_current FROM risk_assessments")
    ).one()
    assert first_assessment.tier == "low"
    assert first_assessment.is_current is True

    bad_content = _attendance_csv("HIST001", "CS101", n_present=2, n_absent=10)  # adds 12 more rows, drags pct down
    _upload_attendance(client, token, source_id, bad_content)

    rows = superuser_connection.execute(text("SELECT id, tier, is_current FROM risk_assessments")).all()
    assert len(rows) == 2  # history retained, nothing deleted
    current_rows = [r for r in rows if r.is_current]
    assert len(current_rows) == 1
    assert current_rows[0].id != first_assessment.id
    superseded = [r for r in rows if not r.is_current]
    assert superseded[0].id == first_assessment.id


def test_error_isolation_one_bad_student_does_not_abort_others(client, superuser_connection, monkeypatch):
    """Acceptance test §15.7."""
    token, source_id = _setup_attendance_import(client, "engine-isolation-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "engine-isolation-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    good_id = _insert_student(superuser_connection, tenant_id, "ISOG001")
    bad_id = _insert_student(superuser_connection, tenant_id, "ISOB001")

    for roll_no in ("ISOG001", "ISOB001"):
        content = _attendance_csv(roll_no, "CS101", n_present=3, n_absent=9)
        _upload_attendance(client, token, source_id, content)

    from app.services.risk import engine as engine_module

    real_evaluate = engine_module._evaluator.evaluate

    def flaky_evaluate(signals, config):
        if signals.student_id == bad_id:
            raise RuntimeError("injected failure for isolation test")
        return real_evaluate(signals, config)

    monkeypatch.setattr(engine_module._evaluator, "evaluate", flaky_evaluate)

    resp = client.post("/risk/recompute", headers=_auth(token), json={"scope": "tenant"})
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["evaluated"] == 1
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["student_id"] == str(bad_id)

    good_assessment = superuser_connection.execute(
        text("SELECT tier FROM risk_assessments WHERE student_id = :s AND is_current"), {"s": str(good_id)}
    ).scalar_one()
    assert good_assessment == "watch"


def test_config_effect_lowering_threshold_changes_which_students_flag(client, superuser_connection):
    """Acceptance test §15.12. 73.91% attendance is below the default 75%
    cutoff (flags) but not below a lowered 70% cutoff (stops flagging) -- a
    deterministic, opposite-direction change driven purely by config. Total
    sessions (23) is kept under 2x the trend window (24) so the declining-
    trend rule can't also fire and confound the tier."""
    token, source_id = _setup_attendance_import(client, "engine-config-college")
    tenant_id = _tenant_id_for_slug(superuser_connection, "engine-config-college")
    _insert_course(superuser_connection, tenant_id, "CS101")
    _insert_student(superuser_connection, tenant_id, "CFG001")

    content = _attendance_csv("CFG001", "CS101", n_present=17, n_absent=6)  # 23 sessions, 73.91%
    _upload_attendance(client, token, source_id, content)

    before = client.get("/risk/students", headers=_auth(token)).json()
    assert len(before) == 1
    assert before[0]["tier"] == "watch"  # 73.91% < default 75% threshold

    config_resp = client.get("/risk/config", headers=_auth(token))
    config = config_resp.json()["config"]
    config["attendance_threshold_pct"] = 70  # 72% is no longer below threshold

    update_resp = client.put("/risk/config", headers=_auth(token), json={"config": config})
    assert update_resp.status_code == 200, update_resp.text

    recompute_resp = client.post("/risk/recompute", headers=_auth(token), json={"scope": "tenant"})
    assert recompute_resp.status_code == 200, recompute_resp.text

    after = client.get("/risk/students", headers=_auth(token)).json()
    assert after == []  # the student no longer appears in the at-risk list at all (tier == low)


def test_no_n_plus_one_bulk_signal_query_count_is_bounded(superuser_connection, app_session_factory):
    """Acceptance test §15.13: the bulk signal-read phase (spec §1/§14's
    explicit "bulk aggregate queries, never N+1") issues a fixed number of
    queries regardless of how many students are in the batch."""
    tenant_id = _tenant_id_or_create(superuser_connection, "engine-n1-college")

    small_ids = [_insert_student(superuser_connection, tenant_id, f"N1S{i}") for i in range(3)]
    large_ids = [_insert_student(superuser_connection, tenant_id, f"N1L{i}") for i in range(30)]

    def count_queries(student_ids) -> int:
        session = app_session_factory()
        set_tenant_context(session, tenant_id)
        counter = {"n": 0}

        def on_execute(conn, cursor, statement, parameters, context, executemany):
            counter["n"] += 1

        event.listen(session.bind, "before_cursor_execute", on_execute)
        try:
            compute_attendance_signals(session, tenant_id, student_ids, DEFAULT_RISK_CONFIG)
            compute_academic_signals(session, tenant_id, student_ids, DEFAULT_RISK_CONFIG)
            compute_fee_signals(session, tenant_id, student_ids, DEFAULT_RISK_CONFIG)
        finally:
            event.remove(session.bind, "before_cursor_execute", on_execute)
            session.close()
        return counter["n"]

    small_count = count_queries(small_ids)
    large_count = count_queries(large_ids)
    assert small_count == large_count, "query count must not scale with student count"


def _tenant_id_or_create(superuser_connection, slug: str):
    tid = superuser_connection.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}).scalar_one_or_none()
    if tid is not None:
        return tid
    tid = superuser_connection.execute(
        text("INSERT INTO tenants (name, slug) VALUES (:s, :s) RETURNING id"), {"s": slug}
    ).scalar_one()
    superuser_connection.commit()
    return tid
