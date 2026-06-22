from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class AttendanceSummary(BaseModel):
    course_id: UUID
    total_sessions: int
    present_sessions: int
    percentage: float


class InternalMarkSummary(BaseModel):
    course_id: UUID | None
    assessment_type: str
    attempt: int
    max_marks: Decimal
    obtained: Decimal


class FeeSummary(BaseModel):
    term: str
    fee_head: str
    amount_due: Decimal | None
    amount_paid: Decimal | None
    status: str | None


class Student360Response(BaseModel):
    id: UUID
    canonical_roll_no: str
    name: str
    dob: date | None
    gender: str | None
    category: str | None
    email: str | None
    phone: str | None
    admission_year: int | None
    programme_id: UUID | None
    status: str | None
    attendance_summary: list[AttendanceSummary]
    marks: list[InternalMarkSummary]
    fees: list[FeeSummary]
