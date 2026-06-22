from app.core.audit import register_audit_hooks
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.canonical import (
    Attendance,
    Course,
    Department,
    Enrollment,
    Faculty,
    Fee,
    Hostel,
    InternalMark,
    Placement,
    Programme,
    ResearchPublication,
    SemesterResult,
    Student,
)
from app.models.conflict import DataConflict
from app.models.identity import EntityIdentityMap, MergeReviewItem
from app.models.ingestion import ColumnMapping, ImportBatch, RawFile, RawRecord, SourceSystem, StagingRecord
from app.models.tenant import Tenant
from app.models.user import User

register_audit_hooks(User)

# Canonical SoT tables only (spec §4.4) — not the ingestion-layer bookkeeping
# tables (import_batches, raw_*, staging_records) or tenant config
# (source_systems, column_mappings).
for _canonical_model in (
    Department,
    Programme,
    Course,
    Faculty,
    Student,
    Enrollment,
    Attendance,
    InternalMark,
    Fee,
    SemesterResult,
):
    register_audit_hooks(_canonical_model)

__all__ = [
    "Base",
    "Tenant",
    "User",
    "AuditLog",
    "SourceSystem",
    "ColumnMapping",
    "ImportBatch",
    "RawFile",
    "RawRecord",
    "StagingRecord",
    "EntityIdentityMap",
    "MergeReviewItem",
    "Department",
    "Programme",
    "Course",
    "Faculty",
    "Student",
    "Enrollment",
    "Attendance",
    "InternalMark",
    "Fee",
    "SemesterResult",
    "Hostel",
    "Placement",
    "ResearchPublication",
    "DataConflict",
]
