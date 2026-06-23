"""Acceptance test §15.1: bulk computation returns correct attendance pct/
sessions, trend windows, latest-vs-baseline marks, failing count, and max
overdue days for a seeded dataset. Data is seeded directly via
superuser_connection (RLS-bypassing, like test_rls_isolation.py) and read
back through an app_session with tenant context set, exercising the real
RLS-scoped signal queries.
"""

from datetime import date, timedelta

from sqlalchemy import text

from app.core.rls import set_tenant_context
from app.services.risk.config import DEFAULT_RISK_CONFIG
from app.services.risk.signals.academic import compute_academic_signals
from app.services.risk.signals.attendance import compute_attendance_signals
from app.services.risk.signals.fees import compute_fee_signals

CONFIG = DEFAULT_RISK_CONFIG


def _tenant(conn, slug: str):
    tid = conn.execute(text("INSERT INTO tenants (name, slug) VALUES (:s, :s) RETURNING id"), {"s": slug}).scalar_one()
    conn.commit()
    return tid


def _student(conn, tenant_id, roll_no: str):
    sid = conn.execute(
        text("INSERT INTO students (tenant_id, canonical_roll_no, name) VALUES (:t, :r, :r) RETURNING id"),
        {"t": tenant_id, "r": roll_no},
    ).scalar_one()
    conn.commit()
    return sid


def _course(conn, tenant_id, code: str):
    cid = conn.execute(
        text("INSERT INTO courses (tenant_id, code, name) VALUES (:t, :c, :c) RETURNING id"), {"t": tenant_id, "c": code}
    ).scalar_one()
    conn.commit()
    return cid


def _attendance(conn, tenant_id, student_id, course_id, class_date, status, session_no=1):
    conn.execute(
        text(
            "INSERT INTO attendance (tenant_id, student_id, course_id, class_date, session_no, status) "
            "VALUES (:t, :s, :c, :d, :n, :st)"
        ),
        {"t": tenant_id, "s": student_id, "c": course_id, "d": class_date, "n": session_no, "st": status},
    )
    conn.commit()


def _mark(conn, tenant_id, student_id, course_id, assessment_type, attempt, max_marks, obtained, created_at):
    conn.execute(
        text(
            "INSERT INTO internal_marks (tenant_id, student_id, course_id, assessment_type, attempt, max_marks, "
            "obtained, created_at) VALUES (:t, :s, :c, :a, :att, :mx, :ob, :ca)"
        ),
        {
            "t": tenant_id,
            "s": student_id,
            "c": course_id,
            "a": assessment_type,
            "att": attempt,
            "mx": max_marks,
            "ob": obtained,
            "ca": created_at,
        },
    )
    conn.commit()


def _fee(conn, tenant_id, student_id, term, fee_head, amount_due, amount_paid, due_date):
    conn.execute(
        text(
            "INSERT INTO fees (tenant_id, student_id, term, fee_head, amount_due, amount_paid, due_date) "
            "VALUES (:t, :s, :term, :head, :due, :paid, :dd)"
        ),
        {"t": tenant_id, "s": student_id, "term": term, "head": fee_head, "due": amount_due, "paid": amount_paid, "dd": due_date},
    )
    conn.commit()


def _app_session(app_session_factory, tenant_id):
    session = app_session_factory()
    set_tenant_context(session, tenant_id)
    return session


def test_attendance_per_course_and_overall(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-a")
    student_id = _student(superuser_connection, tenant_id, "SIGA001")
    course1 = _course(superuser_connection, tenant_id, "CS101")
    course2 = _course(superuser_connection, tenant_id, "CS102")

    base = date(2026, 1, 1)
    for i, status in enumerate(["present", "present", "present", "absent"]):
        _attendance(superuser_connection, tenant_id, student_id, course1, base + timedelta(days=i), status)
    for i, status in enumerate(["present", "absent"]):
        _attendance(superuser_connection, tenant_id, student_id, course2, base + timedelta(days=10 + i), status)

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_attendance_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["overall_sessions"] == 6
        assert result["overall_attendance_pct"] == round(100 * 4 / 6, 2)

        by_course = {c.course_code: c for c in result["attendance_by_course"]}
        assert by_course["CS101"].present == 3 and by_course["CS101"].total == 4
        assert by_course["CS102"].present == 1 and by_course["CS102"].total == 2
    finally:
        session.close()


def test_attendance_trend_windows_computed_over_full_windows(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-b")
    student_id = _student(superuser_connection, tenant_id, "SIGB001")
    course = _course(superuser_connection, tenant_id, "CS201")
    window = CONFIG["attendance_trend_window"]  # 12

    base = date(2026, 1, 1)
    # Prior window (earliest 12): 10 present, 2 absent -> 83.33%
    prior_statuses = ["present"] * 10 + ["absent"] * 2
    # Recent window (latest 12): 6 present, 6 absent -> 50.0%
    recent_statuses = ["present"] * 6 + ["absent"] * 6
    for i, status in enumerate(prior_statuses + recent_statuses):
        _attendance(superuser_connection, tenant_id, student_id, course, base + timedelta(days=i), status)

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_attendance_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["attendance_prior_pct"] == round(100 * 10 / 12, 2)
        assert result["attendance_recent_pct"] == round(100 * 6 / 12, 2)
        assert result["overall_sessions"] == 2 * window
    finally:
        session.close()


def test_attendance_trend_windows_none_when_insufficient_history(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-c")
    student_id = _student(superuser_connection, tenant_id, "SIGC001")
    course = _course(superuser_connection, tenant_id, "CS301")

    base = date(2026, 1, 1)
    for i in range(5):  # far fewer than 2 * trend_window
        _attendance(superuser_connection, tenant_id, student_id, course, base + timedelta(days=i), "present")

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_attendance_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["attendance_recent_pct"] is None
        assert result["attendance_prior_pct"] is None
    finally:
        session.close()


def test_academic_latest_baseline_and_failing_count(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-d")
    student_id = _student(superuser_connection, tenant_id, "SIGD001")
    course = _course(superuser_connection, tenant_id, "CS401")

    t0 = "2026-01-01 09:00:00"
    t1 = "2026-02-01 09:00:00"
    t2 = "2026-03-01 09:00:00"
    _mark(superuser_connection, tenant_id, student_id, course, "CT1", 1, 100, 30, t0)  # 30% - failing
    _mark(superuser_connection, tenant_id, student_id, course, "CT2", 1, 100, 50, t1)  # 50%
    _mark(superuser_connection, tenant_id, student_id, course, "CT3", 1, 100, 45, t2)  # 45% - latest

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_academic_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["academic_latest_pct"] == 45.0
        assert result["academic_baseline_pct"] == 40.0  # mean(30, 50)
        assert result["failing_internal_count"] == 1  # only the 30% row is below 40%
        assert dict(result["latest_internal_pct_by_course"])["CS401"] == 45.0
    finally:
        session.close()


def test_fee_max_overdue_days_ignores_fully_paid(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-e")
    student_id = _student(superuser_connection, tenant_id, "SIGE001")

    today = date.today()
    _fee(superuser_connection, tenant_id, student_id, "T1", "tuition", 1000, 0, today - timedelta(days=40))
    _fee(superuser_connection, tenant_id, student_id, "T1", "library", 200, 200, today - timedelta(days=5))  # fully paid

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_fee_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["max_fee_overdue_days"] == 40
    finally:
        session.close()


def test_fee_no_overdue_rows_is_zero(superuser_connection, app_session_factory):
    tenant_id = _tenant(superuser_connection, "sig-f")
    student_id = _student(superuser_connection, tenant_id, "SIGF001")

    session = _app_session(app_session_factory, tenant_id)
    try:
        result = compute_fee_signals(session, tenant_id, [student_id], CONFIG)[student_id]
        assert result["max_fee_overdue_days"] == 0
    finally:
        session.close()
