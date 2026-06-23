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
from app.models.risk import (
    FacultyScope,
    Intervention,
    InterventionOutcome,
    RiskAlert,
    RiskAssessment,
    RiskConfig,
    RiskFinding,
)
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

# Risk engine: mutable/security-relevant tables only (spec §4, build step 1).
# risk_findings and risk_alerts are intentionally excluded — see their model
# docstrings (immutable child of an audited parent; high-volume/non-critical).
for _risk_model in (RiskConfig, RiskAssessment, Intervention, InterventionOutcome, FacultyScope):
    register_audit_hooks(_risk_model)

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
    "RiskConfig",
    "RiskAssessment",
    "RiskFinding",
    "Intervention",
    "InterventionOutcome",
    "RiskAlert",
    "FacultyScope",
]
