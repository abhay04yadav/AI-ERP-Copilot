"""Student entity resolution (spec §5.5). Other entity types (course,
department, programme, enrollment, attendance, internal_mark, fee) are
matched by direct natural-key upsert in loading/canonical_loader.py — they
don't need fuzzy identity resolution the way human-entered student records
do.

Resolution order, never auto-merging an ambiguous match:
  1. existing (source_system, source_id) mapping -> reuse canonical_id
  2. deterministic: normalized roll_no matches an existing canonical student
  3. fuzzy: score on name + dob (+ email/phone) -> high auto-links,
     medium queues a MergeReviewItem, low is treated as a new student
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Student
from app.models.identity import MergeReviewItem
from app.services.ingestion.resolution.identity import get_existing_link, write_link

# Tunable defaults (not specified by the spec, which only says "≥ threshold");
# documented here and in CHANGELOG.md, easy to make tenant-configurable later.
HIGH_CONFIDENCE = Decimal("90")
MEDIUM_CONFIDENCE = Decimal("70")


@dataclass
class ResolutionResult:
    canonical_id: UUID | None
    is_new: bool
    pending_review: bool
    """True means: queued for manual review, do NOT load this row (spec §5.5
    rule 4 — a wrong merge corrupts the SoT worse than a duplicate)."""


def resolve_student(session: Session, tenant_id: UUID, source_system_id: UUID, cleaned: dict) -> ResolutionResult:
    roll_no = cleaned.get("canonical_roll_no")

    if roll_no:
        existing_link = get_existing_link(session, tenant_id, "student", source_system_id, roll_no)
        if existing_link is not None:
            return ResolutionResult(canonical_id=existing_link.canonical_id, is_new=False, pending_review=False)

    if roll_no:
        match = session.execute(
            select(Student).where(Student.tenant_id == tenant_id, Student.canonical_roll_no == roll_no)
        ).scalar_one_or_none()
        if match is not None:
            write_link(
                session,
                tenant_id=tenant_id,
                entity_type="student",
                source_system_id=source_system_id,
                source_id=roll_no,
                canonical_id=match.id,
                match_method="deterministic",
                confidence=Decimal("100"),
                status="auto_linked",
            )
            return ResolutionResult(canonical_id=match.id, is_new=False, pending_review=False)

    name = cleaned.get("name")
    if name:
        candidate, score = _best_fuzzy_candidate(session, tenant_id, cleaned)
        if candidate is not None and score >= HIGH_CONFIDENCE:
            if roll_no:
                write_link(
                    session,
                    tenant_id=tenant_id,
                    entity_type="student",
                    source_system_id=source_system_id,
                    source_id=roll_no,
                    canonical_id=candidate.id,
                    match_method="fuzzy",
                    confidence=score,
                    status="auto_linked",
                )
            return ResolutionResult(canonical_id=candidate.id, is_new=False, pending_review=False)
        if candidate is not None and score >= MEDIUM_CONFIDENCE:
            session.add(
                MergeReviewItem(
                    tenant_id=tenant_id,
                    entity_type="student",
                    candidate_canonical_id=candidate.id,
                    incoming_payload=cleaned,
                    score=score,
                    status="pending_review",
                )
            )
            session.flush()
            return ResolutionResult(canonical_id=None, is_new=False, pending_review=True)

    return ResolutionResult(canonical_id=None, is_new=True, pending_review=False)


def _best_fuzzy_candidate(session: Session, tenant_id: UUID, cleaned: dict) -> tuple[Student | None, Decimal]:
    name = cleaned.get("name") or ""
    dob = cleaned.get("dob")
    email = cleaned.get("email")
    phone = cleaned.get("phone")

    candidates = (
        session.execute(select(Student).where(Student.tenant_id == tenant_id, Student.is_deleted.is_(False)))
        .scalars()
        .all()
    )

    best_candidate: Student | None = None
    best_score = Decimal("0")
    for candidate in candidates:
        score = _score(candidate, name, dob, email, phone)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    return best_candidate, best_score


def _score(candidate: Student, name: str, dob: str | None, email: str | None, phone: str | None) -> Decimal:
    name_score = fuzz.token_sort_ratio(name, candidate.name or "")
    dob_score = 100.0 if dob and candidate.dob and candidate.dob.isoformat() == dob else 0.0
    contact_score = 0.0
    if email and candidate.email and email == candidate.email:
        contact_score = 100.0
    elif phone and candidate.phone and phone == candidate.phone:
        contact_score = 100.0
    weighted = 0.5 * name_score + 0.4 * dob_score + 0.1 * contact_score
    return Decimal(str(round(weighted, 2)))
