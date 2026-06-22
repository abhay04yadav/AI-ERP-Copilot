"""Idempotent upsert into the canonical SoT (spec §5.6). Implemented as
application-level check-then-insert/update under the caller's transaction,
not literal SQL ON CONFLICT — natural keys still guarantee idempotency
(re-running finds the same row by its natural key and updates it in place),
but the conflict-precedence policy (§5.7) needs the existing value in hand to
decide whether to apply an incoming one, which a plain ON CONFLICT DO UPDATE
can't express conditionally per field. Documented in CHANGELOG.md.

Each upsert_* function is transactional in the sense that it's called inside
the pipeline's per-entity-type transaction (pipeline.py) — a failure partway
through rolls back the whole entity-type's batch, never a partial canonical
write (spec §5.6, acceptance test §9.5).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Attendance, Course, Department, Enrollment, Fee, InternalMark, Programme, Student
from app.services.ingestion.reconciliation.conflicts import apply_field_with_precedence
from app.services.ingestion.resolution.identity import write_link
from app.services.ingestion.resolution.resolver import ResolutionResult


class UnresolvedReferenceError(Exception):
    """A row references a parent (student/course/department/programme) that
    doesn't exist yet. The pipeline catches this per-row and quarantines the
    staging record rather than dropping it or auto-creating a placeholder
    parent (spec §1: never silently overwrite, never drop a bad row)."""


def _apply_provenance(entity, *, source_system_id: UUID, source_record_id: str, import_batch_id: UUID) -> None:
    entity.source_system_id = source_system_id
    entity.source_record_id = source_record_id
    entity.import_batch_id = import_batch_id
    entity.ingested_at = datetime.now(timezone.utc)


def _find_department(session: Session, tenant_id: UUID, code: str | None) -> Department | None:
    if not code:
        return None
    return session.execute(
        select(Department).where(Department.tenant_id == tenant_id, Department.code == code)
    ).scalar_one_or_none()


def _find_programme(session: Session, tenant_id: UUID, code: str | None) -> Programme | None:
    if not code:
        return None
    return session.execute(
        select(Programme).where(Programme.tenant_id == tenant_id, Programme.code == code)
    ).scalar_one_or_none()


def _find_course(session: Session, tenant_id: UUID, code: str | None) -> Course | None:
    if not code:
        return None
    return session.execute(select(Course).where(Course.tenant_id == tenant_id, Course.code == code)).scalar_one_or_none()


def _find_student_by_roll_no(session: Session, tenant_id: UUID, roll_no: str | None) -> Student | None:
    if not roll_no:
        return None
    return session.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.canonical_roll_no == roll_no)
    ).scalar_one_or_none()


def upsert_department(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Department:
    existing = _find_department(session, tenant_id, cleaned.get("code"))
    if existing is not None:
        if cleaned.get("name"):
            apply_field_with_precedence(
                session,
                entity=existing,
                field="name",
                incoming_value=cleaned["name"],
                table_name="departments",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        _apply_provenance(existing, **provenance)
        return existing

    department = Department(tenant_id=tenant_id, code=cleaned["code"], name=cleaned["name"])
    _apply_provenance(department, **provenance)
    session.add(department)
    session.flush()
    return department


def upsert_programme(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Programme:
    department = _find_department(session, tenant_id, cleaned.get("department_code"))
    if cleaned.get("department_code") and department is None:
        raise UnresolvedReferenceError(f"department not found: {cleaned['department_code']}")

    existing = _find_programme(session, tenant_id, cleaned.get("code"))
    if existing is not None:
        if cleaned.get("name"):
            apply_field_with_precedence(
                session,
                entity=existing,
                field="name",
                incoming_value=cleaned["name"],
                table_name="programmes",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        if department is not None:
            existing.department_id = department.id
        _apply_provenance(existing, **provenance)
        return existing

    programme = Programme(
        tenant_id=tenant_id,
        code=cleaned["code"],
        name=cleaned["name"],
        department_id=department.id if department else None,
    )
    _apply_provenance(programme, **provenance)
    session.add(programme)
    session.flush()
    return programme


def upsert_course(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Course:
    programme = _find_programme(session, tenant_id, cleaned.get("programme_code"))
    if cleaned.get("programme_code") and programme is None:
        raise UnresolvedReferenceError(f"programme not found: {cleaned['programme_code']}")

    existing = _find_course(session, tenant_id, cleaned.get("code"))
    if existing is not None:
        if cleaned.get("name"):
            apply_field_with_precedence(
                session,
                entity=existing,
                field="name",
                incoming_value=cleaned["name"],
                table_name="courses",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        if programme is not None:
            existing.programme_id = programme.id
        _apply_provenance(existing, **provenance)
        return existing

    course = Course(
        tenant_id=tenant_id,
        code=cleaned["code"],
        name=cleaned["name"],
        programme_id=programme.id if programme else None,
    )
    _apply_provenance(course, **provenance)
    session.add(course)
    session.flush()
    return course


_STUDENT_UPDATABLE_FIELDS = ("name", "dob", "gender", "category", "email", "phone", "admission_year", "status")


def upsert_student(
    session: Session,
    tenant_id: UUID,
    cleaned: dict,
    provenance: dict,
    resolution: ResolutionResult,
) -> Student | None:
    if resolution.pending_review:
        return None  # queued for manual review, not loaded (spec §5.5 rule 4)

    programme = _find_programme(session, tenant_id, cleaned.get("programme_code"))
    if cleaned.get("programme_code") and programme is None:
        raise UnresolvedReferenceError(f"programme not found: {cleaned['programme_code']}")

    if resolution.canonical_id is not None:
        student = session.get(Student, resolution.canonical_id)
        for field in _STUDENT_UPDATABLE_FIELDS:
            value = cleaned.get(field)
            if field == "dob" and value is not None:
                value = date.fromisoformat(value)
            if value is not None:
                apply_field_with_precedence(
                    session,
                    entity=student,
                    field=field,
                    incoming_value=value,
                    table_name="students",
                    tenant_id=tenant_id,
                    import_batch_id=provenance["import_batch_id"],
                    existing_source_id=student.source_system_id,
                    incoming_source_id=provenance["source_system_id"],
                )
        if programme is not None:
            student.programme_id = programme.id
        _apply_provenance(student, **provenance)
        return student

    student = Student(
        tenant_id=tenant_id,
        canonical_roll_no=cleaned["canonical_roll_no"],
        name=cleaned["name"],
        dob=date.fromisoformat(cleaned["dob"]) if cleaned.get("dob") else None,
        gender=cleaned.get("gender"),
        category=cleaned.get("category"),
        email=cleaned.get("email"),
        phone=cleaned.get("phone"),
        admission_year=cleaned.get("admission_year"),
        programme_id=programme.id if programme else None,
        status=cleaned.get("status"),
    )
    _apply_provenance(student, **provenance)
    session.add(student)
    session.flush()

    write_link(
        session,
        tenant_id=tenant_id,
        entity_type="student",
        source_system_id=provenance["source_system_id"],
        source_id=cleaned["canonical_roll_no"],
        canonical_id=student.id,
        match_method="deterministic",
        confidence=Decimal("100"),
        status="auto_linked",
    )
    return student


def upsert_enrollment(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Enrollment:
    student = _find_student_by_roll_no(session, tenant_id, cleaned.get("roll_no"))
    if student is None:
        raise UnresolvedReferenceError(f"student not found: roll_no={cleaned.get('roll_no')}")
    course = _find_course(session, tenant_id, cleaned.get("course_code"))
    if course is None:
        raise UnresolvedReferenceError(f"course not found: code={cleaned.get('course_code')}")

    existing = session.execute(
        select(Enrollment).where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.student_id == student.id,
            Enrollment.course_id == course.id,
            Enrollment.academic_year == cleaned["academic_year"],
        )
    ).scalar_one_or_none()

    if existing is not None:
        if cleaned.get("status") is not None:
            apply_field_with_precedence(
                session,
                entity=existing,
                field="status",
                incoming_value=cleaned["status"],
                table_name="enrollment",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        _apply_provenance(existing, **provenance)
        return existing

    enrollment = Enrollment(
        tenant_id=tenant_id,
        student_id=student.id,
        course_id=course.id,
        academic_year=cleaned["academic_year"],
        status=cleaned.get("status"),
    )
    _apply_provenance(enrollment, **provenance)
    session.add(enrollment)
    session.flush()
    return enrollment


def upsert_attendance(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Attendance:
    student = _find_student_by_roll_no(session, tenant_id, cleaned.get("roll_no"))
    if student is None:
        raise UnresolvedReferenceError(f"student not found: roll_no={cleaned.get('roll_no')}")
    course = _find_course(session, tenant_id, cleaned.get("course_code"))
    if course is None:
        raise UnresolvedReferenceError(f"course not found: code={cleaned.get('course_code')}")

    session_no = cleaned.get("session_no") or 1
    class_date = date.fromisoformat(cleaned["class_date"])

    existing = session.execute(
        select(Attendance).where(
            Attendance.tenant_id == tenant_id,
            Attendance.student_id == student.id,
            Attendance.course_id == course.id,
            Attendance.class_date == class_date,
            Attendance.session_no == session_no,
        )
    ).scalar_one_or_none()

    if existing is not None:
        apply_field_with_precedence(
            session,
            entity=existing,
            field="status",
            incoming_value=cleaned["status"],
            table_name="attendance",
            tenant_id=tenant_id,
            import_batch_id=provenance["import_batch_id"],
            existing_source_id=existing.source_system_id,
            incoming_source_id=provenance["source_system_id"],
        )
        _apply_provenance(existing, **provenance)
        return existing

    attendance = Attendance(
        tenant_id=tenant_id,
        student_id=student.id,
        course_id=course.id,
        class_date=class_date,
        session_no=session_no,
        status=cleaned["status"],
    )
    _apply_provenance(attendance, **provenance)
    session.add(attendance)
    session.flush()
    return attendance


def upsert_internal_mark(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> InternalMark:
    student = _find_student_by_roll_no(session, tenant_id, cleaned.get("roll_no"))
    if student is None:
        raise UnresolvedReferenceError(f"student not found: roll_no={cleaned.get('roll_no')}")
    course = _find_course(session, tenant_id, cleaned.get("course_code"))
    if course is None:
        raise UnresolvedReferenceError(f"course not found: code={cleaned.get('course_code')}")

    attempt = cleaned.get("attempt") or 1

    existing = session.execute(
        select(InternalMark).where(
            InternalMark.tenant_id == tenant_id,
            InternalMark.student_id == student.id,
            InternalMark.course_id == course.id,
            InternalMark.assessment_type == cleaned["assessment_type"],
            InternalMark.attempt == attempt,
        )
    ).scalar_one_or_none()

    if existing is not None:
        for field in ("max_marks", "obtained"):
            apply_field_with_precedence(
                session,
                entity=existing,
                field=field,
                incoming_value=cleaned[field],
                table_name="internal_marks",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        _apply_provenance(existing, **provenance)
        return existing

    mark = InternalMark(
        tenant_id=tenant_id,
        student_id=student.id,
        course_id=course.id,
        assessment_type=cleaned["assessment_type"],
        attempt=attempt,
        max_marks=cleaned["max_marks"],
        obtained=cleaned["obtained"],
    )
    _apply_provenance(mark, **provenance)
    session.add(mark)
    session.flush()
    return mark


def upsert_fee(session: Session, tenant_id: UUID, cleaned: dict, provenance: dict) -> Fee:
    student = _find_student_by_roll_no(session, tenant_id, cleaned.get("roll_no"))
    if student is None:
        raise UnresolvedReferenceError(f"student not found: roll_no={cleaned.get('roll_no')}")

    existing = session.execute(
        select(Fee).where(
            Fee.tenant_id == tenant_id,
            Fee.student_id == student.id,
            Fee.term == cleaned["term"],
            Fee.fee_head == cleaned["fee_head"],
        )
    ).scalar_one_or_none()

    if existing is not None:
        for field in ("amount_due", "amount_paid", "due_date", "paid_date", "status"):
            value = cleaned.get(field)
            if value is None:
                continue
            if field in ("due_date", "paid_date"):
                value = date.fromisoformat(value)
            apply_field_with_precedence(
                session,
                entity=existing,
                field=field,
                incoming_value=value,
                table_name="fees",
                tenant_id=tenant_id,
                import_batch_id=provenance["import_batch_id"],
                existing_source_id=existing.source_system_id,
                incoming_source_id=provenance["source_system_id"],
            )
        _apply_provenance(existing, **provenance)
        return existing

    fee = Fee(
        tenant_id=tenant_id,
        student_id=student.id,
        term=cleaned["term"],
        fee_head=cleaned["fee_head"],
        amount_due=cleaned.get("amount_due"),
        amount_paid=cleaned.get("amount_paid"),
        due_date=date.fromisoformat(cleaned["due_date"]) if cleaned.get("due_date") else None,
        paid_date=date.fromisoformat(cleaned["paid_date"]) if cleaned.get("paid_date") else None,
        status=cleaned.get("status"),
    )
    _apply_provenance(fee, **provenance)
    session.add(fee)
    session.flush()
    return fee
