"""Canonical SoT tables (spec §5.6/§6).

Natural keys for idempotent upsert are given explicitly in §5.6 for students,
attendance, internal_marks, fees, enrollment. For departments/programmes/
courses/faculty ("standard refs", §6) the spec doesn't name a natural key, so
each gets a `code`/`employee_code` column with a tenant-scoped unique
constraint — the conventional ERP pattern, documented in CHANGELOG.md.

semester_results is named in §5.6 but never given columns anywhere in the
spec; the schema below is a minimal, clearly-flagged invention (also in
CHANGELOG.md) and is NOT wired into the Phase 1 ingestion pipeline, same as
faculty — both get DDL now (per §6's blanket instruction) but no connector
entity_type yet.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, ProvenanceMixin, SoftDeleteMixin, TenantMixin, TimestampMixin


class Department(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_departments_tenant_code"),)

    name: Mapped[str] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(nullable=False)


class Programme(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "programmes"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_programmes_tenant_code"),)

    name: Mapped[str] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )


class Course(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_courses_tenant_code"),)

    name: Mapped[str] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(nullable=False)
    programme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programmes.id"), nullable=True
    )


class Faculty(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    """DDL only in Phase 1 — not wired into the ingestion connector yet."""

    __tablename__ = "faculty"
    __table_args__ = (UniqueConstraint("tenant_id", "employee_code", name="uq_faculty_tenant_employee_code"),)

    name: Mapped[str] = mapped_column(nullable=False)
    employee_code: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    status: Mapped[str | None] = mapped_column(nullable=True)


class Student(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("tenant_id", "canonical_roll_no", name="uq_students_tenant_roll_no"),)

    canonical_roll_no: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    dob: Mapped[date | None] = mapped_column(nullable=True)
    gender: Mapped[str | None] = mapped_column(nullable=True)
    category: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    admission_year: Mapped[int | None] = mapped_column(nullable=True)
    programme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programmes.id"), nullable=True
    )
    status: Mapped[str | None] = mapped_column(nullable=True)


class Enrollment(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "enrollment"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "course_id", "academic_year", name="uq_enrollment_natural_key"
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str | None] = mapped_column(nullable=True)


class Attendance(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "course_id", "class_date", "session_no", name="uq_attendance_natural_key"
        ),
        CheckConstraint("status IN ('present', 'absent', 'leave')", name="ck_attendance_status"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    class_date: Mapped[date] = mapped_column(nullable=False)
    session_no: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(nullable=False)


class InternalMark(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "internal_marks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "course_id", "assessment_type", "attempt", name="uq_internal_marks_natural_key"
        ),
    )

    # Phase 2 hardening part 2: NOT NULL enforced (was nullable per spec §6's
    # literal "student_id uuid, course_id uuid", which left the unique
    # constraint above unable to prevent duplicates across NULL rows --
    # Postgres treats every NULL as distinct. The loader already never
    # constructs a row without a resolved student/course (canonical_loader.py
    # ::upsert_internal_mark raises UnresolvedReferenceError otherwise, and
    # the pipeline quarantines on that); this is the DB-level backstop.
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    assessment_type: Mapped[str] = mapped_column(nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))
    max_marks: Mapped[Decimal] = mapped_column(nullable=False)
    obtained: Mapped[Decimal] = mapped_column(nullable=False)
    assessment_date: Mapped[date | None] = mapped_column(nullable=True)
    """Optional (Phase 2 hardening CHANGE 1): when a source provides a real
    assessment date, the risk engine's academic-decline signal orders by it
    instead of created_at (which is import time, not assessment time, for a
    bulk-imported term's marks). Absent for any row -> ordering falls back to
    created_at exactly as before, so this column is purely additive."""


class Fee(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    __tablename__ = "fees"
    __table_args__ = (UniqueConstraint("tenant_id", "student_id", "term", "fee_head", name="uq_fees_natural_key"),)

    # Phase 2 hardening part 2: NOT NULL enforced -- see InternalMark note above.
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    term: Mapped[str] = mapped_column(nullable=False)
    fee_head: Mapped[str] = mapped_column(nullable=False)
    amount_due: Mapped[Decimal | None] = mapped_column(nullable=True)
    amount_paid: Mapped[Decimal | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    paid_date: Mapped[date | None] = mapped_column(nullable=True)
    status: Mapped[str | None] = mapped_column(nullable=True)


class SemesterResult(PKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, ProvenanceMixin, Base):
    """Columns are not specified anywhere in the spec — minimal invented
    schema, DDL only in Phase 1 (see module docstring)."""

    __tablename__ = "semester_results"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "student_id",
            "course_id",
            "academic_year",
            "semester",
            "attempt",
            name="uq_semester_results_natural_key",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True)
    academic_year: Mapped[str] = mapped_column(nullable=False)
    semester: Mapped[int] = mapped_column(nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))
    grade: Mapped[str | None] = mapped_column(nullable=True)
    result_status: Mapped[str | None] = mapped_column(nullable=True)


class Hostel(PKMixin, TenantMixin, Base):
    """Forward-compat stub (spec §6) — create empty, no behaviour, no columns
    beyond identity, until a later phase defines its schema."""

    __tablename__ = "hostel"


class Placement(PKMixin, TenantMixin, Base):
    """Forward-compat stub (spec §6) — see Hostel docstring."""

    __tablename__ = "placement"


class ResearchPublication(PKMixin, TenantMixin, Base):
    """Forward-compat stub (spec §6) — see Hostel docstring."""

    __tablename__ = "research_publication"
